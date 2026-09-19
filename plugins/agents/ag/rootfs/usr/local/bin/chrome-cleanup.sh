#!/bin/bash
# chrome-cleanup.sh
# Shared cleanup logic for Chrome & Antigravity Agent to ensure Snapshot stability.

# 1. Standard Locks (Prevent "Profile in use")
# Resolve Chrome config directory for the current user
CHROME_CONFIG="${HOME}/.config/google-chrome"
if [ ! -d "$CHROME_CONFIG" ]; then
    CHROME_CONFIG="${HOME}/.config/chromium"
fi
rm -f "$CHROME_CONFIG/SingletonLock"
rm -f "$CHROME_CONFIG/SingletonSocket"
rm -f "$CHROME_CONFIG/SingletonCookie"

# 2. Crashpad & Session State (Prevent "Restore Session" bubble / Hangs)
rm -rf "$CHROME_CONFIG/Crashpad" 
rm -rf "$CHROME_CONFIG/Crash Reports"
rm -f "$CHROME_CONFIG/Last Version"

# 3. Antigravity Agent Profile (Fixes Agent failure in Snapshots)
# We ONLY remove the lock file. Removing the whole profile causes CSRF/TLS issues.
AGENT_PROFILE="$HOME/.gemini/antigravity-browser-profile"
if [ -d "$AGENT_PROFILE" ]; then
    echo "$(date): [chrome-cleanup] Cleaning up locks in Agent Profile at $AGENT_PROFILE" >> /tmp/chrome-cleanup.log
    rm -f "$AGENT_PROFILE/SingletonLock"
    rm -f "$AGENT_PROFILE/SingletonSocket"
else
    echo "$(date): [chrome-cleanup] No Agent Profile found at $AGENT_PROFILE" >> /tmp/chrome-cleanup.log
fi

# 4. GPU/Shader Cache (Prevent Crashes on different HW)
rm -rf "$CHROME_CONFIG/ShaderCache"
rm -rf "$CHROME_CONFIG/GrShaderCache"
rm -rf "$CHROME_CONFIG/Default/GPUCache"

# 5. IPC & Shared Memory Debris in /tmp
find /tmp -name ".org.chromium.Chromium*" -user "${USER:-$(id -un)}" -delete 2>/dev/null || true

# 6. Antigravity Singleton Sockets (Prevent Stale Locks on Restart)
# Only clean these up at container/desktop startup to avoid interfering
# with running instances and Auth Redirect URIs.
#
# "Antigravity IDE" is the 2.x directory (Electron takes it from
# product.json's nameLong); "Antigravity" is 1.x's, still present in a
# home volume that predates the 2.x layer. The main socket carries the
# editor's version in its name, so it is matched by glob rather than
# spelled - the hard-coded 1.10-main.sock had stopped matching anything.
for ag_config in "$HOME/.config/Antigravity IDE" "$HOME/.config/Antigravity"; do
    [ -d "$ag_config" ] || continue
    rm -f "$ag_config"/*-main.sock
    rm -f "$ag_config/SingletonSocket"
    rm -f "$ag_config/SingletonCookie"
    rm -f "$ag_config/singleton-cookie"
done

echo "$(date): [chrome-cleanup] Cleanup completed for user ${USER:-$(id -un)}" >> /tmp/chrome-cleanup.log
