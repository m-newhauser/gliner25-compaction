from gliner25_context_compaction import (
    EvidenceSpan,
    Message,
    RetentionAction,
    ToolResult,
    ToolUse,
    compact,
)
from gliner25_context_compaction.compact import is_mutating


class FakeAnalyzer:
    def classify(self, interaction, *, goal, nearby_text):
        if interaction.tool_use.id == "read-old":
            return RetentionAction.DROP, 0.95, ("superseded",)
        return RetentionAction.KEEP_EVIDENCE, 0.9, ("unresolved_failure",)

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
            tool_uses=(ToolUse("test", "Test", {"target": "parser"}),),
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


def test_protected_error_evidence_overrides_uncertain_retention():
    class UncertainAnalyzer(FakeAnalyzer):
        def classify(self, interaction, *, goal, nearby_text):
            return RetentionAction.DROP, 0.51, ()

    result_text = f"{'noise ' * 100}expected 2, received 3{' tail' * 100}"
    messages = (
        Message(role="user", text="Fix the test"),
        Message(
            role="assistant",
            tool_uses=(ToolUse("test", "Test", {"target": "parser"}),),
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
    assert result.decisions[0].action is RetentionAction.KEEP_EVIDENCE
    assert "protected_evidence" in result.decisions[0].reasons
    kept = next(
        item
        for message in result.messages
        for item in message.tool_results
        if item.tool_use_id == "test"
    )
    assert "expected 2, received 3" in kept.text
    assert len(kept.text) < len(result_text)


def test_shell_policy_only_pins_commands_not_known_to_be_read_only():
    assert not is_mutating("Bash", {"command": "npm test"})
    assert not is_mutating("Shell", {"command": "git status --short"})
    assert not is_mutating("Shell", {"command": "rg ParseError src"})
    assert is_mutating("Bash", {"command": "rm generated.txt"})
    assert is_mutating("Bash", {"command": "git status && rm generated.txt"})
    assert is_mutating("Shell", {"command": "pytest > results.txt"})
    assert is_mutating("Shell", {"command": "git statusmalicious"})
    assert is_mutating("Edit", {"file_path": "src/a.py"})
