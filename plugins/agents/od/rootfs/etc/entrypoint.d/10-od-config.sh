#!/bin/bash

# Opt the OpenCode Desktop app out of self-update wherever it can see it.
# The app is root-owned under /opt/OpenCode, so an auto-update could never
# succeed for the sandbox user and would only add startup noise. The
# documented config-file switch (~/.config/opencode/opencode.json with
# "autoupdate": false) covers every entry path, including GUI launches that
# never inherit an ENV. Seed-once: the file belongs to the user and may be
# edited later (providers, theme, ...), so an existing config is untouched.
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
