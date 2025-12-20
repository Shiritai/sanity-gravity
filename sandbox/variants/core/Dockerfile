FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_ALL=C.UTF-8

# Install Core Dependencies & XFCE4
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    sudo \
    vim \
    curl \
    wget \
    git \
    zsh \
    net-tools \
    locales \
    tzdata \
    ca-certificates \
    xfce4 \
    xfce4-goodies \
    xfce4-terminal \
    dbus-x11 \
    x11-utils \
    x11-xserver-utils \
    x11-apps \
    mesa-utils \
    pulseaudio \
    fonts-noto-cjk \
    openssh-server \
    gnupg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' && \
    apt-get update && apt-get install -y google-chrome-stable && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Add Global Chrome Wrapper (Robust Fix)
# We create a safe wrapper and redirect ALL common shortcuts to it
# This ensures xdg-open, menus, and CLI all use the sandboxed version
RUN echo '#!/bin/bash\nexec /opt/google/chrome/google-chrome --no-sandbox --disable-dev-shm-usage "$@"' > /usr/bin/google-chrome-safe && \
    chmod +x /usr/bin/google-chrome-safe && \
    ln -sf /usr/bin/google-chrome-safe /usr/bin/google-chrome && \
    ln -sf /usr/bin/google-chrome-safe /usr/bin/google-chrome-stable && \
    ln -sf /usr/bin/google-chrome-safe /usr/bin/x-www-browser && \
    sed -i 's|Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome|g' /usr/share/applications/google-chrome.desktop

# Install Antigravity IDE (Official)
# Using repository and key verified from host environment
RUN mkdir -p /etc/apt/keyrings && \
    echo "xsBNBGCRt7MBCADkYJHHQQoL6tKrW/LbmfR9ljz7ib2aWno4JO3VKQvLwjyUMPpq/SXXMOnx8jXwgWizpPxQYDRJ0SQXS9ULJ1hXRL/OgMnZAYvYDeV2jBnKsAIEdiG/e1qm8P4W9qpWJc+hNq7FOT13RzGWRx57SdLWSXo0KeY38r9lvjjOmT/cuOcmjwlDT9XYf/RSO+yJ/AsyMdAr+ZbDeQUd9HYJiPdI04lGaGM02MjDMnx+monc+y54t+Z+ry1WtQdzoQt9dHlIPlV1tR+xV5DHHsejCZxu9TWzzSlL5wfBBeEz7R/OIzivGJpWQdJzd+2QDXSRg9q2XYWP5ZVtSgjVVJjNlb6ZABEBAAHNVEFydGlmYWN0IFJlZ2lzdHJ5IFJlcG9zaXRvcnkgU2lnbmVyIDxhcnRpZmFjdC1yZWdpc3RyeS1yZXBvc2l0b3J5LXNpZ25lckBnb29nbGUuY29tPsLAjgQTAQoAOBYhBDW6oLM+nrOW9ZyoOMC6XObcYxWjBQJgkbezAhsDBQsJCAcCBhUKCQgLAgQWAgMBAh4BAheAAAoJEMC6XObcYxWj+igIAMFh6DrAYMeq9sbZ1ZG6oAMrinUheGQbEqe76nIDQNsZnhDwZ2wWqgVC7DgOMqlhQmOmzm7M6Nzmq2dvPwq3xC2OeI9fQyzjT72deBTzLP7PJok9PJFOMdLfILSsUnmMsheQt4DUO0jYAX2KUuWOIXXJaZ319QyoRNBPYa5qz7qXS7wHLOY89IDqfHt6Aud8ER5zhyOyhytcYMeaGC1g1IKWmgewnhEq02FantMJGlmmFi2eA0EPD02GC3742QGqRxLwjWsm5/TpyuU24EYKRGCRm7QdVIo3ugFSetKrn0byOxWGBvtu4fH8XWvZkRT+u+yzH1s5yFYBqc2JTrrJvRU=" | base64 -d > /etc/apt/keyrings/antigravity-repo-key.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/antigravity-repo-key.gpg] https://us-central1-apt.pkg.dev/projects/antigravity-auto-updater-dev/ antigravity-debian main" | tee /etc/apt/sources.list.d/antigravity.list && \
    apt-get update && apt-get install -y antigravity && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Fix Antigravity IDE sandbox issue (Binary Wrapper Method)
# We wrap the actual electron binary to ensure --no-sandbox is ALWAYS applied
# regardless of how it's invoked (CLI, GUI, or subprocess)
RUN mv /usr/share/antigravity/antigravity /usr/share/antigravity/antigravity-original && \
    echo '#!/bin/bash\nexec /usr/share/antigravity/antigravity-original --no-sandbox "$@"' > /usr/share/antigravity/antigravity && \
    chmod +x /usr/share/antigravity/antigravity && \
    if [ -f /usr/share/applications/antigravity.desktop ]; then \
        sed -i 's|Exec=/usr/bin/antigravity|Exec=/usr/bin/antigravity --no-sandbox|g' /usr/share/applications/antigravity.desktop; \
    fi


# Setup SSH
RUN mkdir /var/run/sshd && \
    echo 'PermitRootLogin no' >> /etc/ssh/sshd_config && \
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config

# Setup Locales
RUN locale-gen en_US.UTF-8

# Copy Rootfs (Configuration & Scripts)
COPY rootfs /

# Setup Entrypoint
RUN chmod +x /usr/local/bin/entrypoint.sh

# Expose SSH
EXPOSE 22

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
