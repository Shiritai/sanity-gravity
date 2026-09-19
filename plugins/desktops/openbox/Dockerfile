ARG BASE_IMAGE=sanity-gravity:_base
FROM ${BASE_IMAGE}

# Install Openbox WM and Desktop Utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    # --- Window Manager ---
    openbox \
    # openbox-xdg-autostart (shipped by the openbox package) requires PyXDG;
    # without it every session logs "requires PyXDG" and XDG autostart fails.
    python3-xdg \
    # --- Terminal ---
    # xterm is the minimal X11 terminal; it registers the
    # x-terminal-emulator alternative so the right-click menu and
    # Terminal=true .desktop entries (agent-starter, CLI agents) launch
    # reliably even though Openbox ships no panel/launcher of its own.
    xterm \
    # --- Shared X11, DBus & System Utilities ---
    dbus \
    dbus-x11 \
    x11-utils \
    x11-xserver-utils \
    x11-apps \
    xdotool \
    mesa-utils \
    # --- Fonts ---
    fonts-dejavu-core \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# The in-container browser: Chrome on amd64, chromium on arm64, wrapped
# so it starts without its own sandbox and registered as x-www-browser.
# Every desktop runs the same recipe out of the base image -- a plugin
# builds with its own directory as the build context, so the base layer's
# rootfs is the only place three Dockerfiles can share a file.
RUN /usr/local/lib/sanity-gravity/install-browser.sh

# Register standard desktop session launcher contract. Identify the session
# as Openbox/x11. openbox-session is the standard session wrapper; without
# the env vars the Openbox autostart/menu tooling would not recognize the
# session.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'exec env XDG_CURRENT_DESKTOP=Openbox DESKTOP_SESSION=openbox XDG_SESSION_DESKTOP=openbox XDG_SESSION_TYPE=x11 openbox-session' \
    > /usr/local/bin/desktop-session \
    && chmod +x /usr/local/bin/desktop-session

# Ship the right-click root menu (menu.xml), the agent-starter entry point
# and its .desktop launcher. The starter is the user-facing entry into the
# installed terminal agents: when combined with a CLI agent it lists the
# workspace projects and launches the agent in the chosen one.
COPY rootfs/ /
