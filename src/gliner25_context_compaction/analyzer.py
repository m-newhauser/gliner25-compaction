from collections.abc import Mapping
from typing import Any, Protocol

from .schema import EVIDENCE_TYPES, REASON_LABELS, RETENTION_LABELS
from .types import EvidenceSpan, RetentionAction, ToolInteraction


class Analyzer(Protocol):
    def classify(
        self, interaction: ToolInteraction, *, goal: str, nearby_text: str
    ) -> tuple[RetentionAction, float, tuple[str, ...]]: ...

    def extract_evidence(self, text: str) -> tuple[EvidenceSpan, ...]: ...


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
    def __init__(self, model: Any):
        self.model = model

    @classmethod
    def from_pretrained(
        cls, checkpoint: str = "fastino/gliner2.5-base-v1"
    ) -> "GlinerAnalyzer":
        from gliner2 import AutoExtractor

        return cls(AutoExtractor.from_pretrained(checkpoint))

    def classify(
        self, interaction: ToolInteraction, *, goal: str, nearby_text: str
    ) -> tuple[RetentionAction, float, tuple[str, ...]]:
        schema = (
            self.model.create_schema()
            .classification("retention_action", RETENTION_LABELS)
            .classification(
                "retention_reasons",
                REASON_LABELS,
                multi_label=True,
                cls_threshold=0.35,
            )
        )
        output = self.model.extract(
            interaction_text(interaction, goal=goal, nearby_text=nearby_text),
            schema,
            include_confidence=True,
        )
        label, confidence = _single_prediction(output["retention_action"])
        return (
            RetentionAction(label),
            confidence,
            _multi_prediction(output.get("retention_reasons")),
        )

    def extract_evidence(self, text: str) -> tuple[EvidenceSpan, ...]:
        output = self.model.extract_entities(
            text,
            EVIDENCE_TYPES,
            include_spans=True,
            include_confidence=True,
            threshold=0.2,
            overlap_policy="allow",
        )
        spans = []
        for kind, items in output.get("entities", {}).items():
            for item in items:
                start, end = int(item["start"]), int(item["end"])
                value = str(item["text"])
                if text[start:end] != value:
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
        return tuple(sorted(spans, key=lambda span: (span.start, span.end)))
