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

# The desktop plugin owns the launcher, so a new desktop needs no change
# here; startxfce4 stays as the fallback for a desktop that predates the
# contract. vncconfig bridges the X11 CLIPBOARD selection to the RFB
# clipboard, and is guarded so the session still starts without it.
cat > $HOME/.vnc/xstartup <<EOF
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
if command -v vncconfig >/dev/null 2>&1; then
    vncconfig -nowin &
fi
if [ -x /usr/local/bin/desktop-session ]; then
    exec /usr/local/bin/desktop-session
else
    exec startxfce4
fi
EOF
chmod +x $HOME/.vnc/xstartup

echo "Starting TigerVNC on :1..."
# Start TigerVNC in foreground
exec /usr/bin/vncserver :1 \
    -geometry $VNC_RESOLUTION \
    -depth $VNC_DEPTH \
    -fg
