from collections.abc import Sequence
from dataclasses import replace
import re

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
)

MUTATING_TOOLS = frozenset(
    {"Edit", "Write", "Delete", "NotebookEdit", "Deploy", "SendMessage"}
)

READ_ONLY_COMMAND_PREFIXES = (
    "pytest",
    "python -m pytest",
    "npm test",
    "npm run test",
    "npx vitest",
    "pnpm test",
    "pnpm exec vitest",
    "git status",
    "git diff",
    "git log",
    "rg",
    "pwd",
)

SHELL_CONTROL_OPERATOR = re.compile(r"(?:[\r\n;<>`]|\&\&|\|\||(?<!\|)\|(?!\|)|\$\()")


def is_mutating(interaction_name: str, tool_input: object) -> bool:
    if interaction_name in MUTATING_TOOLS:
        return True
    if interaction_name not in {"Bash", "Shell"}:
        return False
    if not isinstance(tool_input, dict):
        return True
    command = str(tool_input.get("command", "")).strip()
    if not command or SHELL_CONTROL_OPERATOR.search(command):
        return True
    return not any(
        command == prefix or command.startswith(f"{prefix} ")
        for prefix in READ_ONLY_COMMAND_PREFIXES
    )


def _message_characters(message: Message) -> int:
    return (
        len(message.text)
        + sum(len(str(tool.input)) for tool in message.tool_uses)
        + sum(len(result.text) for result in message.tool_results)
    )


def _nearby_text(messages: Sequence[Message], index: int, radius: int = 2) -> str:
    start, end = max(0, index - radius), min(len(messages), index + radius + 1)
    return "\n".join(message.text for message in messages[start:end] if message.text)


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
    return False


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
    candidates = [
        interaction
        for interaction in interactions
        if not interaction.pinned
        and not is_mutating(interaction.tool_use.name, interaction.tool_use.input)
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
            if protected:
                action, reasons, evidence = (
                    RetentionAction.KEEP_EVIDENCE,
                    (*reasons, "protected_evidence"),
                    protected,
                )
            elif confidence < minimum_confidence:
                action, reasons = RetentionAction.KEEP_FULL, (*reasons, "uncertain")
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
