import type {
  PluginOptions,
  Register,
  SessionCompactInput,
  SessionCompactResult,
  SessionMessage,
} from 'claude-code';

type Manifest = {
  characters_before: number;
  characters_after: number;
  reduction: number;
  decisions: Array<{
    tool_use_id: string;
    action: string;
    confidence: number;
    reasons: string[];
    evidence: Array<{ kind: string; start: number; end: number; confidence: number }>;
  }>;
};

type WorkerResponse = {
  messages: SessionMessage[];
  manifest: Manifest;
};

type Config = {
  pythonPath?: string;
  checkpoint: string;
  timeoutMs: number;
  shadowMode: boolean;
  fallback: 'host' | 'unchanged';
  minReductionRatio: number;
  preserveRecent: number;
  minimumConfidence: number;
  minimumEvidenceConfidence: number;
  contextCharacters: number;
};

function numberOption(
  options: PluginOptions,
  key: string,
  fallback: number,
): number {
  const value = options[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function stringOption(options: PluginOptions, key: string): string | undefined {
  const value = options[key];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

export function resolveConfig(options: PluginOptions): Config {
  const fallback = stringOption(options, 'fallback');
  return {
    pythonPath: stringOption(options, 'pythonPath'),
    checkpoint: stringOption(options, 'checkpoint') ?? 'fastino/gliner2.5-base-v1',
    timeoutMs: numberOption(options, 'timeoutMs', 90_000),
    shadowMode: options.shadowMode !== false,
    fallback: fallback === 'unchanged' ? 'unchanged' : 'host',
    minReductionRatio: numberOption(options, 'minReductionRatio', 0.25),
    preserveRecent: numberOption(options, 'preserveRecentMessages', 6),
    minimumConfidence: numberOption(options, 'minimumConfidence', 0.7),
    minimumEvidenceConfidence: numberOption(
      options,
      'minimumEvidenceConfidence',
      0.5,
    ),
    contextCharacters: numberOption(options, 'contextCharacters', 120),
  };
}

function goalFrom(event: SessionCompactInput): string {
  if (event.instructions) return event.instructions;
  return event.messages
    .filter((message) => message.role === 'user' && message.text.trim())
    .slice(-3)
    .map((message) => message.text.slice(0, 500))
    .join('\n');
}

function parseWorkerResponse(stdout: string): WorkerResponse {
  let value: unknown;
  try {
    value = JSON.parse(stdout);
  } catch {
    throw new Error('worker returned malformed JSON');
  }
  if (
    value === null ||
    typeof value !== 'object' ||
    !Array.isArray((value as WorkerResponse).messages) ||
    typeof (value as WorkerResponse).manifest?.reduction !== 'number'
  ) {
    throw new Error('worker response is missing messages or manifest');
  }
  return value as WorkerResponse;
}

function manifestLines(manifest: Manifest): string[] {
  const lines = [
    `gliner25-compaction: ${Math.round(manifest.reduction * 100)}% reduction ` +
      `(${manifest.characters_before} → ${manifest.characters_after} chars)`,
  ];
  for (const decision of manifest.decisions) {
    lines.push(
      `gliner25-compaction: ${decision.tool_use_id} ${decision.action} ` +
        `confidence=${decision.confidence.toFixed(2)} ` +
        `reasons=${decision.reasons.join(',') || 'none'} ` +
        `spans=${decision.evidence.length}`,
    );
  }
  return lines;
}

async function fallback(
  config: Config,
  event: SessionCompactInput,
  next: (event: SessionCompactInput) => Promise<SessionCompactResult>,
  reason: string,
): Promise<SessionCompactResult> {
  if (config.fallback === 'unchanged') {
    return { skip: `GLiNER compaction skipped: ${reason}` };
  }
  return next(event);
}

export const register: Register = (on, options) => {
  const config = resolveConfig(options);
  on('session.compact', async ($, event, next) => {
    try {
      const configuredPath =
        config.pythonPath ?? (await $.env.get('GLINER_COMPACTION_PYTHON'));
      const pythonPath = configuredPath ?? 'python3';
      const capturePath = await $.env.get('GLINER_COMPACTION_CAPTURE_PATH');
      const payload = JSON.stringify({
        messages: event.messages,
        checkpoint: config.checkpoint,
        capture_path: capturePath,
        options: {
          goal: goalFrom(event),
          preserve_recent: config.preserveRecent,
          minimum_confidence: config.minimumConfidence,
          minimum_evidence_confidence: config.minimumEvidenceConfidence,
          context_characters: config.contextCharacters,
        },
      });
      const process = await $.process.run(
        [pythonPath, '-m', 'gliner25_context_compaction.worker'],
        { stdin: payload, timeoutMs: config.timeoutMs },
      );
      if (process.exitCode !== 0) {
        throw new Error(
          `worker failed (${process.exitCode}): ${process.stderr.slice(0, 500)}`,
        );
      }
      const response = parseWorkerResponse(process.stdout);
      for (const line of manifestLines(response.manifest)) $.ui.log(line);
      if (config.shadowMode) {
        return {
          skip: `GLiNER shadow mode: proposed ${Math.round(
            response.manifest.reduction * 100,
          )}% reduction`,
        };
      }
      const summary =
        `GLiNER compaction: ${Math.round(response.manifest.reduction * 100)}% fewer chars ` +
        `(${response.manifest.characters_before.toLocaleString()} → ` +
        `${response.manifest.characters_after.toLocaleString()})`;
      if (response.manifest.reduction < config.minReductionRatio) {
        $.ui.toast(`${summary} — below minimum, using host compaction`, {
          timeoutMs: 15_000,
        });
        return fallback(config, event, next, 'reduction below configured minimum');
      }
      $.ui.toast(
        `${summary} · kept ${response.messages.length}/${event.messages.length} messages`,
        { timeoutMs: 15_000 },
      );
      return { messages: response.messages };
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      $.ui.log(`gliner25-compaction fallback: ${reason}`);
      $.ui.toast(`GLiNER compaction failed, using fallback: ${reason.slice(0, 120)}`, {
        timeoutMs: 15_000,
      });
      return fallback(config, event, next, reason);
    }
  });
};
