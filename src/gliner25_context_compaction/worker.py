import json
from pathlib import Path
import sys
from typing import Any

from .analyzer import GlinerAnalyzer
from .claude import compact_claude_messages, from_claude_messages
from .validation import deletion_manifest, validate_result

COMPACT_OPTIONS = {
    "goal",
    "preserve_recent",
    "minimum_confidence",
    "minimum_evidence_confidence",
    "context_characters",
}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    options = payload.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    unknown = set(options) - COMPACT_OPTIONS
    if unknown:
        raise ValueError(f"unknown options: {sorted(unknown)}")

    checkpoint = str(
        payload.get("checkpoint", "fastino/gliner2.5-base-v1")
    )
    analyzer = GlinerAnalyzer.from_pretrained(checkpoint)
    original = from_claude_messages(messages)
    result, compacted = compact_claude_messages(messages, analyzer, **options)
    validate_result(original, result)
    response = {"messages": compacted, "manifest": deletion_manifest(result)}
    capture_path = payload.get("capture_path")
    if capture_path is not None:
        if not isinstance(capture_path, str) or not capture_path:
            raise ValueError("capture_path must be a non-empty string")
        destination = Path(capture_path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                {"request": payload, "response": response},
                ensure_ascii=False,
                indent=2,
            )
        )
        temporary.replace(destination)
    return response


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(run(payload), ensure_ascii=False))
    except Exception as error:
        print(
            json.dumps(
                {"error": type(error).__name__, "message": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
