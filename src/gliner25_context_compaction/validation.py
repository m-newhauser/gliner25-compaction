import math
from collections.abc import Sequence
from typing import Any

from .transcript import collect_interactions
from .types import CompactionResult, Message, RetentionAction


def validate_result(
    original: Sequence[Message], result: CompactionResult
) -> None:
    original_calls = {
        interaction.tool_use.id: interaction
        for interaction in collect_interactions(original, preserve_recent=0)
    }
    output_call_ids = {
        tool.id for message in result.messages for tool in message.tool_uses
    }
    output_result_ids = {
        item.tool_use_id
        for message in result.messages
        for item in message.tool_results
    }
    if not output_result_ids <= output_call_ids:
        raise ValueError("compacted transcript contains an orphaned tool result")

    original_text = [message.text for message in original if message.text]
    output_text = [message.text for message in result.messages if message.text]
    if output_text != original_text:
        raise ValueError("conversation text changed during compaction")

    for decision in result.decisions:
        interaction = original_calls.get(decision.tool_use_id)
        if interaction is None:
            raise ValueError(f"decision references unknown call {decision.tool_use_id}")
        if not math.isfinite(decision.confidence) or not 0 <= decision.confidence <= 1:
            raise ValueError(f"invalid confidence for {decision.tool_use_id}")
        if decision.action is RetentionAction.DROP and decision.tool_use_id in output_call_ids:
            raise ValueError(f"dropped call {decision.tool_use_id} survived")
        for span in decision.evidence:
            if (
                span.start < 0
                or span.end < span.start
                or span.end > len(interaction.result.text)
                or interaction.result.text[span.start : span.end] != span.text
            ):
                raise ValueError(f"invalid evidence span for {decision.tool_use_id}")


def deletion_manifest(result: CompactionResult) -> dict[str, Any]:
    return {
        "characters_before": result.original_characters,
        "characters_after": result.compacted_characters,
        "reduction": (
            0
            if result.original_characters == 0
            else 1 - result.compacted_characters / result.original_characters
        ),
        "decisions": [
            {
                "tool_use_id": decision.tool_use_id,
                "action": decision.action.value,
                "confidence": decision.confidence,
                "reasons": list(decision.reasons),
                "evidence": [
                    {
                        "kind": span.kind,
                        "start": span.start,
                        "end": span.end,
                        "text": span.text,
                        "confidence": span.confidence,
                    }
                    for span in decision.evidence
                ],
            }
            for decision in result.decisions
        ],
    }
