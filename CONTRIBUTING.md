# Contributing to Sanity-Gravity

Thank you for your interest in contributing to Sanity-Gravity! We welcome community contributions significantly.

## How to Contribute

1.  **Fork the repository** and create your branch from `main`.
2.  **Make your changes**:
    *   If adding a new variant, create a new `Dockerfile.<variant>` in `sandbox/`.
    *   Update `sanity-cli` to handle the new variant if necessary (though it auto-detects most valid targets).
3.  **Test your changes**:
    *   Run `./sanity-cli build <variant>` to ensure it builds.
    *   Run `./sanity-cli run -v <variant>` to ensure it starts.
    *   Run existing tests: `python3 -m unittest discover tests`.
4.  **Submit a Pull Request**:
    *   Describe your changes clearly.
    *   Provide screenshots if you modified the UI/Desktop environment.

## Development Setup

*   **Requirements**: Docker, Python 3.7+.
*   **Structure**:
    *   `sandbox/variants/`: Variant definitions (Dockerfiles & scripts).
    *   `sandbox/rootfs/`: Shared configuration overlay.
    *   `sanity-cli`: Main CLI entry point.
    *   `tests/`: Integration tests.

## Code Style

*   **Python**: Follow PEP 8.
*   **Shell**: Use `#!/bin/bash` or `#!/bin/sh` and keep it POSIX compliant where possible.
