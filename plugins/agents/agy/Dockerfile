ARG BASE_IMAGE=sanity-gravity:_base-none
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- -d /usr/local/bin && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY rootfs/ /
