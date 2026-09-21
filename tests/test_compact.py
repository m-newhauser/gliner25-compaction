from dataclasses import replace

from gliner25_context_compaction import (
    EvidenceSpan,
    Message,
    RetentionAction,
    ToolResult,
    ToolUse,
    compact,
)
from gliner25_context_compaction.compact import (
    is_mutating,
    strict_diagnostic_block,
)


class FakeAnalyzer:
    def classify(self, interaction, *, goal, nearby_text):
        if interaction.tool_use.id == "read-old":
            return RetentionAction.DROP, 0.95, ("superseded",)
        return RetentionAction.KEEP_EVIDENCE, 0.9, ("safely_rerunnable",)

    def extract_evidence(self, text):
        value = "expected 2, received 3"
        if value not in text:
            return ()
        start = text.index(value)
        return (
            EvidenceSpan(
                start=start,
                end=start + len(value),
                text=value,
                kind="failing_test_or_error_location",
                confidence=0.92,
            ),
        )


def diagnostic_fixture(
    *,
    marker: str = "FAIL tests/parser.test.mjs",
    expected_line: str = "Expected quantity: 1200",
    received_line: str = "Received quantity: 120",
    location: str = "at tests/parser.test.mjs:6:10",
    expected_confidence: float = 0.99,
    received_confidence: float = 0.98,
):
    block = "\n".join((marker, expected_line, received_line, location))
    noise = "noise cache=hit route=/line-items\n" * 140
    text = f"{noise}{block}\ntrailer"
    expected_text = "1200"
    received_text = "120"
    expected_start = text.index(expected_text)
    received_start = text.index(received_text, expected_start + len(expected_text))
    spans = (
        EvidenceSpan(
            start=expected_start,
            end=expected_start + len(expected_text),
            text=expected_text,
            kind="expected_value",
            confidence=expected_confidence,
        ),
        EvidenceSpan(
            start=received_start,
            end=received_start + len(received_text),
            text=received_text,
            kind="received_value",
            confidence=received_confidence,
        ),
    )
    return text, block, spans


def test_strict_diagnostic_block_overrides_only_one_complete_qualified_block():
    class DiagnosticAnalyzer:
        def classify(self, interaction, *, goal, nearby_text):
            return (
                RetentionAction.DROP,
                0.65,
                ("current_dependency", "unresolved_failure"),
            )

        def extract_evidence(self, text):
            return diagnostic_fixture()[2]

    text, block, _ = diagnostic_fixture()
    messages = (
        Message(role="user", text="Fix the quantity failure"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("failure", "read", {"filePath": "failure.log"}),),
            tool_results=(ToolResult("failure", text),),
        ),
        Message(role="user", text="Continue"),
    )

    result = compact(
        messages,
        DiagnosticAnalyzer(),
        goal="Fix the quantity failure",
        preserve_recent=0,
        context_characters=0,
    )

    decision = result.decisions[0]
    assert decision.action is RetentionAction.KEEP_EVIDENCE
    assert decision.evidence == (
        EvidenceSpan(
            start=text.index(block),
            end=text.index(block) + len(block),
            text=block,
            kind="failing_test_or_error_location",
            confidence=0.98,
        ),
    )
    assert "strict_diagnostic_block" in decision.reasons
    kept = next(
        item
        for message in result.messages
        for item in message.tool_results
        if item.tool_use_id == "failure"
    )
    assert kept.text == block


def test_strict_diagnostic_block_rejects_raw_keep_full():
    text, _, spans = diagnostic_fixture()
    assert strict_diagnostic_block(text, RetentionAction.KEEP_FULL, spans) is None


def test_strict_diagnostic_block_accepts_location_inside_received_span():
    text, block, spans = diagnostic_fixture()
    location_end = text.index("tests/parser.test.mjs:6:10") + len(
        "tests/parser.test.mjs:6:10"
    )
    received = spans[1]
    combined = replace(
        received,
        end=location_end,
        text=text[received.start:location_end],
    )

    diagnostic = strict_diagnostic_block(
        text,
        RetentionAction.DROP,
        (spans[0], combined),
    )

    assert diagnostic is not None
    assert diagnostic.text == block


def test_strict_diagnostic_block_rejects_missing_independent_marker():
    text, _, spans = diagnostic_fixture(marker="Test tests/parser.test.mjs")
    assert strict_diagnostic_block(text, RetentionAction.DROP, spans) is None


def test_strict_diagnostic_block_rejects_missing_file_location():
    text, _, spans = diagnostic_fixture(location="at parser test")
    assert strict_diagnostic_block(text, RetentionAction.DROP, spans) is None


def test_strict_diagnostic_block_rejects_reversed_pair():
    noise = "noise cache=hit route=/line-items\n" * 140
    block = "\n".join(
        (
            "FAIL tests/parser.test.mjs",
            "Received quantity: 120",
            "Expected quantity: 1200",
            "at tests/parser.test.mjs:6:10",
        )
    )
    text = f"{noise}{block}\ntrailer"
    expected_start = text.index("1200")
    received_start = text.index("120")
    spans = (
        EvidenceSpan(
            expected_start,
            expected_start + 4,
            "1200",
            "expected_value",
            0.99,
        ),
        EvidenceSpan(
            received_start,
            received_start + 3,
            "120",
            "received_value",
            0.98,
        ),
    )
    assert strict_diagnostic_block(text, RetentionAction.DROP, spans) is None


def test_strict_diagnostic_block_rejects_pair_farther_than_500_characters():
    text, _, spans = diagnostic_fixture(
        received_line=f"{'x' * 501}\nReceived quantity: 120",
    )
    received = spans[1]
    assert received.start - spans[0].end > 500
    assert strict_diagnostic_block(text, RetentionAction.DROP, spans) is None


def test_strict_diagnostic_block_rejects_either_low_confidence_span():
    for expected_confidence, received_confidence in ((0.79, 0.98), (0.99, 0.79)):
        text, _, spans = diagnostic_fixture(
            expected_confidence=expected_confidence,
            received_confidence=received_confidence,
        )
        assert strict_diagnostic_block(text, RetentionAction.DROP, spans) is None


def test_strict_diagnostic_block_rejects_output_at_or_under_4000_characters():
    text, _, spans = diagnostic_fixture()
    shortened = text[-4_000:]
    shift = len(text) - len(shortened)
    shifted = tuple(
        replace(span, start=span.start - shift, end=span.end - shift) for span in spans
    )
    assert len(shortened) == 4_000
    assert strict_diagnostic_block(shortened, RetentionAction.DROP, shifted) is None


def test_strict_diagnostic_block_rejects_multiple_or_cross_paired_failures():
    text, block, spans = diagnostic_fixture()
    second = block.replace("1200", "2200").replace("120", "220", 1)
    text = text + "\n" + second
    second_expected = text.rindex("2200")
    second_received = text.rindex("220")
    all_spans = (
        *spans,
        EvidenceSpan(
            second_expected,
            second_expected + 4,
            "2200",
            "expected_value",
            0.99,
        ),
        EvidenceSpan(
            second_received,
            second_received + 3,
            "220",
            "received_value",
            0.99,
        ),
    )
    assert strict_diagnostic_block(text, RetentionAction.DROP, all_spans) is None


def test_strict_diagnostic_block_rejects_unrelated_log_shapes():
    text, _, spans = diagnostic_fixture(
        location=(
            "2026-09-18T10:22:00Z route=/cache/hit:12 "
            "status=200 cache=hit"
        ),
    )
    assert strict_diagnostic_block(text, RetentionAction.DROP, spans) is None


def test_compaction_drops_stale_call_and_preserves_exact_evidence():
    large_failure = f"{'noise ' * 100}expected 2, received 3{' tail' * 100}"
    messages = (
        Message(role="user", text="Fix the failing parser test."),
        Message(
            role="assistant",
            tool_uses=(ToolUse("read-old", "Read", {"file_path": "old.py"}),),
        ),
        Message(
            role="user",
            tool_results=(ToolResult("read-old", "obsolete contents"),),
        ),
        Message(
            role="assistant",
            tool_uses=(ToolUse("test", "read", {"target": "parser"}),),
        ),
        Message(
            role="user",
            tool_results=(ToolResult("test", large_failure, is_error=True),),
        ),
        Message(role="assistant", text="Investigating the assertion."),
        Message(role="user", text="Continue."),
    )

    result = compact(
        messages,
        FakeAnalyzer(),
        goal="Fix the failing parser test.",
        preserve_recent=1,
        context_characters=10,
    )

    assert [decision.action for decision in result.decisions] == [
        RetentionAction.DROP,
        RetentionAction.KEEP_EVIDENCE,
    ]
    assert all(
        tool.id != "read-old"
        for message in result.messages
        for tool in message.tool_uses
    )
    kept_result = next(
        tool_result
        for message in result.messages
        for tool_result in message.tool_results
        if tool_result.tool_use_id == "test"
    )
    assert "expected 2, received 3" in kept_result.text
    assert len(kept_result.text) < len(large_failure)


def test_low_confidence_prediction_fails_closed():
    class UncertainAnalyzer(FakeAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.DROP, 0.51, ()

    messages = (
        Message(role="user", text="Start"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("x", "Read", {"file_path": "x.py"}),),
        ),
        Message(role="user", tool_results=(ToolResult("x", "important"),)),
        Message(role="user", text="Continue"),
    )
    result = compact(
        messages,
        UncertainAnalyzer(),
        goal="Continue",
        preserve_recent=0,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL
    assert result.messages == messages


def test_uncertain_retention_keeps_full_even_with_protected_evidence():
    class UncertainAnalyzer(FakeAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.DROP, 0.51, ()

    result_text = f"{'noise ' * 100}expected 2, received 3{' tail' * 100}"
    messages = (
        Message(role="user", text="Fix the test"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("test", "read", {"target": "parser"}),),
        ),
        Message(
            role="user",
            tool_results=(ToolResult("test", result_text, is_error=True),),
        ),
        Message(role="user", text="Continue"),
    )
    result = compact(
        messages,
        UncertainAnalyzer(),
        goal="Fix the test",
        preserve_recent=0,
        context_characters=10,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL
    assert "uncertain" in result.decisions[0].reasons
    kept = next(
        item
        for message in result.messages
        for item in message.tool_results
        if item.tool_use_id == "test"
    )
    assert "expected 2, received 3" in kept.text
    assert kept.text == result_text


def test_keep_full_is_never_downgraded_by_extracted_evidence():
    class KeepAnalyzer(FakeAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.KEEP_FULL, 0.95, ("current_dependency",)

    result_text = "expected 2, received 3"
    messages = (
        Message(role="user", text="Fix the test"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("read", "read", {"filePath": "failure.log"}),),
            tool_results=(ToolResult("read", result_text, is_error=True),),
        ),
        Message(role="user", text="Continue"),
    )
    result = compact(
        messages,
        KeepAnalyzer(),
        goal="Fix the test",
        preserve_recent=0,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL
    assert result.messages == messages


def test_shell_policy_only_pins_commands_not_known_to_be_read_only():
    assert is_mutating("Bash", {"command": "npm test"})
    assert not is_mutating("Shell", {"command": "git status --short"})
    assert is_mutating("Shell", {"command": "rg ParseError src"})
    assert is_mutating("Bash", {"command": "rm generated.txt"})
    assert is_mutating("Bash", {"command": "git status && rm generated.txt"})
    assert is_mutating("Shell", {"command": "pytest > results.txt"})
    assert is_mutating("Shell", {"command": "git statusmalicious"})
    assert is_mutating("Edit", {"file_path": "src/a.py"})
    assert is_mutating("edit", {"filePath": "src/a.py"})
    assert is_mutating("question", {"questions": []})
    assert is_mutating("custom_mcp_tool", {})
    assert is_mutating("bash", {"command": "git status && rm important.txt"})
    assert is_mutating("bash", {"command": "git diff --output=patch.txt"})
    assert is_mutating("bash", {"command": "rg --pre 'rm -f important.txt' token"})


def test_destructive_action_with_current_dependency_fails_closed():
    class ContradictoryAnalyzer(FakeAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.DROP, 0.9, ("current_dependency",)

    messages = (
        Message(role="user", text="Start"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("x", "read", {"filePath": "x.py"}),),
            tool_results=(ToolResult("x", "important"),),
        ),
        Message(role="user", text="Continue"),
    )
    result = compact(
        messages,
        ContradictoryAnalyzer(),
        goal="Continue",
        preserve_recent=0,
        minimum_confidence=0.35,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL
    assert "contradictory_destructive_decision" in result.decisions[0].reasons

    class ContradictoryEvidenceAnalyzer(ContradictoryAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.KEEP_EVIDENCE, 0.9, ("current_dependency",)

        def extract_evidence(self, text):
            return (
                EvidenceSpan(
                    start=0,
                    end=len(text),
                    text=text,
                    kind="requirement_subject",
                    confidence=0.99,
                ),
            )

    result = compact(
        messages,
        ContradictoryEvidenceAnalyzer(),
        goal="Continue",
        preserve_recent=0,
        minimum_confidence=0.35,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL


def test_error_without_protected_evidence_fails_closed():
    class DropAnalyzer(FakeAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.DROP, 0.9, ("superseded",)

        def extract_evidence(self, text):
            return ()

    messages = (
        Message(role="user", text="Start"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("x", "read", {"filePath": "missing.py"}),),
            tool_results=(ToolResult("x", "process failed", is_error=True),),
        ),
        Message(role="user", text="Continue"),
    )
    result = compact(
        messages,
        DropAnalyzer(),
        goal="Continue",
        preserve_recent=0,
        minimum_confidence=0.35,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL
    assert "unresolved_error_without_evidence" in result.decisions[0].reasons


def test_identical_reads_are_superseded_only_without_an_intervening_mutation():
    class KeepAnalyzer(FakeAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.KEEP_FULL, 0.99, ("current_dependency",)

        def extract_evidence(self, text):
            return ()

    repeated = (
        Message(role="user", text="Inspect"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("read-1", "read", {"filePath": "x.py"}),),
            tool_results=(ToolResult("read-1", "same"),),
        ),
        Message(
            role="assistant",
            tool_uses=(ToolUse("read-2", "read", {"filePath": "x.py"}),),
            tool_results=(ToolResult("read-2", "same"),),
        ),
        Message(role="user", text="Continue"),
    )
    result = compact(
        repeated,
        KeepAnalyzer(),
        goal="Inspect",
        preserve_recent=0,
    )
    assert result.decisions[0].action is RetentionAction.DROP
    assert result.decisions[0].reasons == ("deterministic_superseded_read",)

    changed_output = (
        repeated[0],
        replace(
            repeated[1],
            tool_results=(ToolResult("read-1", "old"),),
        ),
        repeated[2],
        repeated[3],
    )
    result = compact(
        changed_output,
        KeepAnalyzer(),
        goal="Inspect",
        preserve_recent=0,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL

    with_mutation = (
        repeated[0],
        repeated[1],
        Message(
            role="assistant",
            tool_uses=(ToolUse("edit", "edit", {"filePath": "x.py"}),),
            tool_results=(ToolResult("edit", "updated"),),
        ),
        repeated[2],
        repeated[3],
    )
    result = compact(
        with_mutation,
        KeepAnalyzer(),
        goal="Inspect",
        preserve_recent=0,
    )
    assert result.decisions[0].action is RetentionAction.KEEP_FULL
