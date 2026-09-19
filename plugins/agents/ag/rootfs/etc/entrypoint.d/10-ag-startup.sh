#!/bin/bash

# Cleanup Stale Antigravity Runtime Locks (Safely)
# Instead of deleting entire directories (which breaks TLS/CSRF states),
# we only remove the actual Singleton locks that prevent startup.
#
# Two config directories, not one: Electron derives userData from
# product.json's nameLong, so 1.x wrote ~/.config/Antigravity and the
# standalone 2.x IDE writes ~/.config/Antigravity IDE. The home is a
# persistent volume, so a sandbox upgraded in place has both.
echo "Cleaning up stale Antigravity/Chrome locks..."
find "/home/$USER_NAME/.config/Antigravity IDE" -name "Singleton*" -delete 2>/dev/null || true
find "/home/$USER_NAME/.config/Antigravity" -maxdepth 1 -name "Singleton*" -delete 2>/dev/null || true
find "/home/$USER_NAME/.gemini/antigravity-browser-profile" -name "Singleton*" -delete 2>/dev/null || true

# Fix Chrome symlink for ARM64 (Chromium compatibility)
if [ ! -f "/opt/google/chrome/google-chrome" ]; then
    mkdir -p /opt/google/chrome
    ln -sf /usr/bin/google-chrome /opt/google/chrome/google-chrome
fi

# Keep the IDE from replacing itself. product.json has already lost its
# update URL at build time, which the user cannot undo; this is the
# documented switch on top of it (upstream's releases page names
# "Update: Mode" -> none as the way to stay on a version). Seed-once: the
# file is the user's from here on.
AG_USER_DIR="/home/$USER_NAME/.config/Antigravity IDE/User"
AG_SETTINGS="$AG_USER_DIR/settings.json"
if [ ! -f "$AG_SETTINGS" ]; then
    echo "Seeding Antigravity IDE user settings (updates disabled)..."
    mkdir -p "$AG_USER_DIR"
    cat > "$AG_SETTINGS" <<'EOF'
{
  "update.mode": "none",
  "extensions.autoUpdate": false,
  "extensions.autoCheckUpdates": false
}
EOF
    # Hooks run after the entrypoint's recursive home chown, so anything
    # created here has to fix its own ownership.
    chown -R "$HOST_UID":"$HOST_GID" "/home/$USER_NAME/.config" || true
fi

# Sign-in returns over an antigravity-ide:// deep link, so xdg-open has to
# resolve that scheme to the IDE's handler or the last step of the login
# lands nowhere. The image-level default is in /etc/xdg/mimeapps.list
# (written by gravity-cli); this covers the per-user list, which reads
# first - including a home volume created before the 2.x layer existed.
# Only when the user has recorded no choice of their own.
AG_SCHEME=x-scheme-handler/antigravity-ide
AG_HANDLER=antigravity-ide-url-handler.desktop
if command -v xdg-mime >/dev/null 2>&1; then
    current=$(runuser -u "$USER_NAME" -- env HOME="/home/$USER_NAME" \
        xdg-mime query default "$AG_SCHEME" 2>/dev/null || true)
    if [ -z "$current" ]; then
        echo "Registering the antigravity-ide:// URL handler for '$USER_NAME'..."
        runuser -u "$USER_NAME" -- env HOME="/home/$USER_NAME" \
            xdg-mime default "$AG_HANDLER" "$AG_SCHEME" 2>/dev/null || true
        chown -R "$HOST_UID":"$HOST_GID" \
            "/home/$USER_NAME/.config" "/home/$USER_NAME/.local" 2>/dev/null || true
    fi
fi
