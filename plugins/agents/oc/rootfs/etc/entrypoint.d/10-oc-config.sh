#!/bin/bash

# Persist the OpenCode autoupdate opt-out where SSH sessions can see it.
# The Dockerfile's ENV OPENCODE_DISABLE_AUTOUPDATE only reaches
# supervisord children (the GUI path); sshd builds a fresh PAM
# environment, so on the headless variants the env var never arrives.
# The documented config-file switch covers every entry path instead.
# Seed-once: the file belongs to the user and may be edited later
# (providers, theme, ...), so an existing config is left untouched.
CONFIG_DIR="/home/$USER_NAME/.config/opencode"
CONFIG_FILE="$CONFIG_DIR/opencode.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Seeding OpenCode user config (autoupdate disabled)..."
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_FILE" <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "autoupdate": false
}
EOF
    # Hooks run after the entrypoint's recursive home chown, so anything
    # created here must fix its own ownership.
    chown "$HOST_UID":"$HOST_GID" \
        "/home/$USER_NAME/.config" "$CONFIG_DIR" "$CONFIG_FILE"
fi
