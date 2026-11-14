#!/usr/bin/env bash
# run-round.sh --run-dir D --round N --kind full|delta|confirm [--effort E] [--no-assemble] [--dry-run] [--repair "<problem>"]
# Spec §7.2 step 2 (and the repair call of step 3). Success is judged only from typed signals.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA="$HERE/../review.schema.json"
RUN=""; N=""; KIND=""; EFFORT=""; ASSEMBLE=1; DRY=0; REPAIR=""
while [ $# -gt 0 ]; do case "$1" in
  --run-dir) RUN="$2"; shift 2;; --round) N="$2"; shift 2;; --kind) KIND="$2"; shift 2;; --effort) EFFORT="$2"; shift 2;;
  --no-assemble) ASSEMBLE=0; shift;; --dry-run) DRY=1; shift;; --repair) REPAIR="$2"; shift 2;;
  *) echo "unknown arg $1"; exit 1;; esac; done
[ -n "$RUN" ] && [ -n "$N" ] && [ -n "$KIND" ] || { echo "usage: run-round.sh --run-dir D --round N --kind full|delta|confirm"; exit 1; }
kv() { grep "^$2=" "$1" | head -1 | cut -d= -f2-; }
WT="$(kv "$RUN/run.meta" worktree)"
if [ -z "$EFFORT" ]; then EFFORT="$(kv "$RUN/run.meta" effort)"; [ "$KIND" = delta ] && EFFORT="$(python3 -c "import sys; sys.path.insert(0,'$HERE'); import refine_lib; print(refine_lib.delta_effort('$EFFORT'))")"; fi
PROMPT="$RUN/.prompt-round-$N.md"; OUT="$RUN/round-$N.json"; EV="$RUN/.codex-round-$N.jsonl"; META="$RUN/round-$N.meta"

if [ "$DRY" -eq 1 ]; then exec python3 "$HERE/assemble-prompt.py" --run-dir "$RUN" --round "$N" --kind "$KIND" --stdout; fi

next_attempt() { local k=1; while ls "$RUN/.round-$N.attempt$k."* >/dev/null 2>&1; do k=$((k+1)); done; echo "$k"; }

preserve() {  # bundle the attempt under one number (§7.2 step 2): prompt copied, output/events/meta moved
  local k; k="$(next_attempt)"; local moved=0
  [ -s "$PROMPT" ] && cp "$PROMPT" "$RUN/.round-$N.attempt$k.md"
  for pair in "$OUT:json" "$EV:jsonl" "$META:meta" "$META.pre:meta.pre" "$RUN/.codex-round-$N.repair.jsonl:repair.jsonl"; do f="${pair%%:*}"; ext="${pair##*:}"; [ -e "$f" ] && { mv "$f" "$RUN/.round-$N.attempt$k.$ext"; moved=1; }; done
  [ "$moved" -eq 1 ] && echo "preserved attempt as .round-$N.attempt$k.*"
  return 0
}

write_meta() {  # $1 = events file, $2 = prefix ("" or "repair_"), $3 = duration, $4 = exit code; merges into $META
  python3 - "$1" "$META" "$2" "$3" "$4" "$KIND" "$EFFORT" "$(git -C "$WT" rev-parse --short HEAD)" "$STARTED" <<'PY'
import json, sys, os
ev, meta, pre, dur, rc, kind, effort, head, started = sys.argv[1:]
d = {}
if os.path.exists(meta):
    with open(meta) as f:
        for line in f:
            if "=" in line: k, v = line.rstrip("\n").split("=", 1); d[k] = v
tid = d.get("thread_id", ""); u = {}
with open(ev, errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line.startswith("{"): continue
        try: e = json.loads(line)
        except Exception: continue
        if e.get("type") == "thread.started" and not pre: tid = e.get("thread_id", "")
        if e.get("type") == "turn.completed": u = e.get("usage", {})
if not pre: d.update({"kind": kind, "head": head, "thread_id": tid, "effort": effort, "started_at": started})
else: d.pop("parsed", None); d.pop("parse_failed", None); d.pop("repair_started", None)   # a repaired output has not been parsed yet; the repair is no longer in flight
d[pre + "duration_s"] = dur
for k in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"): d[pre + k] = str(u.get(k, ""))
if not pre: d["exit"] = rc
else: d["repair_exit"] = rc
with open(meta + ".tmp", "w") as f: f.write("".join(f"{k}={v}\n" for k, v in d.items()))
os.replace(meta + ".tmp", meta)
PY
}

judge() {  # uses $RC; prints failure reason or nothing. Typed signals only (§7.2 step 2).
  local fail=""
  [ "$RC" -ne 0 ] && fail="codex exit $RC"
  [ -s "$OUT" ] || fail="${fail:+$fail; }output missing/empty"
  if [ -s "$OUT" ]; then
    python3 -c 'import os,sys; sys.exit(0 if os.stat(sys.argv[1]).st_mtime_ns > os.stat(sys.argv[2]).st_mtime_ns else 1)' "$OUT" "$PROMPT" || fail="${fail:+$fail; }output older than prompt"
    python3 -c 'import json,sys; f=open(sys.argv[1]); json.load(f); f.close()' "$OUT" 2>/dev/null || fail="${fail:+$fail; }output not valid JSON"
  fi
  echo "$fail"
}

diagnose() {  # $1 = events file
  echo "--- error events ---"; grep -E '"type":"(error|turn\.failed)"' "$1" | tail -5 | cut -c1-400
  echo "--- tail ---"; tail -c 600 "$1"; echo
}

if [ -n "$REPAIR" ]; then
  TID="$(kv "$META" thread_id)"; [ -n "$TID" ] || { echo "no thread_id in $META"; exit 1; }
  cp "$META" "$META.pre"
  printf 'repair_started=1\n' >> "$META"   # durable marker before Codex runs: an interrupted repair is detectable (R1-F2)
  [ -e "$OUT" ] && { k="$(next_attempt)"; cp "$PROMPT" "$RUN/.round-$N.attempt$k.md"; mv "$OUT" "$RUN/.round-$N.attempt$k.json"; }
  REV="$RUN/.codex-round-$N.repair.jsonl"; STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; t0=$(date +%s)
  printf 'Your `prior` array was invalid: %s. Re-emit the complete review with the correction, changing no findings.\n' "$REPAIR" \
    | codex exec resume "$TID" --json --output-schema "$SCHEMA" -o "$OUT" - > "$REV" 2>&1
  RC=$?; dur=$(( $(date +%s) - t0 ))
  write_meta "$REV" "repair_" "$dur" "$RC"
  fail="$(judge "$REV")"
  if [ -n "$fail" ]; then
    echo "round $N REPAIR FAILED: $fail"; diagnose "$REV"
    k="$(next_attempt)"; cp "$PROMPT" "$RUN/.round-$N.attempt$k.md"; mv "$REV" "$RUN/.round-$N.attempt$k.repair.jsonl"
    [ -e "$OUT" ] && mv "$OUT" "$RUN/.round-$N.attempt$k.json"
    python3 - "$META" "$RUN/.round-$N.attempt$k.meta" <<'PY'
import os, sys
live, att = sys.argv[1], sys.argv[2]
with open(live) as f:
    d = dict(l.rstrip("\n").split("=", 1) for l in f if "=" in l)
rep = {k: v for k, v in d.items() if k.startswith("repair_")}
with open(att, "w") as f:   # the bundle's meta holds only this repair turn (§4.2); totals count it by repair_exit
    f.write("kind=repair\n" + "".join(f"{k}={d.get(k, '')}\n" for k in ("head", "thread_id")) + "".join(f"{k}={v}\n" for k, v in rep.items()))
PY
    mv "$META.pre" "$META"; printf 'repair_exit=%s\n' "$RC" >> "$META"   # pre-repair state plus the failure record; resume re-runs the round
    echo "preserved repair attempt as .round-$N.attempt$k.*"; exit 1
  fi
  rm -f "$META.pre"
  echo "round $N repair ok: ${dur}s"; exit 0
fi

{ [ -e "$OUT" ] || [ -e "$EV" ] || [ -e "$META" ]; } && preserve
if [ "$ASSEMBLE" -eq 1 ]; then python3 "$HERE/assemble-prompt.py" --run-dir "$RUN" --round "$N" --kind "$KIND" || exit 1; fi
[ -s "$PROMPT" ] || { echo "no prompt at $PROMPT"; exit 1; }
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; t0=$(date +%s)
codex exec -s read-only -C "$WT" -c "model_reasoning_effort=\"$EFFORT\"" --json --output-schema "$SCHEMA" -o "$OUT" - < "$PROMPT" > "$EV" 2>&1
RC=$?; dur=$(( $(date +%s) - t0 ))
write_meta "$EV" "" "$dur" "$RC"
fail="$(judge "$EV")"
if [ -n "$fail" ]; then
  echo "round $N FAILED: $fail"
  grep -q '"type":"error"' "$EV" && grep -q -i 'usage limit' "$EV" && echo "reason: Codex usage limit (see error event for the reset time)"
  diagnose "$EV"; preserve; exit 1
fi
echo "round $N ok: ${dur}s"; cat "$META"
