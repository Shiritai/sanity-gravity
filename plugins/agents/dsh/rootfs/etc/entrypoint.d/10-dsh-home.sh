#!/bin/bash

# Seed the harness state for the user created at boot. Hooks run after the
# entrypoint's recursive home chown, so anything created here must fix its
# own ownership.

# 1. The state dir: the wheel-packaged dsh requires DSH_HOME (the
#    /usr/local/bin/dsh wrapper defaults it to ~/.dsh) and maintains ESM
#    proxy packages under $DSH_HOME/profiles at runtime, so it must exist
#    and be user-writable before first use.
DSH_DIR="/home/$USER_NAME/.dsh"
if [ ! -d "$DSH_DIR" ]; then
    echo "Seeding DeepSeek Harness state dir ($DSH_DIR)..."
    mkdir -p "$DSH_DIR"
    chown "$HOST_UID":"$HOST_GID" "$DSH_DIR"
fi

# 2. Upstream packaging defect, re-verified against 0.1.5rc1: the wheel
#    ships the session-title-first-prompt-llm plugin but not its
#    @deepseek-ai/dsh-session-title-llm dependency, so every profile boot
#    (web and headless alike) dies in module resolution before doing any
#    work. Disabling that one loader entry unblocks both. Seed-once: the
#    file is the user's documented override layer. Drop this seeding when
#    the pin reaches a release that carries the dependency.
PATCH_FILE="$DSH_DIR/cordis.patch.yml"
if [ ! -f "$PATCH_FILE" ]; then
    echo "Seeding DeepSeek Harness patch layer ($PATCH_FILE)..."
    cat > "$PATCH_FILE" <<'PATCHEOF'
# Seeded by the dsh plugin (yours to edit; seeded only when absent).
# The 0.1.5rc1 runtime wheel is missing the dependency of its
# session-title-first-prompt-llm plugin, which breaks every profile
# boot; disabling the entry restores both the web and headless
# profiles. Delete this entry once the sandbox pins a fixed release.
- id: session-title-llm
  disabled: true
PATCHEOF
    chown "$HOST_UID":"$HOST_GID" "$PATCH_FILE"
fi
