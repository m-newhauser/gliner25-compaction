import io
import json

from gliner25_context_compaction.sidecar import serve
from gliner25_context_compaction.types import AnalysisResult, RetentionAction


class DropAnalyzer:
    def analyze_many(self, requests):
        return tuple(
            AnalysisResult(
                action=RetentionAction.DROP,
                confidence=0.95,
                reasons=("safely_rerunnable",),
                evidence=(),
            )
            for _ in requests
        )


def _request(method, payload=None):
    return {
        "v": 1,
        "type": "request",
        "id": f"{method}-1",
        "method": method,
        "payload": payload or {},
    }


def test_sidecar_analyzes_and_shuts_down():
    transcript = [
        {"role": "user", "text": "Inspect the parser."},
        {
            "role": "assistant",
            "tool_uses": [
                {
                    "id": "call-1",
                    "name": "read",
                    "input": {"filePath": "parser.py"},
                }
            ],
        },
        {
            "role": "assistant",
            "tool_results": [
                {
                    "tool_use_id": "call-1",
                    "text": "old parser contents",
                    "is_error": False,
                }
            ],
        },
        {"role": "user", "text": "Continue."},
    ]
    input_stream = io.StringIO(
        "\n".join(
            [
                json.dumps(
                    _request(
                        "analyze",
                        {
                            "messages": transcript,
                            "goal": "Inspect the parser",
                            "options": {"preserve_recent": 0},
                        },
                    )
                ),
                json.dumps(_request("shutdown")),
            ]
        )
        + "\n"
    )
    output_stream = io.StringIO()

    serve(
        input_stream,
        output_stream,
        DropAnalyzer(),
        checkpoint="test-small",
    )

    ready, analyzed, shutdown = [
        json.loads(line) for line in output_stream.getvalue().splitlines()
    ]
    assert ready == {"v": 1, "type": "ready", "checkpoint": "test-small"}
    assert analyzed["ok"] is True
    assert analyzed["result"]["decisions"][0]["action"] == "drop"
    assert analyzed["result"]["characters_after"] < analyzed["result"][
        "characters_before"
    ]
    assert shutdown["ok"] is True


def test_sidecar_rejects_unknown_options_without_stopping():
    input_stream = io.StringIO(
        json.dumps(
            _request(
                "analyze",
                {
                    "messages": [],
                    "goal": "test",
                    "options": {"surprise": True},
                },
            )
        )
        + "\n"
        + json.dumps(_request("shutdown"))
        + "\n"
    )
    output_stream = io.StringIO()

    serve(
        input_stream,
        output_stream,
        DropAnalyzer(),
        checkpoint="test-small",
    )

    _, rejected, shutdown = [
        json.loads(line) for line in output_stream.getvalue().splitlines()
    ]
    assert rejected["ok"] is False
    assert rejected["error"] == "unknown options: surprise"
    assert shutdown["ok"] is True
