from collections.abc import Mapping, Sequence
from typing import Any

from .types import Message, RetentionDecision, ToolResult, ToolUse


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def messages_from_json(value: object) -> tuple[Message, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("messages must be an array")
    messages = []
    for index, raw_message in enumerate(value):
        item = _mapping(raw_message, f"messages[{index}]")
        raw_tool_uses = item.get("tool_uses", ())
        raw_tool_results = item.get("tool_results", ())
        if not isinstance(raw_tool_uses, Sequence) or isinstance(
            raw_tool_uses, (str, bytes)
        ):
            raise ValueError(f"messages[{index}].tool_uses must be an array")
        if not isinstance(raw_tool_results, Sequence) or isinstance(
            raw_tool_results, (str, bytes)
        ):
            raise ValueError(f"messages[{index}].tool_results must be an array")
        tool_uses = []
        for tool_index, raw_tool in enumerate(raw_tool_uses):
            tool = _mapping(
                raw_tool, f"messages[{index}].tool_uses[{tool_index}]"
            )
            tool_input = tool.get("input", {})
            if not isinstance(tool_input, Mapping):
                raise ValueError("tool input must be an object")
            tool_uses.append(
                ToolUse(
                    id=str(tool["id"]),
                    name=str(tool["name"]),
                    input=dict(tool_input),
                )
            )
        tool_results = []
        for result_index, raw_result in enumerate(raw_tool_results):
            result = _mapping(
                raw_result,
                f"messages[{index}].tool_results[{result_index}]",
            )
            tool_results.append(
                ToolResult(
                    tool_use_id=str(result["tool_use_id"]),
                    text=str(result.get("text", "")),
                    is_error=bool(result.get("is_error", False)),
                )
            )
        messages.append(
            Message(
                role=str(item["role"]),
                text=str(item.get("text", "")),
                tool_uses=tuple(tool_uses),
                tool_results=tuple(tool_results),
            )
        )
    return tuple(messages)


def decision_to_json(decision: RetentionDecision) -> dict[str, Any]:
    return {
        "tool_use_id": decision.tool_use_id,
        "action": decision.action.value,
        "confidence": decision.confidence,
        "reasons": list(decision.reasons),
        "evidence": [
            {
                "start": span.start,
                "end": span.end,
                "text": span.text,
                "kind": span.kind,
                "confidence": span.confidence,
            }
            for span in decision.evidence
        ],
    }
