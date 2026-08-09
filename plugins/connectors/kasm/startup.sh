#!/bin/bash
set -e

# Ensure environment variables
export USER=${USER}
export HOME=${HOME}

# Cinnamon (a GNOME fork) requires a per-user runtime directory for its
# session bus and dconf; on a normal login systemd creates /run/user/$UID
# and exports XDG_RUNTIME_DIR, but in a container there is no systemd login.
# Without it the session dies right after authentication -> black desktop
# (see KasmVNC FAQ "Gnome Shows Black Screen").
RUNTIME_DIR="/run/user/$(id -u)"
if [ ! -d "$RUNTIME_DIR" ]; then
    sudo install -d -m 0700 -o "$(id -u)" -g "$(id -g)" "$RUNTIME_DIR"
fi
export XDG_RUNTIME_DIR="$RUNTIME_DIR"

# TLS certificate. The image bakes a localhost CA + server certificate at
# /etc/ssl/certs/ssl-cert-snakeoil.pem (see gen-localhost-certs.sh) at build
# time, so it is stable across container re-creations and a single CA import
# into the browser/OS trust store keeps working. Only the group permission
# needs (re)enforcing here in case the key lost it during an image commit:
# vncserver runs as a member of the ssl-cert group.
if [ -f /etc/ssl/private/ssl-cert-snakeoil.key ]; then
    sudo chown root:ssl-cert /etc/ssl/private/ssl-cert-snakeoil.key
    sudo chmod 640 /etc/ssl/private/ssl-cert-snakeoil.key
fi

# Cleanup locks
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

# ------------------------------------------------------------------
# Chrome Cleanup Strategy (For Snapshot Support)
# ------------------------------------------------------------------
# Source the shared cleanup script
if [ -f "/usr/local/bin/chrome-cleanup.sh" ]; then
    source /usr/local/bin/chrome-cleanup.sh
else
    echo "Warning: chrome-cleanup.sh not found!"
fi

# Setup VNC Directory
mkdir -p $HOME/.vnc

# Setup Password
# KasmVNC vncpasswd requires username and double entry
echo -e "${HOST_PASSWORD}\n${HOST_PASSWORD}\n" | vncpasswd -u $USER -w
# chmod 600 $HOME/.vnc/passwd

# Setup xstartup for Desktop Session. The desktop-session launcher is owned
# by the desktop plugin; wrapping it in dbus-launch guarantees a session bus
# for the DE (Cinnamon requires one) and exports DBUS_SESSION_BUS_ADDRESS to
# every app it spawns (nemo, terminals, ...).
#
# Before the session starts we (1) run vncconfig -nowin, which bridges the
# X11 CLIPBOARD selection to the VNC/RFB clipboard so the browser can copy
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

# Mark the desktop environment as already selected so KasmVNC skips its
# interactive DE picker (select-de.sh). That prompt reads from stdin and
# would hang forever under supervisord, so the HTTPS listener never starts.
touch $HOME/.vnc/.de-was-selected

echo "Starting KasmVNC on port 8444..."
# Start KasmVNC
exec /usr/bin/vncserver :1 \
    -depth 24 \
    -geometry 1920x1080 \
    -websocketPort 8444 \
    -httpd /usr/share/kasmvnc/www \
    -Log *:stderr:10 \
    -fg

