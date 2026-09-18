from collections.abc import Mapping, Sequence
import re
from typing import Any, Protocol

from .schema import EVIDENCE_TYPES, REASON_LABELS, RETENTION_LABELS
from .types import (
    AnalysisRequest,
    AnalysisResult,
    EvidenceSpan,
    RetentionAction,
    ToolInteraction,
)


class Analyzer(Protocol):
    def analyze_many(
        self, requests: Sequence[AnalysisRequest]
    ) -> tuple[AnalysisResult, ...]: ...


def interaction_text(
    interaction: ToolInteraction, *, goal: str, nearby_text: str
) -> str:
    return (
        f"CURRENT GOAL:\n{goal}\n\n"
        f"NEARBY CONVERSATION:\n{nearby_text}\n\n"
        f"TOOL: {interaction.tool_use.name}\n"
        f"INPUT: {interaction.tool_use.input}\n"
        f"RESULT:\n{interaction.result.text}"
    )


def _single_prediction(value: Any) -> tuple[str, float]:
    if isinstance(value, str):
        return value, 1.0
    if isinstance(value, Mapping):
        return str(value.get("label", "")), float(value.get("confidence", 0.0))
    raise ValueError(f"Unexpected single-label response: {value!r}")


def _multi_prediction(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        str(item.get("label", "")) if isinstance(item, Mapping) else str(item)
        for item in value
    )


class GlinerAnalyzer:
    def __init__(
        self,
        model: Any,
        *,
        short_input_words: int = 3_000,
        chunk_size: int = 384,
        chunk_overlap: int = 64,
    ):
        if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk overlap must be non-negative and smaller than size")
        self.model = model
        self.short_input_words = short_input_words
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.schema = (
            self.model.create_schema()
            .entities(EVIDENCE_TYPES)
            .classification("retention_action", RETENTION_LABELS)
            .classification(
                "retention_reasons",
                REASON_LABELS,
                multi_label=True,
                cls_threshold=0.35,
            )
        )

    @classmethod
    def from_pretrained(
        cls, checkpoint: str = "fastino/gliner2.5-base-v1"
    ) -> "GlinerAnalyzer":
        from gliner2 import AutoExtractor

        return cls(AutoExtractor.from_pretrained(checkpoint))

    def _is_long(self, text: str) -> bool:
        word_count = len(re.findall(r"\S+", text))
        if word_count <= self.short_input_words:
            return False
        step = self.chunk_size - self.chunk_overlap
        starts = range(0, word_count, step)
        covered_until = 0
        for start in starts:
            if start > covered_until:
                raise ValueError(f"long-input coverage gap before word {start}")
            covered_until = max(covered_until, min(word_count, start + self.chunk_size))
            if covered_until == word_count:
                break
        if covered_until != word_count:
            raise ValueError(
                f"long-input coverage incomplete: {covered_until}/{word_count} words"
            )
        return True

    def _parse(
        self, output: Mapping[str, Any], text: str, result_text: str
    ) -> AnalysisResult:
        label, confidence = _single_prediction(output["retention_action"])
        result_start = len(text) - len(result_text)
        spans = []
        entities = output.get("entities", {})
        if not isinstance(entities, Mapping):
            raise ValueError("combined model response has invalid entities")
        for kind, items in entities.items():
            for item in items:
                absolute_start, absolute_end = int(item["start"]), int(item["end"])
                if absolute_start < result_start or absolute_end > len(text):
                    continue
                start, end = absolute_start - result_start, absolute_end - result_start
                value = str(item["text"])
                if result_text[start:end] != value:
                    raise ValueError(f"Span mismatch for {kind} at [{start}:{end}]")
                spans.append(
                    EvidenceSpan(
                        start=start,
                        end=end,
                        text=value,
                        kind=kind,
                        confidence=float(item.get("confidence", 0.0)),
                    )
                )
        return AnalysisResult(
            action=RetentionAction(label),
            confidence=confidence,
            reasons=_multi_prediction(output.get("retention_reasons")),
            evidence=tuple(sorted(spans, key=lambda span: (span.start, span.end))),
        )

    def analyze_many(
        self, requests: Sequence[AnalysisRequest]
    ) -> tuple[AnalysisResult, ...]:
        texts = [
            interaction_text(
                request.interaction,
                goal=request.goal,
                nearby_text=request.nearby_text,
            )
            for request in requests
        ]
        parsed: list[AnalysisResult | None] = [None] * len(requests)
        groups = {
            False: [index for index, text in enumerate(texts) if not self._is_long(text)],
            True: [index for index, text in enumerate(texts) if self._is_long(text)],
        }
        for is_long, indices in groups.items():
            if not indices:
                continue
            selected = [texts[index] for index in indices]
            options = {
                "threshold": 0.2,
                "format_results": True,
                "include_confidence": True,
                "include_spans": True,
                "overlap_policy": "allow",
            }
            if is_long:
                outputs = self.model.batch_extract_long(
                    selected,
                    self.schema,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                    **options,
                )
            else:
                outputs = self.model.batch_extract(selected, self.schema, **options)
            if len(outputs) != len(indices):
                raise ValueError("batch model response length mismatch")
            for index, output in zip(indices, outputs):
                parsed[index] = self._parse(
                    output,
                    texts[index],
                    requests[index].interaction.result.text,
                )
        if any(item is None for item in parsed):
            raise ValueError("batch model response omitted an interaction")
        return tuple(item for item in parsed if item is not None)
