#!/bin/bash
set -euo pipefail

# Defaults (Relies on upstream)
HOST_UID=${HOST_UID}
HOST_GID=${HOST_GID}
export USER_NAME=${HOST_USER}

# Prevent WSL/Docker Desktop from materializing enormous host-side crash dumps
# when Chromium/Electron native code segfaults. Docker also sets this via
# compose ulimits; doing it here keeps the policy inherited by supervisord and
# every GUI/SSH child process even if the container is run without compose.
ulimit -S -c 0 2>/dev/null || true
ulimit -H -c 0 2>/dev/null || true

# Defence-in-depth: validate identity inputs before they reach sed/useradd/chown.
# Mirrors validate_username / validate_project_name in sanity-cli; a malformed
# USER_NAME would otherwise allow shell/sed injection via the supervisor-config
# rewrites below.
if ! [[ "$USER_NAME" =~ ^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$ ]]; then
    echo "ERROR: Invalid HOST_USER='$USER_NAME' (must be [a-zA-Z_][a-zA-Z0-9_-]{0,31})" >&2
    exit 1
fi
if ! [[ "$HOST_UID" =~ ^[0-9]+$ ]] || ! [[ "$HOST_GID" =~ ^[0-9]+$ ]]; then
    echo "ERROR: HOST_UID/HOST_GID must be numeric (got UID='$HOST_UID' GID='$HOST_GID')" >&2
    exit 1
fi
case "$HOST_PASSWORD" in
    *[$'\n\r':]*|"")
        echo "ERROR: invalid HOST_PASSWORD" >&2
        exit 1
        ;;
esac

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

# Set the login password on every boot, not only when the user is first
# created. A container started from a committed/snapshot image (e.g. after
# `sanity-cli upgrade`) already has the user, so the create-branch above is
# skipped; without this, HOST_PASSWORD would be silently ignored for SSH /
# system login and stay whatever was baked into the image. KASM is unaffected
# only because kasm/startup.sh re-runs vncpasswd every boot — this brings
# system auth in line with that.
printf '%s:%s\n' "$USER_NAME" "$HOST_PASSWORD" | chpasswd

# Passwordless Sudo
# NOTE: Password protects SSH & VNC login only.
# Passwordless sudo is intentional for developer sandbox use.
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-developer
chmod 0440 /etc/sudoers.d/90-developer

# Fix permissions for home directory
chown -R "$HOST_UID":"$HOST_GID" /home/"$USER_NAME"

# Fix permissions for workspace if it exists (volume mount)
if [ -d "/home/$USER_NAME/workspace" ]; then
    chown "$HOST_UID":"$HOST_GID" /home/"$USER_NAME/workspace"
fi

# Setup SSH Public Key Authentication if provided
if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
    echo "Setting up SSH public key authentication for '$USER_NAME'..."
    SSH_DIR="/home/$USER_NAME/.ssh"
    mkdir -p "$SSH_DIR"
    printf '%s\n' "$SSH_PUBLIC_KEY" > "$SSH_DIR/authorized_keys"
    chmod 700 "$SSH_DIR"
    chmod 600 "$SSH_DIR/authorized_keys"
    chown -R "$HOST_UID":"$HOST_GID" "$SSH_DIR"
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
fi

# Setup DBus & Machine ID (skip if dbus not installed, e.g. headless builds)
if command -v dbus-uuidgen >/dev/null 2>&1; then
    if [ ! -s /etc/machine-id ]; then
        echo "Generating /etc/machine-id..."
        dbus-uuidgen > /etc/machine-id
    fi

    mkdir -p /var/run/dbus
else
    echo "DBus not installed, skipping (headless mode)."
fi

# Regenerate SSH host keys if missing (removed from image for security)
if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
    echo "Generating SSH host keys..."
    ssh-keygen -A
fi

SUPERVISOR_PID=""
SHUTTING_DOWN=0

graceful_shutdown() {
    if [ "$SHUTTING_DOWN" -eq 1 ]; then
        return
    fi
    SHUTTING_DOWN=1

    echo "[shutdown] Graceful shutdown initiated..."

    if [ -d "/etc/shutdown.d" ]; then
        for f in /etc/shutdown.d/*.sh; do
            if [ -f "$f" ] && [ -x "$f" ]; then
                echo "Running shutdown hook $f..."
                timeout 15s "$f" || echo "[shutdown] Hook $f failed with $?"
            fi
        done
    fi

    if [ -n "$SUPERVISOR_PID" ] && kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
        kill -TERM "$SUPERVISOR_PID" 2>/dev/null || true
        wait "$SUPERVISOR_PID" 2>/dev/null || true
    fi

    exit 0
}

# Execute plugin entrypoint hooks
if [ -d "/etc/entrypoint.d" ]; then
    for f in /etc/entrypoint.d/*.sh; do
        if [ -x "$f" ]; then
            echo "Running entrypoint hook $f..."
            "$f"
        fi
    done
fi

# Execute CMD (Supervisord) in background so we can trap signals
trap graceful_shutdown SIGTERM SIGINT
"$@" &
SUPERVISOR_PID=$!
set +e
wait "$SUPERVISOR_PID"
SUPERVISOR_STATUS=$?
set -e
exit "$SUPERVISOR_STATUS"
