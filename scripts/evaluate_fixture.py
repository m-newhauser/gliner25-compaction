import argparse
import json
import time
from pathlib import Path

from gliner25_context_compaction.analyzer import GlinerAnalyzer
from gliner25_context_compaction.codec import messages_from_json
from gliner25_context_compaction.compact import compact
from gliner25_context_compaction.validation import deletion_manifest, validate_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a sanitized pruning fixture")
    parser.add_argument(
        "fixture",
        type=Path,
        nargs="?",
        default=Path("fixtures/opencode/tool-heavy-session.json"),
    )
    parser.add_argument(
        "--checkpoint",
        default="fastino/gliner2.5-small-v1",
    )
    parser.add_argument("--preserve-recent", type=int, default=2)
    parser.add_argument("--minimum-confidence", type=float, default=0.7)
    parser.add_argument("--context-characters", type=int, default=120)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text())
    messages = messages_from_json(fixture["messages"])
    analyzer = GlinerAnalyzer.from_pretrained(args.checkpoint)
    started = time.perf_counter()
    result = compact(
        messages,
        analyzer,
        goal=str(fixture["goal"]),
        preserve_recent=args.preserve_recent,
        minimum_confidence=args.minimum_confidence,
        context_characters=args.context_characters,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1_000, 1)
    validate_result(messages, result)
    report = deletion_manifest(result)
    report["elapsed_ms"] = elapsed_ms
    report["checkpoint"] = args.checkpoint
    report["fixture"] = str(args.fixture)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
