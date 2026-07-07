#!/bin/sh
set -e

Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
export DISPLAY=:99

for _ in $(seq 1 20); do
    if xdpyinfo >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

exec uv run python handler.py
