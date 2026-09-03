#!/bin/bash
set -e

# Defaults (Relies on upstream)
VNC_RESOLUTION=${VNC_RESOLUTION}
VNC_DEPTH=${VNC_DEPTH}
VNC_PW=${VNC_PW}
# Dynamic identity (parity with kasm/startup.sh; keeps USER exported for
# sourced helpers like chrome-cleanup.sh)
export USER=${USER}
export HOME=${HOME}

# Cinnamon (a GNOME fork) requires a per-user runtime directory for its
# session bus and dconf; on a normal login systemd creates /run/user/$UID
# and exports XDG_RUNTIME_DIR, but in a container there is no systemd login.
# Without it the session dies right after authentication -> black desktop.
RUNTIME_DIR="/run/user/$(id -u)"
if [ ! -d "$RUNTIME_DIR" ]; then
    sudo install -d -m 0700 -o "$(id -u)" -g "$(id -g)" "$RUNTIME_DIR"
fi
export XDG_RUNTIME_DIR="$RUNTIME_DIR"

# Cleanup locks
# Cleanup locks
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

# ------------------------------------------------------------------
# Chrome Cleanup Strategy (For Snapshot Support)
# ------------------------------------------------------------------
export CHROME_CONFIG="$HOME/.config/google-chrome"
if [ -f /usr/local/bin/chrome-cleanup.sh ]; then
    source /usr/local/bin/chrome-cleanup.sh
else
    echo "Warning: chrome-cleanup.sh not found!"
fi

# Setup VNC Directory
mkdir -p $HOME/.vnc

# Setup Password
echo "$VNC_PW" | vncpasswd -f > $HOME/.vnc/passwd
chmod 600 $HOME/.vnc/passwd

# Setup xstartup for Desktop Session. The desktop-session launcher is owned
# by the desktop plugin; wrapping it in dbus-launch guarantees a session bus
# for the DE (Cinnamon requires one) and exports DBUS_SESSION_BUS_ADDRESS to
# every app it spawns.
#
# Before the session starts we (1) run vncconfig -nowin, which bridges the
# X11 CLIPBOARD selection to the VNC/RFB clipboard so the client can copy
# and paste in both directions (required by TigerVNC; KasmVNC ships the same
# tool), and (2) merge the desktop's X resources (xterm font + clipboard
# selection, shipped by the openbox plugin) into the server. Both are guarded
# so connectors work on desktops that ship neither.
cat > $HOME/.vnc/xstartup <<EOF
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
if command -v vncconfig >/dev/null 2>&1; then
    vncconfig -nowin &
fi
if command -v xrdb >/dev/null 2>&1 && [ -d /etc/X11/Xresources ]; then
    for f in /etc/X11/Xresources/*; do
        [ -f "\$f" ] && xrdb -merge "\$f"
    done
fi
if [ -x /usr/local/bin/desktop-session ]; then
    exec dbus-launch --exit-with-session /usr/local/bin/desktop-session
else
    exec dbus-launch --exit-with-session startxfce4
fi
EOF
chmod +x $HOME/.vnc/xstartup

echo "Starting TigerVNC on :1..."
# Start TigerVNC in foreground
exec /usr/bin/vncserver :1 \
    -geometry $VNC_RESOLUTION \
    -depth $VNC_DEPTH \
    -fg
