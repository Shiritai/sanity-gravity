#!/bin/bash
set -e

# Defaults (Relies on upstream)
HOST_UID=${HOST_UID}
HOST_GID=${HOST_GID}
USER_NAME=${HOST_USER}

echo "Starting Antigravity Sandbox..."
echo "Configuring user '$USER_NAME' with UID=$HOST_UID, GID=$HOST_GID..."

# Create Group
if ! getent group "$HOST_GID" >/dev/null; then
    # Check if group name exists with different GID, if so, we might have conflict
    # But usually groupadd handles it or we use force.
    groupadd -g "$HOST_GID" "$USER_NAME"
else
    GROUP_NAME=$(getent group "$HOST_GID" | cut -d: -f1)
    echo "Group with GID $HOST_GID already exists: $GROUP_NAME"
    # If group exists, we might need to use that group name or just add user to it
fi

# Create User
if ! id -u "$HOST_UID" >/dev/null 2>&1; then
    useradd -u "$HOST_UID" -g "$HOST_GID" -m -s /bin/zsh "$USER_NAME"
    echo "User '$USER_NAME' created."
    # Set default password
    echo "$USER_NAME:$HOST_PASSWORD" | chpasswd
else
    EXISTING_USER=$(getent passwd "$HOST_UID" | cut -d: -f1)
    echo "UID $HOST_UID already exists: $EXISTING_USER"
    if [ "$EXISTING_USER" != "$USER_NAME" ]; then
        # Rename user if needed, or just use existing. 
        # For simplicity, we assume we can use the existing user or we might have issues.
        # But for a sandbox, usually we are fine creating a new one if 1000 is free.
        # If 1000 is taken by 'ubuntu', we can modify it.
        if [ "$EXISTING_USER" == "ubuntu" ]; then
            # Fix: Check if target home exists (e.g. from volume mount)
            HOME_OPT="-m"
            if [ -d "/home/$USER_NAME" ]; then HOME_OPT=""; fi

            # Rename user 'ubuntu' -> $USER_NAME
            usermod -l "$USER_NAME" -d /home/"$USER_NAME" $HOME_OPT ubuntu
            
            # Fix: Set primary group to match HOST_GID (created/verified earlier)
            # We avoid renaming the 'ubuntu' group as it might conflict if we already created $USER_NAME group
            usermod -g "$HOST_GID" "$USER_NAME"
            
            echo "Renamed 'ubuntu' user to '$USER_NAME' and set GID=$HOST_GID."
        fi
    fi
fi

# Passwordless Sudo
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-developer

# Fix permissions for home directory
chown -R "$HOST_UID":"$HOST_GID" /home/"$USER_NAME"

# Fix permissions for workspace if it exists (volume mount)
if [ -d "/home/$USER_NAME/workspace" ]; then
    chown "$HOST_UID":"$HOST_GID" /home/"$USER_NAME/workspace"
fi

# Add to ssl-cert group if exists (for KasmVNC)
if getent group ssl-cert >/dev/null; then
    usermod -aG ssl-cert "$USER_NAME"
fi

# Setup Zsh (Optional: install oh-my-zsh if not present)
# We can do this in Dockerfile to save startup time, but here we ensure ownership.

# Fix Supervisor Configs (Dynamic User)
# We need to replace 'developer' with the actual USER_NAME in all conf files
if [ "$USER_NAME" != "developer" ]; then
    echo "Updating Supervisor configs for user '$USER_NAME'..."
    sed -i "s/user=developer/user=$USER_NAME/g" /etc/supervisor/conf.d/*.conf
    sed -i "s|directory=/home/developer|directory=/home/$USER_NAME|g" /etc/supervisor/conf.d/*.conf
    sed -i "s|HOME=\"/home/developer\"|HOME=\"/home/$USER_NAME\"|g" /etc/supervisor/conf.d/*.conf
    sed -i "s|USER=\"developer\"|USER=\"$USER_NAME\"|g" /etc/supervisor/conf.d/*.conf
    # Fix for any occurrences of user=developer in general (supervisord specific)
    sed -i "s/^user=developer/user=$USER_NAME/g" /etc/supervisor/conf.d/*.conf
    
    # Also fix Kasm startup script if present (it exports HOME/USER)
    if [ -f "/usr/local/bin/kasm-startup.sh" ]; then
        sed -i "s|export HOME=/home/developer|export HOME=/home/$USER_NAME|g" /usr/local/bin/kasm-startup.sh
        sed -i "s|export USER=developer|export USER=$USER_NAME|g" /usr/local/bin/kasm-startup.sh
        # kasm vncpasswd -u argument
        sed -i "s|-u developer|-u $USER_NAME|g" /usr/local/bin/kasm-startup.sh
    fi
fi

# Setup DBus & Machine ID (skip if dbus not installed, e.g. headless builds)
if command -v dbus-uuidgen >/dev/null 2>&1; then
    if [ ! -s /etc/machine-id ]; then
        echo "Generating /etc/machine-id..."
        dbus-uuidgen > /etc/machine-id
    fi

    mkdir -p /var/run/dbus
    if [ -f /var/run/dbus/pid ]; then
        rm /var/run/dbus/pid
    fi

    echo "Starting DBus System Daemon..."
    dbus-daemon --system --fork
else
    echo "DBus not installed, skipping (headless mode)."
fi

# Cleanup Stale Antigravity Runtime Locks (Safely)
# Instead of deleting entire directories (which breaks TLS/CSRF states),
# we only remove the actual Singleton locks that prevent startup.
echo "Cleaning up stale Antigravity/Chrome locks..."
find /home/"$USER_NAME"/.config/Antigravity -name "Singleton*" -delete 2>/dev/null || true
find /home/"$USER_NAME"/.gemini/antigravity-browser-profile -name "Singleton*" -delete 2>/dev/null || true

# Fix Chrome symlink for ARM64 (Chromium compatibility)
if [ ! -f "/opt/google/chrome/google-chrome" ]; then
    mkdir -p /opt/google/chrome
    ln -sf /usr/bin/google-chrome /opt/google/chrome/google-chrome
fi

# Regenerate SSH host keys if missing (removed from image for security)
if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
    echo "Generating SSH host keys..."
    ssh-keygen -A
fi

# Graceful shutdown handler: close Antigravity via Ctrl+Q before stopping supervisord.
# Triggered by Docker stop/host shutdown (SIGTERM to PID 1).
# Works with docker-compose stop_grace_period: 30s to allow full state persistence.
graceful_shutdown() {
    echo "[shutdown] Graceful shutdown initiated, closing Antigravity..."
    FOUND=0
    for wid in $(su - "$USER_NAME" -c 'DISPLAY=:1 xdotool search --class Antigravity' 2>/dev/null); do
        NAME=$(su - "$USER_NAME" -c "DISPLAY=:1 xdotool getwindowname $wid" 2>/dev/null)
        case "$NAME" in
            *" - Antigravity"*|"Antigravity"|"Launchpad")
                su - "$USER_NAME" -c "DISPLAY=:1 xdotool key --window $wid ctrl+q" 2>/dev/null
                FOUND=1
                ;;
        esac
    done

    if [ "$FOUND" = 1 ]; then
        for i in $(seq 1 20); do
            pgrep -f antigravity-bin > /dev/null 2>&1 || break
            sleep 1
        done
        echo "[shutdown] Antigravity exited after ${i}s"
    fi

    # Forward SIGTERM to supervisord
    kill -TERM "$SUPERVISOR_PID" 2>/dev/null
    wait "$SUPERVISOR_PID"
}

# Execute CMD (Supervisord) in background so we can trap signals
"$@" &
SUPERVISOR_PID=$!
trap graceful_shutdown SIGTERM SIGINT
wait "$SUPERVISOR_PID"
