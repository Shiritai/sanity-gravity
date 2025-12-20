#!/bin/bash
set -e

# Ensure environment variables
# Ensure environment variables
export USER=${USER}
export HOME=${HOME}

# Cleanup locks
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

# Setup VNC Directory
mkdir -p $HOME/.vnc

# Setup Password
# KasmVNC vncpasswd requires username and double entry
echo -e "${HOST_PASSWORD}\n${HOST_PASSWORD}\n" | vncpasswd -u $USER -w
# chmod 600 $HOME/.vnc/passwd

# Setup xstartup for XFCE4
cat > $HOME/.vnc/xstartup <<EOF
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
chmod +x $HOME/.vnc/xstartup

echo "Starting KasmVNC on port 8444..."
# Start KasmVNC
# -select-de xfce might be needed if xstartup isn't used, but xstartup is standard.
exec /usr/bin/vncserver :1 \
    -depth 24 \
    -geometry 1920x1080 \
    -websocketPort 8444 \
    -httpd /usr/share/kasmvnc/www \
    -select-de xfce \
    -fg
