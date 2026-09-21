import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any, TextIO

from .analyzer import Analyzer, GlinerAnalyzer
from .codec import decision_to_json, messages_from_json
from .compact import compact
from .validation import deletion_manifest, validate_result

PROTOCOL_VERSION = 1
DEFAULT_CHECKPOINT = "fastino/gliner2.5-small-v1"
MAX_LINE_BYTES = 32 * 1024 * 1024
OPTION_NAMES = frozenset(
    {
        "preserve_recent",
        "minimum_confidence",
        "minimum_evidence_confidence",
        "context_characters",
    }
)


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _write(output: TextIO, value: Mapping[str, Any]) -> None:
    output.write(json.dumps(value, separators=(",", ":")) + "\n")
    output.flush()


def _handle_analyze(
    request_id: str, payload: Mapping[str, Any], analyzer: Analyzer
) -> dict[str, Any]:
    messages = messages_from_json(payload.get("messages"))
    goal = str(payload.get("goal", "")).strip()
    if not goal:
        raise ValueError("goal must not be empty")
    options = dict(_object(payload.get("options", {}), "options"))
    unknown = sorted(set(options) - OPTION_NAMES)
    if unknown:
        raise ValueError(f"unknown options: {', '.join(unknown)}")
    result = compact(messages, analyzer, goal=goal, **options)
    validate_result(messages, result)
    manifest = deletion_manifest(result)
    return {
        "v": PROTOCOL_VERSION,
        "type": "response",
        "id": request_id,
        "ok": True,
        "result": {
            "decisions": [
                decision_to_json(decision) for decision in result.decisions
            ],
            "characters_before": result.original_characters,
            "characters_after": result.compacted_characters,
            "reduction": manifest["reduction"],
            "warnings": list(result.warnings),
            "context_characters": int(options.get("context_characters", 120)),
        },
    }


def serve(
    input_stream: TextIO,
    output_stream: TextIO,
    analyzer: Analyzer,
    *,
    checkpoint: str,
) -> None:
    _write(
        output_stream,
        {
            "v": PROTOCOL_VERSION,
            "type": "ready",
            "checkpoint": checkpoint,
        },
    )
    for raw_line in input_stream:
        if len(raw_line.encode("utf-8")) > MAX_LINE_BYTES:
            _write(
                output_stream,
                {
                    "v": PROTOCOL_VERSION,
                    "type": "response",
                    "id": "",
                    "ok": False,
                    "error": "request exceeds size limit",
                },
            )
            continue
        request_id = ""
        try:
            request = _object(json.loads(raw_line), "request")
            request_id = str(request.get("id", ""))
            if request.get("v") != PROTOCOL_VERSION:
                raise ValueError("unsupported protocol version")
            method = request.get("method")
            if method == "shutdown":
                _write(
                    output_stream,
                    {
                        "v": PROTOCOL_VERSION,
                        "type": "response",
                        "id": request_id,
                        "ok": True,
                        "result": {},
                    },
                )
                return
            if method != "analyze":
                raise ValueError(f"unsupported method: {method}")
            response = _handle_analyze(
                request_id,
                _object(request.get("payload"), "payload"),
                analyzer,
            )
        except Exception as error:
            response = {
                "v": PROTOCOL_VERSION,
                "type": "response",
                "id": request_id,
                "ok": False,
                "error": str(error),
            }
        _write(output_stream, response)


def main() -> None:
    parser = argparse.ArgumentParser(description="GLiNER2.5 pruning sidecar")
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    args = parser.parse_args()
    analyzer = GlinerAnalyzer.from_pretrained(args.checkpoint)
    print(
        f"loaded checkpoint {args.checkpoint}",
        file=sys.stderr,
        flush=True,
    )
    serve(sys.stdin, sys.stdout, analyzer, checkpoint=args.checkpoint)


if __name__ == "__main__":
    main()
