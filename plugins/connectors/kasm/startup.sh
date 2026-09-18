#!/bin/bash
set -e

# Ensure environment variables
export USER=${USER}
export HOME=${HOME}

# Generate SSL certificate if missing (moved from Dockerfile for per-container uniqueness)
if [ ! -f /etc/ssl/certs/ssl-cert-snakeoil.pem ]; then
    sudo make-ssl-cert generate-default-snakeoil --force-overwrite
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

# Claim the desktop choice so vncserver keeps the xstartup above. Left
# unclaimed it runs select-de.sh, which overwrites xstartup with its own
# and prompts on stdin - under supervisord that never returns.
touch $HOME/.vnc/.de-was-selected

echo "Starting KasmVNC on port 8444..."
# Start KasmVNC
exec /usr/bin/vncserver :1 \
    -depth 24 \
    -geometry 1920x1080 \
    -websocketPort 8444 \
    -httpd /usr/share/kasmvnc/www \
    -Log '*:stderr:10' \
    -fg
