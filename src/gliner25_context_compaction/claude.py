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


def _merge_tool_entries(
    original: object,
    rendered: object,
) -> list[dict[str, Any]]:
    original_items = (
        original
        if isinstance(original, Sequence) and not isinstance(original, (str, bytes))
        else ()
    )
    rendered_items = (
        rendered
        if isinstance(rendered, Sequence) and not isinstance(rendered, (str, bytes))
        else ()
    )
    by_id = {
        str(item.get("tool_use_id")): dict(item)
        for item in original_items
        if isinstance(item, Mapping)
    }
    output = []
    for rendered_item in rendered_items:
        if not isinstance(rendered_item, Mapping):
            continue
        tool_use_id = str(rendered_item.get("tool_use_id"))
        item = by_id.get(tool_use_id, {})
        item.update(rendered_item)
        output.append(item)
    return output


def compact_claude_messages(
    source: Sequence[Mapping[str, Any]],
    analyzer: Analyzer,
    **options: Any,
) -> tuple[CompactionResult, list[dict[str, Any]]]:
    normalized = from_claude_messages(source)
    indices_by_identity = {
        id(message): index for index, message in enumerate(normalized)
    }
    result = compact(normalized, analyzer, **options)
    output = []
    cursor = 0
    for message in result.messages:
        index = indices_by_identity.get(id(message))
        if index is None:
            tool_ids = {tool.id for tool in message.tool_uses}
            result_ids = {item.tool_use_id for item in message.tool_results}
            index = next(
                (
                    candidate_index
                    for candidate_index in range(cursor, len(normalized))
                    if normalized[candidate_index].role == message.role
                    and normalized[candidate_index].text == message.text
                    and tool_ids
                    <= {tool.id for tool in normalized[candidate_index].tool_uses}
                    and result_ids
                    <= {
                        item.tool_use_id
                        for item in normalized[candidate_index].tool_results
                    }
                ),
                None,
            )
        rendered = to_claude_messages((message,))[0]
        if index is None:
            output.append(rendered)
            continue
        item = dict(source[index])
        item["role"] = rendered["role"]
        item["text"] = rendered["text"]
        item["toolUses"] = _merge_tool_entries(
            source[index].get("toolUses", ()),
            rendered["toolUses"],
        )
        if "toolResults" in rendered:
            item["toolResults"] = _merge_tool_entries(
                source[index].get("toolResults", ()),
                rendered["toolResults"],
            )
        else:
            item.pop("toolResults", None)
        output.append(item)
        cursor = index + 1
    return result, output
