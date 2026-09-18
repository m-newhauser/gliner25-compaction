from gliner25_context_compaction import RetentionAction
from gliner25_context_compaction import worker


class DropAnalyzer:
    def extract_evidence(self, text):
        return ()

    def classify(self, interaction, *, goal, nearby_text):
        return RetentionAction.DROP, 0.99, ("superseded",)


def test_worker_returns_atomic_messages_and_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(
        worker.GlinerAnalyzer,
        "from_pretrained",
        lambda checkpoint: DropAnalyzer(),
    )
    payload = {
        "messages": [
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
            {"role": "user", "text": "Continue", "toolUses": [], "handle": "last"},
        ],
        "options": {"goal": "Goal", "preserve_recent": 1},
        "capture_path": str(tmp_path / "capture.json"),
    }
    output = worker.run(payload)
    assert [message["handle"] for message in output["messages"]] == [
        "first",
        "last",
    ]
    assert output["manifest"]["decisions"][0]["action"] == "drop"
    captured = (tmp_path / "capture.json").read_text()
    assert '"request"' in captured
    assert '"manifest"' in captured


def test_worker_rejects_unknown_options():
    try:
        worker.run({"messages": [], "options": {"unsafe": True}})
    except ValueError as error:
        assert "unknown options" in str(error)
    else:
        raise AssertionError("worker accepted an unknown option")
