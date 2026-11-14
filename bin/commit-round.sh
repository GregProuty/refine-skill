#!/usr/bin/env bash
# commit-round.sh --run-dir D --kind brief|round|ruling [--round N] [--summary S] [--ids IDS] [--body TEXT]
# Spec §4.2: path-limited commit from an explicit allowlist; BLOCKED PATH (exit 3) on a dirty-baseline path.
set -uo pipefail
export GIT_LITERAL_PATHSPECS=1   # entries are literal paths: no :(magic), no globs (R1-F1)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN=""; KIND=""; N=""; SUMMARY=""; IDS=""; BODY=""
while [ $# -gt 0 ]; do case "$1" in
  --run-dir) RUN="$2"; shift 2;; --kind) KIND="$2"; shift 2;; --round) N="$2"; shift 2;;
  --summary) SUMMARY="$2"; shift 2;; --ids) IDS="$2"; shift 2;; --body) BODY="$2"; shift 2;;
  *) echo "unknown arg $1"; exit 1;; esac; done
[ -n "$RUN" ] && [ -n "$KIND" ] || { echo "usage: commit-round.sh --run-dir D --kind brief|round|ruling ..."; exit 1; }
kv() { grep "^$2=" "$1" | head -1 | cut -d= -f2-; }
TOPIC="$(kv "$RUN/run.meta" topic)"; WT="$(kv "$RUN/run.meta" worktree)"
REL="$(python3 -c 'import os,sys; print(os.path.relpath(os.path.realpath(sys.argv[1]), os.path.realpath(sys.argv[2])))' "$RUN" "$WT")"

case "$KIND" in
  brief) RECORD=""; MSG="refine($TOPIC): brief" ;;
  round) [ -n "$N" ] && [ -n "$SUMMARY" ] || { echo "round needs --round and --summary"; exit 1; }; RECORD="$RUN/response-$N.md"; MSG="refine($TOPIC): round $N ($SUMMARY)" ;;
  ruling) [ -n "$N" ] && [ -n "$IDS" ] || { echo "ruling needs --round and --ids"; exit 1; }; RECORD="$RUN/ruling-$N.md"; MSG="refine($TOPIC): ruling after round $N ($IDS)" ;;
  *) echo "bad kind $KIND"; exit 1 ;;
esac

FILES=()
if [ -n "$RECORD" ]; then
  STATE="$(python3 -c "import sys; sys.path.insert(0,'$HERE'); import refine_lib; print(refine_lib.record_state(sys.argv[1]))" "$RECORD")"
  [ "$STATE" = complete ] || { echo "record $RECORD is $STATE, not complete; refusing to commit"; exit 1; }
  while IFS= read -r f; do [ -n "$f" ] && FILES+=("$f"); done < <(python3 -c "import sys; sys.path.insert(0,'$HERE'); import refine_lib; print('\n'.join(refine_lib.files_changed(sys.argv[1])))" "$RECORD")
  # setup-run.py always writes dirty-baseline; its absence means something is wrong with the run dir, not that nothing is blocked
  [ -e "$RUN/dirty-baseline" ] || { echo "missing $RUN/dirty-baseline; refusing to commit (setup-run.py always writes it)"; exit 1; }
  # macOS ships bash 3.2, where "${FILES[@]}" on an empty array is an unbound variable under set -u; the ${FILES[@]+...} form is safe there
  for f in ${FILES[@]+"${FILES[@]}"}; do
    case "$f" in
      /*) echo "entry '$f' is absolute; entries must be repo-relative; no commit made"; exit 1;;
      :*) echo "entry '$f' uses git pathspec magic; no commit made"; exit 1;;
      ./*|*/./*|.|./) echo "entry '$f' contains a ./ component; no commit made"; exit 1;;
      ..|../*|*/..|*/../*) echo "entry '$f' contains a .. component; no commit made"; exit 1;;
      *'*'*|*'?'*|*'['*|*'\\'*) echo "entry '$f' contains a glob or escape character; no commit made"; exit 1;;
    esac
    canon="$(python3 -c 'import os,sys; wt=os.path.realpath(sys.argv[1]); p=os.path.realpath(os.path.join(wt, sys.argv[2])); print(os.path.relpath(p, wt))' "$WT" "$f")"
    [ "$canon" = "$f" ] || { echo "entry '$f' is not a canonical repo-relative path (resolves to '$canon'); no commit made"; exit 1; }
    [ -d "$WT/$f" ] && { echo "entry '$f' is a directory; list files individually; no commit made"; exit 1; }
  done
  for f in ${FILES[@]+"${FILES[@]}"}; do
    while IFS= read -r b; do
      [ -n "$b" ] || continue
      if [ "$b" = "$f" ]; then echo "BLOCKED PATH $f (in dirty-baseline); no commit made"; exit 3; fi
      case "$b" in "$f"/*) echo "BLOCKED PATH $f (in dirty-baseline); no commit made"; exit 3 ;; esac
    done < "$RUN/dirty-baseline"
  done
fi

# Spec section 4.2: format the run dir's JSON (Codex's round-N.json) with the repo's formatter before
# staging, so a repo-wide format check (prettier --check .) passes on what the run commits.
FMT=(); while IFS= read -r t; do [ -n "$t" ] && FMT+=("$t"); done < <(python3 -c "import sys; sys.path.insert(0,'$HERE'); import refine_lib as L; c=L.format_command(sys.argv[1], L.read_kv(sys.argv[2])); print('\n'.join(c or []))" "$WT" "$RUN/run.meta")
JSONS=(); for j in "$RUN"/*.json; do [ -f "$j" ] && JSONS+=("$j"); done
if [ ${#FMT[@]} -gt 0 ] && [ ${#JSONS[@]} -gt 0 ]; then
  ERR="$( (cd "$WT" && "${FMT[@]}" "${JSONS[@]}") 2>&1 >/dev/null )" || { echo "format failed (${FMT[*]}): $ERR; no commit made"; exit 1; }
fi

ALLOW=("$REL"); for f in ${FILES[@]+"${FILES[@]}"}; do case "$f" in "$REL"/*) ;; *) ALLOW+=("$f");; esac; done
git -C "$WT" add -- "${ALLOW[@]}" || exit 1
if [ -n "$BODY" ]; then git -C "$WT" commit -q -m "$MSG" -m "$BODY" -- "${ALLOW[@]}" || exit 1
else git -C "$WT" commit -q -m "$MSG" -- "${ALLOW[@]}" || exit 1; fi
git -C "$WT" rev-parse --short HEAD
