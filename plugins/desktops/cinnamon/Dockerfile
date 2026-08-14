ARG BASE_IMAGE=sanity-gravity:_base
FROM ${BASE_IMAGE}

# Install Cinnamon Desktop and Core Utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    # --- Cinnamon Core & Session ---
    cinnamon-core \
    # --- Core Utilities (replaces XFCE-Tools) ---
    gnome-terminal \
    file-roller \
    # --- Shared X11, DBus & System Utilities ---
    dbus \
    dbus-x11 \
    x11-utils \
    x11-xserver-utils \
    xdotool \
    libgl1-mesa-dri \
    && apt-get autoremove -y && \
    rm -rf /usr/share/doc/* /usr/share/info/* /usr/share/lintian/* /usr/share/man/* \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Register standard desktop session launcher contract. Identify the session
# as Cinnamon/x11 so Cinnamon components behave correctly: muffin avoids the
# "Unsupported session type" warning, nemo-desktop/polkit recognize the DE
# (otherwise nemo logs "session is not cinnamon" and skips desktop handling).
RUN echo '#!/bin/sh\nexec env XDG_CURRENT_DESKTOP=Cinnamon DESKTOP_SESSION=cinnamon XDG_SESSION_DESKTOP=cinnamon XDG_SESSION_TYPE=x11 cinnamon-session' > /usr/local/bin/desktop-session \
    && chmod +x /usr/local/bin/desktop-session

