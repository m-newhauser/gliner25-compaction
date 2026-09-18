# Security Policy

## Supported versions

This project is experimental. Security fixes are provided on the latest release and the default branch.

## Reporting a vulnerability

Report vulnerabilities privately through [GitHub Security Advisories](https://github.com/m-newhauser/gliner25-compaction/security/advisories/new).

Do not include credentials, private source code, or real Claude Code transcripts in a public issue. If a report involves a suspected credential, revoke or rotate it before sharing any diagnostic material.

Please include:

- A concise description of the impact
- The affected version or commit
- Minimal reproduction steps using synthetic data
- Suggested remediation, if known

## Sensitive data

The optional capture path can store complete compaction requests and responses. Treat captures as sensitive local data. They are not required for normal plugin use and must not be committed.
