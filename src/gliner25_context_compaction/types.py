from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RetentionAction(StrEnum):
    KEEP_FULL = "keep_full"
    KEEP_EVIDENCE = "keep_evidence"
    KEEP_CALL_ONLY = "keep_call_only"
    DROP = "drop"


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    text: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    role: str
    text: str = ""
    tool_uses: tuple[ToolUse, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class ToolInteraction:
    tool_use: ToolUse
    result: ToolResult
    call_message_index: int
    result_message_index: int
    pinned: bool


@dataclass(frozen=True)
class EvidenceSpan:
    start: int
    end: int
    text: str
    kind: str
    confidence: float
    status: str | None = None


@dataclass(frozen=True)
class RetentionDecision:
    tool_use_id: str
    action: RetentionAction
    confidence: float
    reasons: tuple[str, ...] = ()
    evidence: tuple[EvidenceSpan, ...] = ()


@dataclass(frozen=True)
class CompactionResult:
    messages: tuple[Message, ...]
    decisions: tuple[RetentionDecision, ...]
    original_characters: int
    compacted_characters: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
