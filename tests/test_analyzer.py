from gliner25_context_compaction.analyzer import GlinerAnalyzer, _single_prediction
from gliner25_context_compaction.types import (
    AnalysisRequest,
    ToolInteraction,
    ToolResult,
    ToolUse,
)


class FakeModel:
    def __init__(self):
        self.calls = []

    def create_schema(self):
        return self

    def classification(self, *args, **kwargs):
        return self

    def entities(self, *args, **kwargs):
        return self

    def batch_extract_long(self, texts, schema, **kwargs):
        self.calls.append(("combined_long", kwargs))
        return [
            {
                "retention_action": {"label": "drop", "confidence": 0.9},
                "retention_reasons": [],
                "entities": {
                    "url": [
                        {
                            "text": "https://example.com",
                            "start": text.index("https://"),
                            "end": text.index("https://")
                            + len("https://example.com"),
                            "confidence": 0.99,
                        }
                    ]
                },
            }
            for text in texts
        ]


def test_long_inputs_use_explicit_long_context_apis():
    model = FakeModel()
    analyzer = GlinerAnalyzer(
        model, short_input_words=3, chunk_size=3, chunk_overlap=1
    )
    interaction = ToolInteraction(
        ToolUse("t1", "Read", {}),
        ToolResult("t1", "one two three four https://example.com"),
        1,
        2,
        False,
    )
    result = analyzer.analyze_many(
        (AnalysisRequest(interaction, goal="goal", nearby_text="context"),)
    )
    assert [call[0] for call in model.calls] == ["combined_long"]
    assert result[0].evidence[0].text == "https://example.com"


def test_confidence_less_prediction_fails_closed():
    assert _single_prediction("drop") == ("drop", 0.0)
