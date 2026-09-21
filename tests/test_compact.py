from dataclasses import replace

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
    assert is_mutating("Bash", {"command": "rm generated.txt"})
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
