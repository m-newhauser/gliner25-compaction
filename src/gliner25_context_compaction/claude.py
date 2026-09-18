from collections.abc import Mapping, Sequence
from typing import Any

from .analyzer import Analyzer
from .compact import compact
from .types import CompactionResult
from .types import Message, ToolResult, ToolUse


def from_claude_messages(messages: Sequence[Mapping[str, Any]]) -> tuple[Message, ...]:
    return tuple(
        Message(
            role=str(message["role"]),
            text=str(message.get("text", "")),
            tool_uses=tuple(
                ToolUse(
                    id=str(tool["tool_use_id"]),
                    name=str(tool["tool"]),
                    input=dict(tool.get("input", {})),
                )
                for tool in message.get("toolUses", ())
            ),
            tool_results=tuple(
                ToolResult(
                    tool_use_id=str(result["tool_use_id"]),
                    text=str(result.get("text", "")),
                    is_error=bool(result.get("isError", False)),
                )
                for result in message.get("toolResults", ())
            ),
        )
        for message in messages
    )


def to_claude_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    output = []
    for message in messages:
        item: dict[str, Any] = {
            "role": message.role,
            "text": message.text,
            "toolUses": [
                {
                    "tool_use_id": tool.id,
                    "tool": tool.name,
                    "input": tool.input,
                }
                for tool in message.tool_uses
            ],
        }
        if message.tool_results:
            item["toolResults"] = [
                {
                    "tool_use_id": result.tool_use_id,
                    "text": result.text,
                    "isError": result.is_error,
                }
                for result in message.tool_results
            ]
        output.append(item)
    return output


def compact_claude_messages(
    source: Sequence[Mapping[str, Any]],
    analyzer: Analyzer,
    **options: Any,
) -> tuple[CompactionResult, list[dict[str, Any]]]:
    normalized = from_claude_messages(source)
    originals = {id(message): dict(raw) for message, raw in zip(normalized, source)}
    result = compact(normalized, analyzer, **options)
    output = []
    for message in result.messages:
        original = originals.get(id(message))
        if original is not None:
            output.append(original)
            continue
        output.extend(to_claude_messages((message,)))
    return result, output
