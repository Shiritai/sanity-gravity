# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# SSH is already installed and configured in the base image.
# This layer explicitly marks the intent to expose SSH as the primary connector and can host further SSH-specific hardening.

EXPOSE 22
