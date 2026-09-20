#!/bin/bash
set -euo pipefail

# The IDE holds unsaved editor state, so it is asked to close itself
# (ctrl+q) before anything signals it. Two identities are needed for that.
# Measured on ag-xfce-kasm rather than assumed, because 2.x has more than
# one:
#
#   WM_CLASS   the editor window is "antigravity ide" / "Antigravity IDE"
#              (Electron derives it from product.json's nameLong), while a
#              hidden helper window is "antigravity-ide-bin" after the
#              wrapper renames the binary. xdotool matches --class
#              case-insensitively on a substring, so the shared prefix
#              finds both and also still finds 1.x's plain "Antigravity".
#   title      "<file> - <project> - Antigravity IDE" once a workspace is
#              open, "Antigravity IDE" before that. The " - Antigravity"
#              substring picks the editor and skips the helper window,
#              whose title is the binary name. 1.x's "Launchpad" window
#              has no counterpart in 2.x.
#
# Processes are matched by install directory rather than by binary name:
# the 1.x pattern leaned on the diverted binary being called
# antigravity-bin, which was a fact about the divert, not about the app.
AG_DIR=/usr/share/antigravity-ide

echo "[shutdown] Closing Antigravity gracefully..."
FOUND=0
while IFS= read -r wid; do
    [ -n "$wid" ] || continue
    NAME=$(runuser -u "$USER_NAME" -- env DISPLAY=:1 xdotool getwindowname "$wid" 2>/dev/null || true)
    case "$NAME" in
        *" - Antigravity"*|"Antigravity IDE")
            runuser -u "$USER_NAME" -- env DISPLAY=:1 xdotool key --window "$wid" ctrl+q 2>/dev/null || true
            FOUND=1
            ;;
    esac
done < <(runuser -u "$USER_NAME" -- env DISPLAY=:1 xdotool search --class antigravity 2>/dev/null || true)

if [ "$FOUND" -eq 1 ]; then
    for i in $(seq 1 12); do
        pgrep -u "$USER_NAME" -f "$AG_DIR" >/dev/null 2>&1 || {
            echo "[shutdown] Antigravity exited after ${i}s"
            exit 0
        }
        sleep 1
    done
    echo "[shutdown] Antigravity did not exit after GUI quit; sending SIGTERM..."
else
    echo "[shutdown] No Antigravity windows found; checking for background processes..."
fi

pkill -TERM -u "$USER_NAME" -f "$AG_DIR" 2>/dev/null || true

for i in $(seq 1 8); do
    pgrep -u "$USER_NAME" -f "$AG_DIR" >/dev/null 2>&1 || {
        echo "[shutdown] Antigravity processes stopped after SIGTERM in ${i}s"
        exit 0
    }
    sleep 1
done

echo "[shutdown] Antigravity still running; leaving final termination to supervisor/Docker"
