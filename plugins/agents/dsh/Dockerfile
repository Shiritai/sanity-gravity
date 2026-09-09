# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# DeepSeek Harness (dsh) Agent Layer -- community tier.
#
# The base layer ships no Python, so the venv machinery is installed here.
# --no-deps is deliberate: the runtime wheel is one self-contained
# executable, and the sdk's pydantic dependency belongs in a Python SDK
# user's own environment, not in this CLI-only venv.
#
# No `dsh --version` at build time: like the other bundled-runtime
# agents (see oc), running the packaged binary is unreliable under qemu
# cross-builds; `test -x` keeps the build check architecture-safe.
COPY requirements.txt /opt/dsh/requirements.txt
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-venv && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    python3 -m venv /opt/dsh/venv && \
    /opt/dsh/venv/bin/pip install --no-cache-dir --no-deps --require-hashes \
        -r /opt/dsh/requirements.txt && \
    test -x /opt/dsh/venv/bin/dsh

# Reaches supervisord children (the GUI path) only; ssh logins get a fresh
# PAM environment, which is why the rootfs wrapper repeats this default.
ENV DSH_TELEMETRY_MODE=DISABLED

COPY rootfs/ /
RUN chmod 755 /usr/local/bin/dsh /etc/entrypoint.d/10-dsh-home.sh
