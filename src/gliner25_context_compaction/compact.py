from collections.abc import Sequence
from dataclasses import replace
import json
import re
import shlex

from .analyzer import Analyzer
from .transcript import collect_interactions
from .types import (
    AnalysisRequest,
    AnalysisResult,
    CompactionResult,
    EvidenceSpan,
    Message,
    RetentionAction,
    RetentionDecision,
    ToolResult,
    ToolInteraction,
)

MUTATING_TOOLS = frozenset(
    {
        "edit",
        "write",
        "delete",
        "notebookedit",
        "deploy",
        "sendmessage",
        "patch",
        "apply_patch",
        "question",
        "askquestion",
    }
)

READ_ONLY_TOOLS = frozenset(
    {
        "read",
        "glob",
        "grep",
        "search",
        "webfetch",
        "websearch",
        "lsp",
    }
)

SHELL_MUTATION_MARKERS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n")
DETERMINISTIC_READ_TOOLS = frozenset({"read", "glob", "grep"})

PROTECTING_REASONS = frozenset(
    {
        "current_dependency",
        "unresolved_failure",
        "binding_constraint",
        "non_reproducible",
        "mutation_record",
    }
)


def is_mutating(interaction_name: str, tool_input: object) -> bool:
    normalized_name = interaction_name.casefold()
    if normalized_name in MUTATING_TOOLS:
        return True
    if normalized_name in READ_ONLY_TOOLS:
        return False
    if normalized_name not in {"bash", "shell"}:
        return True
    if not isinstance(tool_input, dict):
        return True
    command = str(tool_input.get("command", "")).strip()
    if any(marker in command for marker in SHELL_MUTATION_MARKERS):
        return True
    try:
        arguments = shlex.split(command)
    except ValueError:
        return True
    if arguments == ["pwd"]:
        return False
    if arguments[:2] == ["git", "status"]:
        return any(
            argument.startswith("--output")
            or argument in {"--exec-path", "--html-path", "--man-path"}
            for argument in arguments[2:]
        )
    return True


def _message_characters(message: Message) -> int:
    return (
        len(message.text)
        + sum(len(str(tool.input)) for tool in message.tool_uses)
        + sum(len(result.text) for result in message.tool_results)
    )


def _superseded_interaction_ids(
    interactions: Sequence[ToolInteraction],
) -> set[str]:
    latest_by_signature: dict[tuple[str, str, str, bool], str] = {}
    superseded: set[str] = set()
    for interaction in interactions:
        tool_use = interaction.tool_use
        if is_mutating(tool_use.name, tool_use.input):
            latest_by_signature.clear()
            continue
        name = tool_use.name.casefold()
        if name not in DETERMINISTIC_READ_TOOLS:
            continue
        signature = (
            name,
            json.dumps(tool_use.input, sort_keys=True, separators=(",", ":")),
            interaction.result.text,
            interaction.result.is_error,
        )
        previous = latest_by_signature.get(signature)
        if previous is not None:
            superseded.add(previous)
        latest_by_signature[signature] = tool_use.id
    return superseded


def _message_context(message: Message, result_characters: int = 500) -> str:
    pieces = [f"ROLE: {message.role}"]
    if message.text:
        pieces.append(f"TEXT: {message.text}")
    for tool in message.tool_uses:
        pieces.append(f"TOOL {tool.id}: {tool.name} {tool.input}")
    for result in message.tool_results:
        text = result.text
        if len(text) > result_characters:
            text = f"{text[:result_characters]}\n[... truncated ...]"
        pieces.append(f"RESULT {result.tool_use_id}: {text}")
    return "\n".join(pieces)


def _nearby_text(messages: Sequence[Message], index: int, radius: int = 4) -> str:
    start, end = max(0, index - radius), min(len(messages), index + radius + 1)
    return "\n\n".join(_message_context(message) for message in messages[start:end])


def _merge_ranges(
    spans: Sequence[EvidenceSpan], text_length: int, context_characters: int
) -> list[tuple[int, int]]:
    ranges = sorted(
        (
            max(0, span.start - context_characters),
            min(text_length, span.end + context_characters),
        )
        for span in spans
    )
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def evidence_text(
    text: str, spans: Sequence[EvidenceSpan], context_characters: int = 120
) -> str:
    ranges = _merge_ranges(spans, len(text), context_characters)
    pieces = [text[start:end] for start, end in ranges]
    return "\n[... omitted ...]\n".join(pieces)


DIAGNOSTIC_MARKER = re.compile(
    r"\b(?:FAIL|FAILED|ERROR|Expected|Received|Traceback|AssertionError)\b",
    re.IGNORECASE,
)


def is_protected_evidence(
    span: EvidenceSpan, *, result_text: str, result_is_error: bool
) -> bool:
    if span.kind in {
        "failing_test_or_error_location",
        "expected_value",
        "received_value",
    }:
        context = result_text[max(0, span.start - 120) : span.end + 120]
        return result_is_error or DIAGNOSTIC_MARKER.search(context) is not None
    if span.kind == "url":
        return span.text.startswith(("https://", "http://"))
    if span.kind == "identifier_or_handle":
        return (
            len(span.text) >= 6
            and not any(character.isspace() for character in span.text)
            and any(character.isalpha() for character in span.text)
            and any(character.isdigit() for character in span.text)
        )
    return span.kind == "requirement_subject"


def _legacy_analysis(analyzer: object, request: AnalysisRequest) -> AnalysisResult:
    action, confidence, reasons = analyzer.classify(
        request.interaction,
        goal=request.goal,
        nearby_text=request.nearby_text,
    )
    return AnalysisResult(
        action=action,
        confidence=confidence,
        reasons=reasons,
        evidence=tuple(analyzer.extract_evidence(request.interaction.result.text)),
    )


def compact(
    messages: Sequence[Message],
    analyzer: Analyzer,
    *,
    goal: str,
    preserve_recent: int = 6,
    minimum_confidence: float = 0.7,
    minimum_evidence_confidence: float = 0.5,
    context_characters: int = 120,
) -> CompactionResult:
    interactions = collect_interactions(messages, preserve_recent)
    superseded_ids = _superseded_interaction_ids(interactions)
    candidates = [
        interaction
        for interaction in interactions
        if not interaction.pinned
        and not is_mutating(interaction.tool_use.name, interaction.tool_use.input)
        and interaction.tool_use.id not in superseded_ids
    ]
    requests = tuple(
        AnalysisRequest(
            interaction=interaction,
            goal=goal,
            nearby_text=_nearby_text(messages, interaction.call_message_index),
        )
        for interaction in candidates
    )
    analyze_many = getattr(analyzer, "analyze_many", None)
    if callable(analyze_many):
        analyses = tuple(analyze_many(requests))
    else:
        analyses = tuple(_legacy_analysis(analyzer, request) for request in requests)
    if len(analyses) != len(candidates):
        raise ValueError("analyzer response length does not match candidates")
    analysis_by_id = {
        interaction.tool_use.id: analysis
        for interaction, analysis in zip(candidates, analyses)
    }
    decisions: list[RetentionDecision] = []
    for interaction in interactions:
        if interaction.pinned or is_mutating(
            interaction.tool_use.name, interaction.tool_use.input
        ):
            decision = RetentionDecision(
                tool_use_id=interaction.tool_use.id,
                action=RetentionAction.KEEP_FULL,
                confidence=1.0,
                reasons=("pinned" if interaction.pinned else "mutation_record",),
            )
        elif interaction.tool_use.id in superseded_ids:
            decision = RetentionDecision(
                tool_use_id=interaction.tool_use.id,
                action=RetentionAction.DROP,
                confidence=1.0,
                reasons=("deterministic_superseded_read",),
            )
        else:
            analysis = analysis_by_id[interaction.tool_use.id]
            evidence = tuple(
                span
                for span in analysis.evidence
                if span.confidence >= minimum_evidence_confidence
            )
            protected = tuple(
                span
                for span in evidence
                if is_protected_evidence(
                    span,
                    result_text=interaction.result.text,
                    result_is_error=interaction.result.is_error,
                )
            )
            action, confidence, reasons = (
                analysis.action,
                analysis.confidence,
                analysis.reasons,
            )
            if confidence < minimum_confidence:
                action, reasons = RetentionAction.KEEP_FULL, (*reasons, "uncertain")
            elif action is RetentionAction.KEEP_FULL:
                pass
            elif PROTECTING_REASONS.intersection(reasons):
                action, reasons = (
                    RetentionAction.KEEP_FULL,
                    (*reasons, "contradictory_destructive_decision"),
                )
            elif protected:
                action, reasons, evidence = (
                    RetentionAction.KEEP_EVIDENCE,
                    (*reasons, "protected_evidence"),
                    protected,
                )
            elif interaction.result.is_error:
                action, reasons = (
                    RetentionAction.KEEP_FULL,
                    (*reasons, "unresolved_error_without_evidence"),
                )
            elif action is RetentionAction.KEEP_EVIDENCE and not evidence:
                action, reasons = RetentionAction.KEEP_FULL, (*reasons, "no_evidence")
            decision = RetentionDecision(
                tool_use_id=interaction.tool_use.id,
                action=action,
                confidence=confidence,
                reasons=reasons,
                evidence=evidence,
            )
        decisions.append(decision)

    by_id = {decision.tool_use_id: decision for decision in decisions}
    compacted: list[Message] = []
    for message in messages:
        tool_uses = tuple(
            tool
            for tool in message.tool_uses
            if by_id.get(tool.id, None) is None
            or by_id[tool.id].action is not RetentionAction.DROP
        )
        tool_results = []
        for result in message.tool_results:
            decision = by_id.get(result.tool_use_id)
            if decision is None or decision.action is RetentionAction.KEEP_FULL:
                tool_results.append(result)
            elif decision.action is RetentionAction.KEEP_EVIDENCE:
                tool_results.append(
                    replace(
                        result,
                        text=evidence_text(
                            result.text, decision.evidence, context_characters
                        ),
                    )
                )
            elif decision.action is RetentionAction.KEEP_CALL_ONLY:
                tool_results.append(
                    replace(result, text="[tool result omitted; re-run if needed]")
                )
        kept_results = tuple(tool_results)
        if message.text or tool_uses or kept_results:
            uses_unchanged = len(tool_uses) == len(message.tool_uses) and all(
                current is original
                for current, original in zip(tool_uses, message.tool_uses)
            )
            results_unchanged = len(kept_results) == len(
                message.tool_results
            ) and all(
                current is original
                for current, original in zip(kept_results, message.tool_results)
            )
            if uses_unchanged and results_unchanged:
                compacted.append(message)
            else:
                compacted.append(
                    replace(
                        message,
                        tool_uses=tool_uses,
                        tool_results=kept_results,
                    )
                )

    original_chars = sum(_message_characters(message) for message in messages)
    compacted_chars = sum(_message_characters(message) for message in compacted)
    return CompactionResult(
        messages=tuple(compacted),
        decisions=tuple(decisions),
        original_characters=original_chars,
        compacted_characters=compacted_chars,
    )
