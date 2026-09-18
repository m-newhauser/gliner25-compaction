from collections.abc import Sequence

from .types import Message, ToolInteraction


def is_pinned(index: int, total: int, preserve_recent: int) -> bool:
    return index == 0 or index >= total - preserve_recent


def collect_interactions(
    messages: Sequence[Message], preserve_recent: int = 6
) -> tuple[ToolInteraction, ...]:
    results = {
        result.tool_use_id: (index, result)
        for index, message in enumerate(messages)
        for result in message.tool_results
    }
    interactions = []
    for call_index, message in enumerate(messages):
        for tool_use in message.tool_uses:
            matched = results.get(tool_use.id)
            if matched is None:
                continue
            result_index, result = matched
            interactions.append(
                ToolInteraction(
                    tool_use=tool_use,
                    result=result,
                    call_message_index=call_index,
                    result_message_index=result_index,
                    pinned=is_pinned(call_index, len(messages), preserve_recent)
                    or is_pinned(result_index, len(messages), preserve_recent),
                )
            )
    return tuple(interactions)
