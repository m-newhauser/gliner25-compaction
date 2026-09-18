# GLiNER2.5 Context Compaction for Claude Code

Experimental, local-first context compaction for Claude Code. [GLiNER2.5](https://huggingface.co/collections/fastino/gliner25-models) chooses a retention action for completed tool interactions and extracts exact source spans when the full result is unnecessary.

This project does not generate a prose summary. User and assistant text remains unchanged, retained evidence is copied from original character offsets, and mutating tool interactions are preserved in full.

## How it works

For each completed, eligible tool interaction, the local model receives:

- The current goal
- Nearby conversation text
- The tool name and input
- The original tool result

It returns one action:

- `keep_full`: preserve the complete call and result
- `keep_evidence`: preserve exact excerpts from the result
- `keep_call_only`: preserve the call and replace its result with a rerun notice
- `drop`: remove the paired call and result

Deterministic safeguards override uncertain predictions, protect validated diagnostic spans, preserve recent messages and mutations, validate exact offsets, and reject orphaned tool results.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Claude Code 2.1.274 or newer
- Claude Code function hooks enabled

The default checkpoint is `fastino/gliner2.5-base-v1`. Model weights are downloaded from Hugging Face during setup and are not stored in this repository. The checkpoint model card declares Apache-2.0 licensing.

## Install

```sh
git clone https://github.com/m-newhauser/gliner25-compaction.git
cd gliner25-compaction
uv sync --frozen
uv run python scripts/download_model.py
```

Start Claude Code with the plugin:

```sh
export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1
export GLINER_COMPACTION_PYTHON="$PWD/.venv/bin/python"
claude --plugin-dir .
```

The public default is `shadowMode: true`. Shadow mode runs local analysis and logs the proposed reduction without replacing session history. Review its output before explicitly setting `shadowMode` to `false` in your Claude Code plugin configuration.

## Safety behavior

- Low-confidence retention predictions fail closed to `keep_full`.
- Missing or invalid evidence fails closed to `keep_full`.
- Mutating tools and unknown shell commands are retained in full.
- Shell commands containing control operators, pipelines, substitutions, or redirections are treated as mutating.
- Compacted messages are installed only after transcript and span validation.
- Worker failures delegate to Claude Code's compactor by default.
- The worker has a 90-second host deadline.

## Privacy

Inference runs in a local Python worker. The initial model download contacts Hugging Face, but transcript analysis does not require a remote inference API.

Do not commit real Claude Code transcripts. If `GLINER_COMPACTION_CAPTURE_PATH` is set, the worker writes the complete compaction request and response to that local path. Those files may contain source code, prompts, tool output, credentials, personal paths, and other sensitive data. Capture output is opt-in and ignored by this repository.

This repository intentionally contains no real session captures, model weights, or demo transcript data.

## Configuration

The plugin exposes these options:

- `checkpoint`: local Hugging Face checkpoint
- `timeoutMs`: worker deadline, default `90000`
- `shadowMode`: analyze without replacing history, default `true`
- `fallback`: `host` or `unchanged`
- `minReductionRatio`: minimum reduction before installing output, default `0.25`
- `preserveRecentMessages`: newest messages excluded from compaction, default `6`
- `minimumConfidence`: retention threshold, default `0.7`
- `minimumEvidenceConfidence`: evidence threshold, default `0.5`
- `contextCharacters`: original context retained around each evidence span, default `120`

## Development

```sh
uv sync --frozen
uv run pytest
npm ci --ignore-scripts
npm run check
```

## Limitations

- This is an experimental prototype, not a general-purpose summarizer.
- Reduction metrics are measured in characters, not model tokens.
- Retention quality depends on the checkpoint and transcript domain.
- The conservative shell policy may retain commands that are actually read-only.
- Only completed tool-call/result pairs are candidates for compaction.
- Domain-specific tuning and broad production evaluation remain future work.

## Security

Please report vulnerabilities privately through [GitHub Security Advisories](https://github.com/m-newhauser/gliner25-compaction/security/advisories/new). Do not open a public issue containing credentials or private transcripts.

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
