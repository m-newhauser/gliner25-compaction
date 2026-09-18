from gliner25_context_compaction import (
    RetentionAction,
    compact_claude_messages,
    from_claude_messages,
    to_claude_messages,
)


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


def test_compaction_preserves_untouched_claude_envelopes():
    class DropAnalyzer:
        def extract_evidence(self, text):
            return ()

        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.DROP, 0.99, ("superseded",)

    source = [
        {"role": "user", "text": "Goal", "toolUses": [], "handle": "first"},
        {
            "role": "assistant",
            "text": "",
            "toolUses": [
                {"tool_use_id": "t1", "tool": "Read", "input": {"path": "a"}}
            ],
            "handle": "call",
        },
        {
            "role": "user",
            "text": "",
            "toolUses": [],
            "toolResults": [{"tool_use_id": "t1", "text": "old"}],
            "handle": "result",
        },
        {
            "role": "assistant",
            "text": "Continue",
            "toolUses": [],
            "handle": "last",
            "opaque": {"preserve": True},
        },
    ]
    _, output = compact_claude_messages(
        source, DropAnalyzer(), goal="Goal", preserve_recent=1
    )
    assert output == [source[0], source[3]]
    assert output[-1]["opaque"] == {"preserve": True}
