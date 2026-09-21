export type CanonicalToolUse = {
  id: string;
  name: string;
  input: Record<string, unknown>;
};

export type CanonicalToolResult = {
  tool_use_id: string;
  text: string;
  is_error: boolean;
};

export type CanonicalMessage = {
  role: string;
  text: string;
  tool_uses: CanonicalToolUse[];
  tool_results: CanonicalToolResult[];
};

export type EvidenceSpan = {
  start: number;
  end: number;
  text: string;
  kind: string;
  confidence: number;
};

export type RetentionDecision = {
  tool_use_id: string;
  action: "keep_full" | "keep_evidence" | "keep_call_only" | "drop";
  confidence: number;
  reasons: string[];
  evidence: EvidenceSpan[];
};

export type AnalyzeResult = {
  decisions: RetentionDecision[];
  characters_before: number;
  characters_after: number;
  reduction: number;
  warnings: string[];
  context_characters: number;
};

export type AnalyzePayload = {
  messages: CanonicalMessage[];
  goal: string;
  options?: {
    preserve_recent?: number;
    minimum_confidence?: number;
    minimum_evidence_confidence?: number;
    context_characters?: number;
  };
};
