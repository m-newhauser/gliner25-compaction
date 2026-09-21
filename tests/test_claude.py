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
                {
                    "tool_use_id": "t1",
                    "tool": "Read",
                    "input": {"path": "a"},
                    "opaque_call": {"preserve": True},
                }
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


def test_compaction_preserves_modified_claude_envelopes():
    class CallOnlyAnalyzer:
        def extract_evidence(self, text):
            return ()

        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.KEEP_CALL_ONLY, 0.99, ("safely_rerunnable",)

    source = [
        {"role": "user", "text": "Goal", "toolUses": [], "handle": "first"},
        {
            "role": "assistant",
            "text": "",
            "toolUses": [
                {
                    "tool_use_id": "t1",
                    "tool": "Read",
                    "input": {"path": "a"},
                    "opaque_call": {"preserve": True},
                }
            ],
            "handle": "call",
        },
        {
            "role": "user",
            "text": "",
            "toolUses": [],
            "toolResults": [
                {
                    "tool_use_id": "t1",
                    "text": "ordinary output",
                    "opaque_result": {"preserve": True},
                }
            ],
            "handle": "result",
            "opaque": {"preserve": True},
        },
        {"role": "user", "text": "Continue", "toolUses": [], "handle": "last"},
    ]
    _, output = compact_claude_messages(
        source, CallOnlyAnalyzer(), goal="Goal", preserve_recent=0
    )
    modified = output[2]
    assert modified["handle"] == "result"
    assert modified["opaque"] == {"preserve": True}
    assert output[1]["toolUses"][0]["opaque_call"] == {"preserve": True}
    assert modified["toolResults"][0]["opaque_result"] == {"preserve": True}
    assert modified["toolResults"][0]["text"] == (
        "[tool result omitted; re-run if needed]"
    )
