---
name: refine
description: Harden a spec, plan or implementation by driving Codex review rounds autonomously. Use when the user types /refine, asks to "refine" or "harden" a document or branch with Codex, or wants a Claude-Codex review loop run to convergence.
---

# /refine

You run a review loop: Codex (`codex exec`) reviews the subject, you verify and answer every finding, fix what you accept, commit, and run the next round, until Codex has no remaining P0/P1 findings, a finding is contested, the round cap is reached, or Codex fails. The spec is `docs/design.md`; section numbers below refer to it. Announce "Using /refine" and keep the user informed with exactly one block per round (§9).

`SKILL` below is this skill's directory (`~/.claude/skills/refine`, a symlink to this repository). `RUN` is the run dir. Read every script's output; do not guess. Output contract: `setup-run.py`, `assemble-prompt.py`, `parse-round.py`, `set-status.py`, `resume-position.py`, `render-exchange.py` and `round-summary.py --totals` print one JSON object; `round-summary.py --round N` prints the round block as display text; `run-round.sh` prints text (key=value meta on success, a diagnostic on failure); `commit-round.sh` prints the new short commit hash on success and a diagnostic on failure. Every script's exit code is meaningful and is handled where the step names it.

## Hard rules

- Only these scripts make commits, and only path-limited ones (§4.2). Never `git add -A`, never `git stash`.
- Every finding is verified against the subject and the code before it is accepted or rejected (`superpowers:receiving-code-review`). No "you're right"; state what you checked.
- You never edit a file that is listed in `RUN/dirty-baseline`. If a fix needs one, stop with BLOCKED PATH (§8); once the user has committed or moved that work aside, `resume-position.py` releases the path (it prints it under `released`) and the fix can proceed.
- P2/P3 never keep the loop running. P0/P1 are never `deferred`.
- One fresh Codex review session per round; the only additional Codex invocation allowed in a round is the single semantic-repair continuation of step 2. A round that fails is re-run, never patched by hand.
- Long-running commands (`run-round.sh`) go in the background; report `round N running` once and wait for the notification.

## Arguments

`/refine <subject> [focus notes...] [--rounds N] [--effort high|medium|low] [--confirm] [--resume <run-dir>]`

- `<subject>`: a spec or plan path (kind `spec` or `plan`, inferred from the path and its contents; ask if unclear), or a diff range `<base>...HEAD` (kind `impl`). A range whose right side is not `HEAD` is not supported: ask the user to check out the branch to review.
- Focus notes: free text about low-confidence, fuzzy or risky areas. Add your own low-confidence list from the session.
- `--rounds N` (passed to `setup-run.py` as `--cap N`).
- `--resume <run-dir>`: skip to **Resume** below.

## Round 0: setup and the brief (§7.1)

1. Identify the worktree: for a spec or plan, `git -C <dir of the subject file> rev-parse --show-toplevel`; for impl, `git rev-parse --show-toplevel` of the current directory (the range is reviewed on the checked-out branch). Identify the project's verification command for impl subjects (e.g. `pnpm verify`; never bare `jest`); ask if unknown. Pick a short topic slug.
2. Run setup, with the flags chosen by kind:
   - spec or plan: `--subject-kind spec|plan --subject <path>`
   - impl `<base>...HEAD`: `--subject-kind impl --base <base>` and NO `--subject` (the script derives the changed files from the range)
   ```
   python3 $SKILL/bin/setup-run.py --worktree <wt> --topic <topic> --subject-kind spec|plan|impl [--subject <path>] [--base <base>] [--cap N] [--effort E] [--confirm] [--verify "<cmd>"] [--format "<cmd>"]
   ```
   `--format` is only needed when the repository's JSON formatter is not its own prettier: by default each commit formats the run dir's JSON with `node_modules/.bin/prettier` and the `--config` of the first `package.json` script that runs prettier (§4.2); `--format ""` disables formatting.
   Exit 0 prints JSON: read `run_dir`, `subject` and `dirty_count` from it. Exit 1 means a precondition failed; print its message and stop, then ask for what it names: a valid subject or base when no subject paths were found; to commit or unstage when the index is not empty; to commit the dirty subject paths; or, when the run dir already exists, whether to `/refine --resume <that run dir>` or pick another topic. Never continue without a `run_dir` from a successful call.
3. Write `RUN/brief.md` from `$SKILL/brief-template.md`: fill every `{{...}}`, keep the checklist for this kind and delete the other two, put the user's focus notes and then your own low-confidence items as numbered items after the checklist, write a reading manifest of `path:L<a>-L<b>` pointers (not excerpts) for everything the review needs, list the user's fixed decisions, and set P0/P1 meanings for this subject, and leave the Output format section's `prior` sentence unchanged (the confirm pass rewrites it by exact match). Keep every `<!-- reuse -->` line. Write it to `brief.md.tmp` and `mv` it into place, so a partial brief never exists under the live name.
4. Print, in chat: the run parameters (kind, topic, worktree, HEAD, effort for round 1 and for delta rounds, cap, confirm, verify command, dirty-baseline count) and the brief, section by section. Delta effort is one tier below round 1: high→medium, medium→low, low→low (§3). Do not wait for approval: go straight on to step 5 and round 1. The printout is there so the user can interrupt; if they ask for a change before round 1 finishes, apply it to the brief, commit it, and re-run round 1. The loop has no start gate; it stops only on the §8 outcomes.
5. Commit the brief: `bash $SKILL/bin/commit-round.sh --run-dir $RUN --kind brief`. Exit 0 prints the commit hash. Exit 1 is a git failure: print its diagnostic and stop with the exact resume command.

## Round N (§7.2)

Round kinds: `full` for round 1, `delta` after, `confirm` when resume-position says so.

1. **Run Codex** (background; effort is chosen by the script per §3, except that when any ledger row has a `fixed:*` status with `cycles >= 2` (a fix Codex found incomplete twice, which you fixed again in the previous round) you pass `--effort <the run.meta effort>` so the round runs at round-1 effort, §6):
   ```
   bash $SKILL/bin/run-round.sh --run-dir $RUN --round N --kind full|delta|confirm [--effort high]
   ```
   Say `round N running` and wait. Exit 1 is CODEX FAILURE (§8): print its diagnostic (it names a usage limit and the reset time when that is the cause), then the final summary, then stop. The attempt is preserved; a resume re-runs the same round.
2. **Parse** (it reads the ledger as committed at HEAD, so re-running it is safe until a step-3 or step-4 decision has been recorded):
   ```
   python3 $SKILL/bin/parse-round.py --run-dir $RUN --round N --kind full|delta|confirm
   ```
   Exit 2 prints `{"violations": [...]}`. If `RUN/round-N.meta` already has a `repair_exit` line, a repair was used on this output: this is the second violation, CODEX FAILURE (§8), stop. Otherwise repair once with the violations joined by `; `:
   ```
   bash $SKILL/bin/run-round.sh --run-dir $RUN --round N --kind <kind> --repair "<violations>"
   ```
   If the repair call exits 1 (`REPAIR FAILED`), that is CODEX FAILURE (§8): print its diagnostic and the final summary and stop; the failed repair is preserved as an attempt and the live meta is restored, so a resume re-runs the round. Otherwise parse again. Exit 0 prints `new`, `transitions`, `needs_judgment`, `contested`.
3. **Judge new evidence** for every ID in `needs_judgment` (a rejected row Codex re-raised, or a decided row re-raised in a confirm pass): does its note cite a file:line or subject line not cited before, or answer your rejection rationale directly? If not, contest it now:
   ```
   python3 $SKILL/bin/set-status.py --run-dir $RUN --id <id> --status contested --append-note "no new evidence"
   ```
4. **Respond** under `superpowers:receiving-code-review`, one row at a time, for every row now `open` or `reopened`:
   - Verify the claim against the subject and the code. Then either fix it now, reject it, or, for P2/P3 only, defer it, and record the decision:
     ```
     python3 $SKILL/bin/set-status.py --run-dir $RUN --id <id> [--id <id>] --status fixed:R<N> --note "<what changed and where>"
     python3 $SKILL/bin/set-status.py --run-dir $RUN --id <id> --status rejected --note "<one-line evidence>"
     python3 $SKILL/bin/set-status.py --run-dir $RUN --id <id> --status deferred --note "<why>"
     ```
     The full rationale for a rejection goes in the response file.
   - Write `RUN/response-N.md` from `$SKILL/response-template.md` **after** the fixes are on disk: write to `response-N.md.tmp`, then `mv` it into place. `## Files changed` lists every file you edited outside the run dir as `- <repo-relative path>`; the last line is `<!-- end -->`. Never list a `dirty-baseline` path; if a fix needs one, stop with BLOCKED PATH: name the path and the finding, and ask the user to commit or move that work aside (not `git stash`).
5. **Verify.** spec/plan: re-read every section you changed against the rest of the document for contradictions. impl: run the `verify` command from `RUN/run.meta`; a failure is fixed before committing, or the loop stops with VERIFY FAILURE and the output.
6. **Render and commit**:
   ```
   python3 $SKILL/bin/render-exchange.py --run-dir $RUN
   bash $SKILL/bin/commit-round.sh --run-dir $RUN --kind round --round N --summary "<a> accepted, <r> rejected, <d> deferred"
   ```
   Add `--body "<k> contested: <ids>"` when any row went contested this round. Exit 0 prints the commit hash. Exit 1 with "not complete" means the response file is incomplete: rewrite it correctly (step 4), re-render, and retry the commit once; any other exit 1 is a git failure: print its diagnostic and stop with the exact resume command. Exit 3 is BLOCKED PATH (see step 4): print the path and the finding, the final summary, and the resume command; stop.
7. **Print the round block**: run `python3 $SKILL/bin/round-summary.py --run-dir $RUN --round N` and print its output verbatim in chat. It reads the ledger's final statuses, the meta (tokens include any repair turn), the round JSON and the round commit; its `Status` line is the §8 outcome:
   ```
   ── /refine round N/<cap> · <kind> <topic> · rev <head> · codex <m>m<ss>s · <tok>k tok (<cached>k cached) ──
   Verdict  <verdict>
   New      <sev> <id>  <title>                          accepted → fixed | rejected | deferred
   Prior    <id> <sev> ✓ ...        <id> <sev> ⚠ still open (cycles c) → open | reopened | CONTESTED
   Commit   <hash>  <message>
   Status   CONTINUING → round N+1 (<kind>, effort <e>) | STOPPING — <outcome>
   ```
8. **Evaluate** `python3 $SKILL/bin/resume-position.py --run-dir $RUN` (it also refreshes the dirty baseline and prints `released`) and act on `outcome`:
   - `CONTINUE`: next round, kind `delta`. `CONFIRM`: next round, kind `confirm` (only once per run).
   - `CONTESTED` (a disagreement: you rejected and Codex re-raised without new evidence or twice, or a fix missed three times): print each contested row as two positions with citations (Codex's claim and latest note; your rejection or fix and why), your recommendation per ID, and the ruling options `accept | reject | stop`. Print the final summary. Stop and wait for the user. `stop` means no ruling: leave the contested statuses as they are, write no ruling file and make no commit, start no round; the run stays resumable with the printed `/refine --resume` command and will ask for the ruling again.
   - `CONVERGED` or `CAP`: print the final summary. Stop.

## Ruling (§8 CONTESTED)

When the user rules, in this order:
1. Write `RUN/ruling-N.md` from `$SKILL/ruling-template.md` in its **pending** form (decisions and reasons, last line `<!-- pending -->`), via `.tmp` + `mv`, before touching any other file. For each ID state its actual `cycles` and why it was contested (a rejection re-raised, or a third miss), taken from the ledger row.
2. Apply the fix for each *accept* (verify against the current tree first; a fix may already be partly present after a resume).
3. Rewrite `ruling-N.md` complete: the same decisions, then `## Files changed` with the same grammar as a response: every file edited outside the run dir, once, as `- <repo-relative path>`, no other non-blank lines in the section, an empty section allowed, no `dirty-baseline` path (BLOCKED PATH otherwise, as in Round N step 4); last line `<!-- end -->`; written via `.tmp` + `mv`.
4. Set statuses (cycles stay as they are); one `--id` flag per ID:
   ```
   python3 $SKILL/bin/set-status.py --run-dir $RUN --id <id> [--id <id>] --status fixed:ruling<N> --note "<what changed>"
   python3 $SKILL/bin/set-status.py --run-dir $RUN --id <id> [--id <id>] --status closed-by-user --note "<user's reason>"
   ```
5. `python3 $SKILL/bin/render-exchange.py --run-dir $RUN` then `bash $SKILL/bin/commit-round.sh --run-dir $RUN --kind ruling --round N --ids "<ids>"`. The ruling commit is made even when every ruling is a reject. Exit 1 with "not complete" (or "pending"): finish step 3 and retry once; other exit 1: git failure, print and stop with the resume command; exit 3: BLOCKED PATH, print the path and the ID, the final summary and the resume command, stop.
6. Evaluate with `python3 $SKILL/bin/resume-position.py --run-dir $RUN` and act on `outcome` as in Round N step 8: `CONTINUE` starts round N+1 (kind `delta`) to verify the accepted fixes; `CONVERGED` (possible when every ruling was a reject and every P0/P1 row is now terminal) prints the final summary and stops.

## Resume (§7.3)

`python3 $SKILL/bin/resume-position.py --run-dir $RUN` prints `phase`, `next_round` and `next_kind`; enter the loop there:
- `setup`: the run dir exists but the brief was never committed. Do NOT run `setup-run.py` again (it refuses an existing run dir). If `RUN/brief.md` is missing, or exists but fails validation (it must have the eight H2 sections of the template in order, the five `<!-- reuse -->` lines, and no `{{...}}` placeholder left), write it again (Round 0 step 3); then print the parameters and brief (step 4) and commit (step 5).
- `ask-ruling`: re-print the contested positions (Round N step 8, CONTESTED) and wait.
- `apply-ruling`: the decision is recorded in the pending `ruling-N.md`; do Ruling steps 2 to 6.
- `commit-ruling`: the ruling file is complete; do Ruling steps 4 to 6.
- `stop`: print the final summary.
- `assemble`: Round N step 1 as written (the normal `run-round.sh` call assembles the prompt).
- `run`: the prompt exists and must be re-sent exactly: `bash $SKILL/bin/run-round.sh --run-dir $RUN --round <next_round> --kind <next_kind> --no-assemble` (plus `--effort <run.meta effort>` under the step-1 bump rule), run in the background with step 1's `round N running` announcement and step 1's exit handling (exit 1 is CODEX FAILURE: diagnostic, final summary, stop); on exit 0 continue at step 2. This is also where a round lands after its one repair failed semantics again.
- `parse`: Round N step 2.
- `respond`: parse is done. First do step 3 for exactly the IDs in the `needs_judgment` line of `RUN/round-<next_round>.meta` (parse-round.py records them there; do not re-run parse and do not reconstruct the list from statuses: a fixed row reopened after a miss is `open` too but needs no judgment). Then step 4, re-verifying every `open` and `reopened` row against the current tree; fixes may be partly applied.
- `verify-commit`: steps 5 to 8.
If it printed `released` paths, say so: those files were blocked and are now editable.

## Final summary

On every stop: `python3 $SKILL/bin/round-summary.py --run-dir $RUN --totals` gives the numbers (rounds, failed attempts, wall time, tokens over every round and attempt meta with repair turns included, findings by status). Print: outcome; those numbers; the contested block if any (Codex's claim and latest note, your position, both cited); the deferred list; the commit range (`git log --oneline -- $RUN`); whether a confirm pass ran; and for CONTESTED, CODEX FAILURE or BLOCKED PATH the exact resume command with absolute paths: `/refine --resume <absolute run dir>`.
