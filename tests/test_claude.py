from gliner25_context_compaction import from_claude_messages, to_claude_messages


def test_claude_adapter_round_trip():
    source = [
        {
            "role": "assistant",
            "text": "",
            "toolUses": [
                {
                    "tool_use_id": "t1",
                    "tool": "Read",
                    "input": {"file_path": "src/a.py"},
                }
            ],
        },
        {
            "role": "user",
            "text": "",
            "toolUses": [],
            "toolResults": [
                {"tool_use_id": "t1", "text": "contents", "isError": False}
            ],
        },
    ]
    assert to_claude_messages(from_claude_messages(source)) == source
