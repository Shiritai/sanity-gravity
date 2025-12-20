#!/bin/bash
set -e

# Defaults (Relies on upstream)
VNC_RESOLUTION=${VNC_RESOLUTION}
VNC_DEPTH=${VNC_DEPTH}
VNC_PW=${VNC_PW}
# Dynamic HOME
export HOME=${HOME}

# Cleanup locks
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

# Setup VNC Directory
mkdir -p $HOME/.vnc

# Setup Password
echo "$VNC_PW" | vncpasswd -f > $HOME/.vnc/passwd
chmod 600 $HOME/.vnc/passwd

# Setup xstartup for XFCE4
cat > $HOME/.vnc/xstartup <<EOF
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
chmod +x $HOME/.vnc/xstartup

echo "Starting TigerVNC on :1..."
# Start TigerVNC in foreground
exec /usr/bin/vncserver :1 \
    -geometry $VNC_RESOLUTION \
    -depth $VNC_DEPTH \
    -fg
