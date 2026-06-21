#!/bin/bash
set -euo pipefail

echo "[shutdown] Closing Antigravity gracefully..."
FOUND=0
while IFS= read -r wid; do
    [ -n "$wid" ] || continue
    NAME=$(runuser -u "$USER_NAME" -- env DISPLAY=:1 xdotool getwindowname "$wid" 2>/dev/null || true)
    case "$NAME" in
        *" - Antigravity"*|"Antigravity"|"Launchpad")
            runuser -u "$USER_NAME" -- env DISPLAY=:1 xdotool key --window "$wid" ctrl+q 2>/dev/null || true
            FOUND=1
            ;;
    esac
done < <(runuser -u "$USER_NAME" -- env DISPLAY=:1 xdotool search --class Antigravity 2>/dev/null || true)

if [ "$FOUND" -eq 1 ]; then
    for i in $(seq 1 12); do
        pgrep -u "$USER_NAME" -f 'antigravity.*(bin|Antigravity)' >/dev/null 2>&1 || {
            echo "[shutdown] Antigravity exited after ${i}s"
            exit 0
        }
        sleep 1
    done
    echo "[shutdown] Antigravity did not exit after GUI quit; sending SIGTERM..."
else
    echo "[shutdown] No Antigravity windows found; checking for background processes..."
fi

pkill -TERM -u "$USER_NAME" -f 'antigravity.*(bin|Antigravity)' 2>/dev/null || true

for i in $(seq 1 8); do
    pgrep -u "$USER_NAME" -f 'antigravity.*(bin|Antigravity)' >/dev/null 2>&1 || {
        echo "[shutdown] Antigravity processes stopped after SIGTERM in ${i}s"
        exit 0
    }
    sleep 1
done

echo "[shutdown] Antigravity still running; leaving final termination to supervisor/Docker"
