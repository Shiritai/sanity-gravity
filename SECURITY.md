# Security Policy

## Supported Versions

| Version | Supported          |
| :------ | :----------------- |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

**Sanity-Gravity is a Sandbox.** Its primary purpose is to **contain** untrusted execution.

If you find a way to **escape the container** (break out of the sandbox) or gain unauthorized access to the host machine through `sanity-gravity`'s default configuration, this is a critical vulnerability.

Please report it by:
1.  Opening a GitHub Issue with the label `security`.
2.  AND/OR emailing the maintainer directly.

### Scope

*   **In Scope**: Docker escape, Privilege escalation from container to host, Unintentional exposure of host files (beyond mapped workspace).
*   **Out of Scope**: Vulnerabilities within the guest OS (Ubuntu) that do not impact the host, or issues arising from user-configured insecure volume mounts.
