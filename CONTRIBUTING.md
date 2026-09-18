# Contributing

Contributions are welcome while the project remains experimental.

## Before opening a pull request

1. Create a focused branch.
2. Use only synthetic transcript fixtures.
3. Never commit credentials, `.env` files, local auth stores, real source code, or real Claude Code transcripts.
4. Run the checks:

```sh
uv sync --frozen
uv run pytest
npm ci --ignore-scripts
npm run check
```

5. Explain the retention or safety behavior changed by the pull request.

## Design principles

- Fail closed when model output is uncertain or malformed.
- Preserve ordinary conversation text unchanged.
- Rebuild evidence only from validated original offsets.
- Preserve tool-call/result pairing.
- Treat unknown or compound shell commands as mutating.
- Keep dependencies and changes minimal.

## Security reports

Do not report vulnerabilities or sensitive transcripts in public issues. Follow [SECURITY.md](SECURITY.md).
