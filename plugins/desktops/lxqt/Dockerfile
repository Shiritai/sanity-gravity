ARG BASE_IMAGE=sanity-gravity:_base
FROM ${BASE_IMAGE}

# Install LXQt Desktop and Core Utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    # --- LXQt Core & Session ---
    # lxqt-core pulls in lxqt-session (startlxqt), lxqt-panel, pcmanfm-qt,
    # lxqt-runner, lxqt-qtplugin, lxqt-policykit, lxqt-notificationd,
    # lxqt-config, lxqt-globalkeys, lxqt-system-theme, qterminal, etc.
    # LXQt ships no window manager of its own (it is WM-agnostic); xfwm4
    # is the standard WM for LXQt on both Ubuntu and Debian, so lxqt-session
    # finds exactly one known WM at start and selects it without prompting.
    lxqt-core \
    xfwm4 \
    # --- Core Utilities (replaces XFCE-Tools) ---
    featherpad \
    lximage-qt \
    qps \
    qlipper \
    lxqt-archiver \
    # --- Shared X11, DBus & System Utilities ---
    dbus \
    dbus-x11 \
    x11-utils \
    x11-xserver-utils \
    x11-apps \
    xdotool \
    mesa-utils \
    fonts-noto-cjk \
    && apt-get autoremove -y && \
    rm -rf /usr/share/doc/* /usr/share/info/* /usr/share/lintian/* /usr/share/man/* \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Register standard desktop session launcher contract. Identify the session
# as LXQt/x11 so LXQt components behave correctly: pcmanfm-qt handles the
# desktop and lxqt components recognize the DE.
RUN echo '#!/bin/sh\nexec env XDG_CURRENT_DESKTOP=LXQt DESKTOP_SESSION=lxqt XDG_SESSION_DESKTOP=lxqt XDG_SESSION_TYPE=x11 startlxqt' > /usr/local/bin/desktop-session \
    && chmod +x /usr/local/bin/desktop-session
