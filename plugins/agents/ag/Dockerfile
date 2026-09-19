ARG BASE_IMAGE=sanity-gravity:_base-xfce
FROM ${BASE_IMAGE}

# The browser comes from the desktop layer below (ag requires a display,
# so there is always one): Chrome/chromium, the --no-sandbox wrapper and
# the x-www-browser registration are installed once per desktop rather
# than once per agent. The IDE's own browser integration finds it as
# /usr/bin/google-chrome, and the arm64 path the IDE hard-codes
# (/opt/google/chrome/google-chrome) is linked at container start by
# rootfs/etc/entrypoint.d/10-ag-startup.sh.

# Install Antigravity IDE (Official) + apply sandbox wrapper in single layer
RUN mkdir -p /etc/apt/keyrings && \
    echo "xsBNBGCRt7MBCADkYJHHQQoL6tKrW/LbmfR9ljz7ib2aWno4JO3VKQvLwjyUMPpq/SXXMOnx8jXwgWizpPxQYDRJ0SQXS9ULJ1hXRL/OgMnZAYvYDeV2jBnKsAIEdiG/e1qm8P4W9qpWJc+hNq7FOT13RzGWRx57SdLWSXo0KeY38r9lvjjOmT/cuOcmjwlDT9XYf/RSO+yJ/AsyMdAr+ZbDeQUd9HYJiPdI04lGaGM02MjDMnx+monc+y54t+Z+ry1WtQdzoQt9dHlIPlV1tR+xV5DHHsejCZxu9TWzzSlL5wfBBeEz7R/OIzivGJpWQdJzd+2QDXSRg9q2XYWP5ZVtSgjVVJjNlb6ZABEBAAHNVEFydGlmYWN0IFJlZ2lzdHJ5IFJlcG9zaXRvcnkgU2lnbmVyIDxhcnRpZmFjdC1yZWdpc3RyeS1yZXBvc2l0b3J5LXNpZ25lckBnb29nbGUuY29tPsLAjgQTAQoAOBYhBDW6oLM+nrOW9ZyoOMC6XObcYxWjBQJgkbezAhsDBQsJCAcCBhUKCQgLAgQWAgMBAh4BAheAAAoJEMC6XObcYxWj+igIAMFh6DrAYMeq9sbZ1ZG6oAMrinUheGQbEqe76nIDQNsZnhDwZ2wWqgVC7DgOMqlhQmOmzm7M6Nzmq2dvPwq3xC2OeI9fQyzjT72deBTzLP7PJok9PJFOMdLfILSsUnmMsheQt4DUO0jYAX2KUuWOIXXJaZ319QyoRNBPYa5qz7qXS7wHLOY89IDqfHt6Aud8ER5zhyOyhytcYMeaGC1g1IKWmgewnhEq02FantMJGlmmFi2eA0EPD02GC3742QGqRxLwjWsm5/TpyuU24EYKRGCRm7QdVIo3ugFSetKrn0byOxWGBvtu4fH8XWvZkRT+u+yzH1s5yFYBqc2JTrrJvRU=" | base64 -d > /etc/apt/keyrings/antigravity-repo-key.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/antigravity-repo-key.gpg] https://us-central1-apt.pkg.dev/projects/antigravity-auto-updater-dev/ antigravity-debian main" | tee /etc/apt/sources.list.d/antigravity.list && \
    apt-get update && apt-get install -y --no-install-recommends antigravity && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY rootfs/ /

RUN dpkg-divert --add --rename --divert /usr/share/antigravity/antigravity-bin /usr/share/antigravity/antigravity && \
    printf '#!/bin/bash\n\n# 1. Environment Fix for Electron Children\nexport ELECTRON_DISABLE_SANDBOX=1\n\n# 2. Process Type Detection\nIS_GUI_CHILD=0\nfor arg in "$@"; do\n    if [[ "$arg" == --type=* ]]; then\n        IS_GUI_CHILD=1\n        break\n    fi\ndone\n\n# 3. Execution Logic\nif [ "$ELECTRON_RUN_AS_NODE" = "1" ] && [ "$IS_GUI_CHILD" = "0" ] && [[ "$*" == *cli.js* ]]; then\n    exec /usr/share/antigravity/antigravity-bin "$@"\nfi\n\nunset ELECTRON_RUN_AS_NODE\nexec /usr/share/antigravity/antigravity-bin --no-sandbox --disable-dev-shm-usage --disable-zygote --disable-namespace-sandbox "$@"\n' > /usr/share/antigravity/antigravity && \
    chmod +x /usr/share/antigravity/antigravity && \
    cp /usr/share/antigravity/antigravity /usr/share/antigravity/antigravity-original && \
    chmod +x /usr/share/antigravity/antigravity-original && \
    if [ -f /usr/share/applications/antigravity.desktop ]; then \
        sed -i 's|Exec=/usr/bin/antigravity|Exec=/usr/bin/antigravity --no-sandbox|g' /usr/share/applications/antigravity.desktop; \
    fi && \
    rm -rf /usr/share/doc/* /usr/share/info/* /usr/share/lintian/* /usr/share/man/*
