#!/usr/bin/env bash
# probe.sh [worktree]  - 4-second check that this codex honours --output-schema and --json.
# Must be run with a trusted worktree (see ~/.codex/config.toml [projects]); default: cwd.
set -uo pipefail
WT="${1:-$PWD}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
codex exec -s read-only -C "$WT" -c 'model_reasoning_effort="low"' \
  --json --output-schema "$HERE/review.schema.json" -o "$TMP/out.json" \
  - <<'PROMPT' > "$TMP/events.jsonl" 2>&1
This is a format probe. Do not read any files. Reply with verdict "ready", zero findings, one prior entry {id "R1-F1", result "resolved", note "probe"}, verified ["probe"], not_verified [].
PROMPT
rc=$?
ok=1
[ "$rc" -eq 0 ] || { echo "probe: codex exit $rc"; ok=0; }
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["verdict"]=="ready" and d["prior"][0]["id"]=="R1-F1", d' "$TMP/out.json" 2>/dev/null || { echo "probe: output did not conform"; ok=0; }
grep -q '"type":"thread.started"' "$TMP/events.jsonl" || { echo "probe: no thread.started event"; ok=0; }
grep -q '"type":"turn.completed"' "$TMP/events.jsonl" || { echo "probe: no turn.completed event"; ok=0; }
if [ "$ok" -eq 1 ]; then echo "probe ok: $(grep -o '"usage":{[^}]*}' "$TMP/events.jsonl")"; rm -rf "$TMP"; exit 0; fi
echo "probe FAILED; artifacts in $TMP"; tail -c 800 "$TMP/events.jsonl"; exit 1
