#!/usr/bin/env bash
# install.sh - symlink this directory to ~/.claude/skills/refine (global skill, spec §4.1).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.claude/skills/refine"
if [ -e "$DEST" ] && [ ! -L "$DEST" ]; then echo "refusing: $DEST exists and is not a symlink"; exit 1; fi
ln -sfn "$HERE" "$DEST"
echo "installed: $DEST -> $HERE"
