from collections.abc import Sequence
from dataclasses import replace

from .analyzer import Analyzer
from .transcript import collect_interactions
from .types import (
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
    "rg ",
    "pwd",
)


def is_mutating(interaction_name: str, tool_input: object) -> bool:
    if interaction_name in MUTATING_TOOLS:
        return True
    if interaction_name not in {"Bash", "Shell"}:
        return False
    if not isinstance(tool_input, dict):
        return True
    command = str(tool_input.get("command", "")).strip()
    return not command.startswith(READ_ONLY_COMMAND_PREFIXES)


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


def is_protected_evidence(span: EvidenceSpan, *, result_is_error: bool) -> bool:
    if span.kind in {
        "failing_test_or_error_location",
        "expected_value",
        "received_value",
    }:
        return result_is_error
    if span.kind == "url":
        return span.text.startswith(("https://", "http://"))
    if span.kind == "identifier_or_handle":
        return len(span.text) >= 6 and any(character.isdigit() for character in span.text)
    return span.kind == "requirement_subject"


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
            evidence = tuple(
                span
                for span in analyzer.extract_evidence(interaction.result.text)
                if span.confidence >= minimum_evidence_confidence
            )
            protected = tuple(
                span
                for span in evidence
                if is_protected_evidence(
                    span, result_is_error=interaction.result.is_error
                )
            )
            action, confidence, reasons = analyzer.classify(
                interaction,
                goal=goal,
                nearby_text=_nearby_text(messages, interaction.call_message_index),
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
        if message.text or tool_uses or tool_results:
            compacted.append(
                replace(
                    message, tool_uses=tool_uses, tool_results=tuple(tool_results)
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
