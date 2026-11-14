# `/refine` — Claude-driven Codex review loop

Date: 2026-09-18
Status: design, rev 7 (rev 5 converged after Codex review round 5; rev 6 changes the contested rule after two real runs; rev 7 removes the brief go gate)
Supersedes: the manual paste-between-terminals workflow and the shared
`REVIEW.md` back-and-forth skills.

## 1. Problem

Hardening a spec, plan, or implementation today means running Claude Code in
one terminal and Codex in another, pasting Claude's output into Codex, pasting
Codex's review back, and repeating until the review has no blocking findings.
Convergence takes several rounds; every round is hand-driven.

Codex can be run non-interactively from a Claude Code shell (`codex exec`).
A prototype of that (`run-round.sh` in the erebor-reverse-design worktree,
2026-09-18) produced a real round-1 review — 2 P0, 8 P1, 1 P2 — in about 8
minutes and ~216k Codex tokens, and its first round-2 attempt died on an
out-of-credits error after spending 202k tokens without writing a finding.
That prototype proves the transport and exposes the two costs the skill must
manage: Codex re-discovering the codebase on every round, and failures that
arrive late.

## 2. Goal

A skill, `/refine`, that runs the review loop autonomously: draft the brief,
run a Codex round, verify and respond to every finding, fix what is accepted,
commit, run the next round, and stop when Codex has no remaining P0/P1
findings, when a finding is contested, when a round cap is reached, or when
Codex fails. The user sees one compact block per round and a final summary.

Non-goals:
- Replacing the human's final read. `/refine` hardens; the user still reviews.
- Running Jest inside Codex (it hangs in this repo). Codex verifies with
  `tsc --noEmit`, `grep`, `sed`, `cat`.
- A persistent Codex session across rounds. Considered and deferred (§13).
- Refining more than one subject per run.

## 3. Invocation

```
/refine <subject> [focus notes...] [--rounds N] [--effort high|medium|low]
        [--confirm] [--resume <run-dir>]
```

`<subject>` is one of:

| kind | argument | Codex reviews |
|------|----------|---------------|
| spec | path to a design doc | the document, against the codebase it describes |
| plan | path to an implementation plan | the plan, against the spec it conforms to and the branch it will execute on |
| impl | a diff range (default `main...HEAD`) | the diff, against the spec/plan it implements |

For impl subjects the run dir is excluded from every diff Codex sees
(`-- . ':!docs/superpowers/reviews'`), so the brief and round commits do not
appear as reviewable changes. The impl subject's **subject paths** are the
files in the diff range at setup, plus every file the loop edits afterwards
(§7.2 step 4).

Claude infers the kind from the argument and asks if it cannot. Focus notes
are free text: areas of low confidence, fuzzy sections, risky steps. Claude
adds its own low-confidence list from the session.

Flags:
- `--rounds` caps the loop (default 10). The cap counts every Codex round,
  including a confirm pass.
- `--effort` sets round-1 reasoning effort (default `high`). Delta rounds use
  the next lower tier: `high → medium`, `medium → low`, `low → low`.
- `--confirm` adds one final full-review pass after convergence (default
  off), if a round remains under the cap.
- `--resume <run-dir>` re-enters an existing run at the exact phase where it
  stopped (§7.3). All loop state is on disk and in git.

## 4. Files

### 4.1 The skill

`~/.claude/skills/refine/` (global, alongside `grilling` and
`confidence-assessment`):

| file | role |
|------|------|
| `SKILL.md` | the procedure Claude follows |
| `run-round.sh` | assembles the prompt for round N, runs Codex, judges success, writes `round-N.meta` |
| `parse-round.sh` | applies the `prior` transitions and appends new findings to the ledger; reports semantic violations |
| `review.schema.json` | the JSON Schema Codex's output must conform to (§5.2) |
| `probe.sh` | the 4-second schema smoke test (§11) |
| `brief-template.md` | the brief skeleton with per-kind checklists and `<!-- reuse -->` markers |
| `response-template.md` | the shape of Claude's per-round response |

### 4.2 The run directory

`docs/superpowers/reviews/<YYYY-MM-DD>-<topic>/` in the repo that holds the
subject:

| file | content | committed |
|------|---------|-----------|
| `brief.md` | the round-1 brief; sections marked `<!-- reuse -->` are carried into delta prompts | yes |
| `ledger.md` | one row per finding; **the source of truth for termination** | yes |
| `round-N.json` | Codex's output for round N, conforming to `review.schema.json` | yes |
| `response-N.md` | Claude's response for round N: per-finding verdicts with evidence, then `## Files changed`, then the end marker | yes |
| `ruling-N.md` | the user's ruling on the rows contested after round N: per ID the decision and a one-line reason, then `## Files changed` for the accepted fixes, then the end marker. Written first as a **pending** ruling (decisions only, final line `<!-- pending -->`) before any fix is applied | yes |
| `exchange.md` | rendered from every `round-N.json` and `response-N.md` in order; regenerated before each commit | yes |
| `.prompt-round-N.md` | the exact prompt sent; makes any round reproducible | yes |
| `round-N.meta` | `kind` (`full`, `delta` or `confirm`), `head`, `thread_id`, `effort`, `started_at`, `duration_s`, `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens`, `exit`, and the `repair_*` fields when a repair turn ran | yes |
| `dirty-baseline` | every path dirty in the working tree at round 0, one per line; the loop may never commit these | yes |
| `.codex-round-N.jsonl` | the typed event stream from `--json`; diagnostic only. A repair turn writes `.codex-round-N.repair.jsonl` | no |
| `.round-N.attempt<k>.*` | the prompt, output, meta and event stream of a failed or repaired attempt, preserved | no |

The run dir's `.gitignore` holds `*.jsonl`, `.round-*.attempt*` and the
exception `!fixture-*.jsonl`, so a captured failure stream can be kept.

**Commits.** Round 0 requires an empty index and clean subject paths;
otherwise the skill stops and asks. Every other dirty path in the working
tree is recorded in `dirty-baseline`. Every commit is path-limited to an
explicit allowlist — the run dir plus the `## Files changed` list from the
commit's own record: `response-N.md` for a round commit, `ruling-N.md` for
a ruling commit — using `git add -- <new files>` then
`git commit -- <allowlist>`. Path-limited commits ignore whatever else is
staged or dirty, so nothing outside the allowlist is ever swept in. A
`## Files changed` list may not name a path in `dirty-baseline`: that file
already holds the user's uncommitted work, and a path-limited commit would
take all of it. If a fix needs such a file the loop stops with BLOCKED PATH
(§8).

**Formatting.** Before staging, every commit formats the run dir's `*.json`
(Codex's `round-N.json`, written compact) with the repository's own
formatter, so a repository-wide format check passes on what the run
commits. The command is `run.meta`'s `format=` when present (set by
`setup-run.py --format`; empty disables it); otherwise the worktree's
`node_modules/.bin/prettier --write`, with the `--config` of the first
`package.json` script that runs prettier. No prettier installed means no
formatting. A formatter failure stops the commit (exit 1, nothing
committed). Reformatting changes no JSON value, so `parse-round.py` and the
renderers read the same content.

```
refine(<topic>): brief
refine(<topic>): round N (<a> accepted, <r> rejected, <d> deferred)
refine(<topic>): ruling after round N (<ids>)
```

## 5. The brief

Built from `brief-template.md`. Sections, in order:

1. **Role** `<!-- reuse -->` — what Codex is reviewing and why.
2. **What to review** — the subject, the documents it must conform to, the
   worktree path and the revision. Regenerated for every delta prompt with
   the current revision.
3. **What to check, in priority order** — the kind's default checklist,
   then the user's focus notes, then Claude's low-confidence list.
4. **Reading manifest** — the files and line ranges that matter, per focus
   area, as `path:L<a>-L<b>`. Pointers, never excerpts. Instruction: *read
   by range (`sed -n`), not whole files; do not `ls` or explore beyond the
   manifest unless a finding requires it, and say so if you do.* For impl
   subjects the manifest is the `--stat` file list of the diff plus the
   spec/plan.
5. **Constraints** `<!-- reuse -->` — read-only; no Jest; no `.env*`,
   `secrets/`, credential or key files; allowed commands.
6. **Fixed decisions** `<!-- reuse -->` — decisions attributed to the user
   that Codex must not propose reversing, but must flag if the subject
   violates.
7. **Output format** `<!-- reuse -->` — the meaning of each field in §5.2;
   the schema enforces the shape.
8. **Severities** `<!-- reuse -->` — P0/P1/P2/P3 definitions, tuned to the
   subject kind, plus the cap: at most 12 findings, prefer fewer verified
   over many speculative, unsure → `not_verified`.

`<!-- reuse -->` is a line directly under the H2 heading. The runner
extracts every H2 section carrying the marker, by marker, not by name.

### 5.1 Default checklists by kind

- **spec**: internal contradictions; requirements with two readings;
  unstated assumptions; missing failure modes and degraded states;
  acceptance criteria that cannot be tested; interfaces described that the
  codebase does not have.
- **plan**: executability against the actual branch — every consumed
  interface (methods, signatures, types, schemas, helpers, exports) exists
  with the shape the plan assumes; spec conformance, with deviations stated
  and justified; task ordering and dependencies; whether the tests the plan
  writes can pass against the helpers that exist.
- **impl**: correctness against the spec/plan; the invariants named in the
  focus notes; `tsc --noEmit` clean; test adequacy for the risky paths;
  anything the plan said to do that the diff does not.

### 5.2 Output contract

Codex runs with `--output-schema review.schema.json`; its final message must
conform (probed on Codex 0.155.0, 2026-09-18: the `-o` file conformed on the
first attempt). The schema, abridged:

```
{ "verdict":      "changes requested" | "ready with P2s" | "ready",
  "findings":     [ { "severity": "P0"|"P1"|"P2"|"P3", "title", "claim",
                      "evidence", "why", "fix" } ],
  "prior":        [ { "id", "result": "resolved"|"withdrawn"|"still open",
                      "note" } ],
  "verified":     [ string ],
  "not_verified": [ string ] }
```

All fields required, no additional properties. `evidence` cites the subject
by line (`spec L<n>`) and code by `file:L<n>`. Findings are ordered by
severity then importance. Claude assigns IDs `R<N>-F<k>` in array order;
Codex never invents IDs. In round 1 `prior` must be empty.

The rendered form, used in `exchange.md` and in the awaited-findings block
of delta prompts:

```
Verdict: changes requested

### [P0] R1-F1 <title>
<claim> · <evidence> · <why> · <fix>

## Prior findings
- R1-F3: resolved — <note>

## Verified
- …
## Not verified
- …
```

## 6. The ledger

`ledger.md` is a markdown table, one row per finding, rewritten by Claude
each round:

```
| id    | sev | title                                  | status         | cycles | note                                        |
|-------|-----|----------------------------------------|----------------|--------|---------------------------------------------|
| R1-F1 | P0  | CAN escapes unresolved parks           | resolved       | 0      | fixed:R1, confirmed R2                      |
| R1-F3 | P1  | A2 not pinned on recovery              | rejected       | 0      | plan L1420 pins A2 before fallthrough       |
| R1-F5 | P1  | payout retry after FAILED              | contested      | 2      | R2 reopened w/ new evidence; R3 still open  |
| R2-F2 | P2  | inbound-wire identity fields stripped  | deferred       | 0      |                                             |
```

Statuses and who sets them:

| status | set by | meaning |
|--------|--------|---------|
| `open` | Claude, on parse | raised, not yet answered |
| `fixed:R<N>` | Claude, on respond | accepted; fixed in round N's commit; awaiting Codex confirmation |
| `fixed:ruling<N>` | Claude, on ruling | accepted by the user's ruling; fixed in the ruling commit after round N; awaiting confirmation |
| `resolved` | Claude, on parse | Codex reported `resolved` for a `fixed:*` row |
| `rejected` | Claude, on respond | not a defect; one-line evidence in `note`, full rationale in `response-N.md` |
| `withdrawn` | Claude, on parse | Codex reported `withdrawn` for a `rejected` row |
| `reopened` | Claude, on parse | Codex reported `still open` on a `rejected` row with new evidence; Claude answers again |
| `contested` | Claude, on parse | needs the user's ruling (rules below) |
| `closed-by-user` | Claude, on ruling | user ruled reject |
| `deferred` | Claude, on respond | P2/P3 not fixed in-loop; listed at the end. Never for P0/P1 |

The status names the commit without containing its hash: round N's commit
is the one whose message starts `refine(<topic>): round N (`, the ruling
commit `refine(<topic>): ruling after round N (`; both are located with
`git log --grep`, and round N+1's `head` in its meta is round N's commit.

**Awaited IDs** are the rows with status `fixed:*` or `rejected` when a
delta prompt is assembled; Codex must report each one in `prior`. `open`
and `reopened` are transient: every such row is answered in the same
round's respond step and leaves it as `fixed:*`, `rejected` or `deferred`.

**Transitions** on parse, by row status × Codex `result`:

| row status | `resolved` | `withdrawn` | `still open` |
|------------|------------|-------------|--------------|
| `fixed:*` | → `resolved` | violation | `cycles += 1`; `cycles ≥ 3` → `contested`, else → `open` (Claude fixes again; at `cycles = 2` the next round runs at the round-1 effort) |
| `rejected` | violation | → `withdrawn` | `cycles += 1`; no new evidence or `cycles ≥ 2` → `contested`, else → `reopened` |

A `prior` entry whose `id` is not awaited, a duplicated `id`, or an awaited
`id` with no entry is a **semantic violation** (§7.2 step 3). "New
evidence" — a file:line or subject line not previously cited, or a direct
answer to the rejection rationale — is Claude's judgment, bounded by the
cycle limit. `cycles` is a lifetime counter: it is never reset, including
by a user ruling, so after an accept ruling a further `still open` takes
the row past its limit and re-contests it.

**Contested means disagreement.** A `rejected` row that Codex re-raises is
a disagreement between the two reviewers and goes to the user quickly (no
new evidence, or a second rejection). A `fixed:*` row that Codex reports
still open is not a disagreement, it is an incomplete fix: Claude fixes it
again, the next round after a second miss runs at the round-1 effort so
Codex verifies harder, and only a third miss escalates. Two real runs of
this loop stopped four times under the earlier rule (contested at two
misses regardless), every time on a finding the responder agreed with,
three of them trivial; the rule was costing a human round trip for a `cp`.

**In a confirm pass** (§8) the awaited rows stay mandatory, and `prior` may
additionally carry any decided row — `resolved`, `withdrawn`,
`closed-by-user` or `deferred` — only as `still open`. Transitions:
`resolved`/`withdrawn` → `cycles += 1`, then `open` with new evidence, else
`contested`; `closed-by-user` → `contested` (the user ruled once already);
`deferred` → unchanged, the note is appended. A `resolved` or `withdrawn`
result on a decided row is a no-op. Outside a confirm pass a decided ID in
`prior` is still an unknown-ID violation.

## 7. The loop

### 7.1 Round 0 — setup

1. Infer subject kind, topic slug, the worktree (`git rev-parse
   --show-toplevel` of the subject path — the workspace has many worktrees,
   Codex must run in the right one), and the project's verification command
   (e.g. `pnpm verify`; never bare `jest`). Ask if unknown.
2. Require an empty index and clean subject paths; otherwise stop and ask.
3. Create the run dir with its `.gitignore`, and write `dirty-baseline`
   from `git status --porcelain` (every path not under the run dir).
4. Write `brief.md` per §5.
5. Print the brief, the run parameters, the verify command and the
   dirty-baseline count, then continue without waiting (rev 7: the go gate
   is removed; the user interrupts if the brief is wrong).
6. Commit `refine(<topic>): brief` (run dir only).

### 7.2 Round N, N = 1 … cap

1. **Assemble prompt** (`run-round.sh`) into `.prompt-round-N.md`.
   N = 1: `brief.md` verbatim. N > 1, the delta prompt, in order:
   - the brief's `<!-- reuse -->` sections
   - **What to review**, regenerated: subject path(s), worktree, current
     `HEAD`, and the round-1 references
   - the delta preamble: *the subject was revised since your findings;
     verify each awaited finding against the diff and the current text by
     ID; look for regressions in the regions the diff touches; report every
     awaited ID in `prior`; raise new findings only in touched regions or
     where a fix directly caused them; do not re-review unchanged sections*
   - `ledger.md`
   - **Awaited findings**, verbatim: the rendered finding block (§5.2) of
     every awaited ID `R<M>-F<k>`, taken from `round-<M>.json` — the output
     of the round that raised it, not the round being assembled
   - the inline diff: `git diff <head from round-(N-1).meta>..HEAD --
     <subject paths>` — everything that changed since Codex last looked;
     for impl subjects the whole fix commit including tests
   - **Delta manifest**: for each hunk, the enclosing section of the
     *current* subject (nearest H2/H3 above the hunk, to the next heading)
     as `path:L<a>-L<b>`, plus every section an awaited finding's `evidence`
     cites, re-located in the current file; with the round-1 reading
     instruction
   - `response-(N-1).md`, so Codex sees the rationale for each verdict
2. **Run Codex** (`run-round.sh`, in the background — a round can exceed
   the foreground tool limit). The output file is removed first; the prompt
   is fed on stdin with `-` (with a prompt argument and a non-TTY stdin,
   codex blocks waiting to append stdin, and it refuses a directory that is
   not trusted in `~/.codex/config.toml`):
   ```
   codex exec -s read-only -C "$WORKTREE" \
     -c "model_reasoning_effort=\"$EFFORT\"" \
     --json --output-schema "$SKILL/review.schema.json" \
     -o "$RUN/round-$N.json" - < "$RUN/.prompt-round-$N.md" \
     > "$RUN/.codex-round-$N.jsonl" 2>&1
   ```
   Success is judged from typed signals only: exit code 0, `round-N.json`
   present, newer than the prompt, and valid JSON. The event stream is
   never grepped for control flow. `round-N.meta` is written from
   `thread.started.thread_id` and `turn.completed.usage`, plus `kind`,
   `head`, `effort`, `started_at`, `duration_s` and `exit`. "No confirm
   pass has run" (§8) means no committed meta has `kind=confirm`. On failure the attempt's
   files are preserved as `.round-N.attempt<k>.*`, the loop stops (§8), and
   the same N is re-run on resume.
3. **Parse** (`parse-round.sh`). Shape is guaranteed by the schema; the
   script checks the semantics of §6 — every awaited ID present exactly
   once, no unknown IDs, only valid transitions, `prior` empty in round 1 —
   then applies the transitions and appends new findings as `open` rows.
   A semantic violation is repaired once by resuming the same session:
   `codex exec resume <thread_id> --json --output-schema … -o … -` with
   *"your `prior` array was invalid: <exact problem>; re-emit the complete
   review with the correction, changing no findings"* on stdin, events to
   `.codex-round-N.repair.jsonl`. Codex already holds the review, so this
   costs a fraction of a round. The first output is preserved as an attempt
   file, and `round-N.meta` gains `repair_duration_s` and the four
   `repair_*_tokens` fields from the repair turn's `turn.completed`; every
   total in §9 includes them. A second violation stops the loop.
4. **Respond** (`response-N.md`, from `response-template.md`) under
   `superpowers:receiving-code-review`: every P0/P1/P2 is verified against
   the subject and the code before it is accepted or rejected. Accept → fix
   now. Reject → evidence. P3, and P2s whose fix is out of proportion →
   `deferred`. `reopened` IDs are answered again with the new evidence
   addressed. The response's last section is `## Files changed`: one entry
   per line, each exactly `- <repo-relative path>` (the scripts strip the
   `- ` prefix; blank lines are allowed; any other line between the heading
   and the marker makes the file incomplete), for every file the round
   edited outside the run dir (run-dir files are always in the allowlist
   and may be omitted), none of them in `dirty-baseline`; the section may
   list no paths when a round changed nothing outside the run dir. The
   file's final line is the end marker `<!-- end -->`. The response is written **after** the fixes are applied,
   to a temporary name and renamed into place, with the marker emitted
   last. A response is **complete** when its last line is `<!-- end -->`
   and a `## Files changed` heading precedes it; anything else is
   incomplete and is treated as absent. `ruling-N.md` uses the same
   section and marker.
5. **Verify.** spec/plan: re-read every changed section for contradictions
   with the rest of the document. impl: the project's verification command.
   A failing verification is fixed before the round commits; if it cannot
   be, the loop stops with the failure output.
6. **Render `exchange.md`**, then commit the round (path-limited, §4.2).
7. **Print the round block** (§9), evaluate termination (§8). Continue or
   stop.

### 7.3 Resume

`--resume <run-dir>` (and an interrupted session continuing in place)
derives its position from git and the run dir, in this order:

1. `N_done` = the highest N with a commit `refine(<topic>): round N (`
   **among the commits that touch this run dir** (`git log --grep … --
   <run-dir>`), 0 if only the brief commit exists. Ruling commits are found
   the same way. Anchoring to the run dir keeps a later run that reuses a
   topic from inheriting this one's rounds.
2. If `N_done ≥ 1`, evaluate §8 for round `N_done` from the committed
   ledger — termination is a function of the ledger, `N_done` and the
   flags, so it can be re-derived. If it yields a stop, stop there: this is
   how an interruption between the round commit and step 7 does not start
   round `N_done + 1` past the cap or after convergence, and how a pending
   ruling (a `contested` row with no later ruling commit) is re-surfaced.
   The ruling file decides what to do next: a complete
   `ruling-N_done.md` without its commit means the fixes are applied, so
   finish the §8 sequence from the ledger update onward; a **pending** one
   (final line `<!-- pending -->`) means the decision is recorded but the
   fixes may be partial, so re-verify and apply each accepted fix against
   the current tree (as in §7.2 step 4, an already-applied fix is simply
   present), complete the file, and continue; only when no ruling file
   exists is the user asked again.
3. `N = N_done + 1`. Then, by the state of round N's files:

| on disk | resume at |
|---------|-----------|
| no `.prompt-round-N.md` | step 1 |
| prompt, but no `round-N.json`/`round-N.meta`, or meta `exit ≠ 0`, or output older than the prompt or not valid JSON | step 2 — re-run; the stale attempt is preserved |
| valid output, ledger has no `R<N>-` rows and awaited rows unchanged | step 3 |
| ledger updated for round N, no complete `response-N.md` | step 4 — Claude re-verifies every `open` row against the current tree; a partially applied fix is simply already present |
| `response-N.md` complete (last line `<!-- end -->`, `## Files changed` before it) | step 5, then 6 |

Nothing in the run dir is ever overwritten silently: a re-run moves the
previous attempt aside first.

## 8. Termination

Evaluated after every round, first match wins:

| outcome | condition | then |
|---------|-----------|------|
| CODEX FAILURE | `run-round.sh` judged the round failed, or two consecutive semantic violations | print the diagnostic (exit code, last `error`-typed events if any) and the resume command; stop |
| VERIFY FAILURE | the round's fixes fail verification and cannot be repaired in-round | print the failure; stop |
| BLOCKED PATH | an accepted fix needs a file listed in `dirty-baseline` | name the path and the finding; stop. The user commits or moves that work aside (never `git stash`, per the workspace rules), then resumes |
| CONTESTED | any P0/P1 row is `contested` | print both positions side by side with citations; stop. The user rules per ID in chat. Claude then, in this order: writes `ruling-N.md` as a **pending** ruling (per ID the decision and reason, final line `<!-- pending -->`, temp-and-rename) before touching any file, so the decision is on disk first; applies the fix for each *accept*; rewrites `ruling-N.md` complete (the same decisions, `## Files changed` under the dirty-baseline rule and the entry grammar of §7.2 step 4, final line `<!-- end -->`); updates the ledger — `fixed:ruling<N>` for accepted IDs (cycles unchanged), `closed-by-user` for rejected; renders `exchange.md`; makes **one** path-limited commit `refine(<topic>): ruling after round N (<ids>)` whose allowlist is the run dir plus `ruling-N.md`'s `## Files changed`. The ruling commit is made even when every ruling is a reject, so the decision is in git and §7.3 step 2 sees it. The next delta round verifies the accepted fixes. Rulings in the same session continue the loop directly; `--resume` is for a new session |
| CONVERGED | round N raised no P0/P1, and every prior P0/P1 row is `resolved`, `withdrawn` or `closed-by-user` | if `--confirm`, no confirm pass has run, and `N < --rounds`: round N+1 is a **confirm pass** — the brief with **What to review and the reading manifest regenerated against the current revision** (for impl, the current diff's file list; for prose, the current section map) + `ledger.md` + the rendered blocks of every decided finding + the rule *a decided ID may be raised again only as a `prior` entry with `still open` and new evidence, never as a new finding* (parsed per §6's confirm-pass transitions); evaluate again (a confirm pass that raises P0/P1 continues the loop as delta rounds). Otherwise stop |
| CAP | `N ≥ --rounds` | stop; list what is still open |

Remaining P2/P3 are never a reason to continue; they are listed as deferred.

Interrupt (ctrl-c) at any point leaves the run dir and git in a state §7.3
can resume from.

## 9. What the user sees

While a round runs: one line, `round N running`. When it completes, one
block:

```
── /refine round 3/10 · plan erebor-reverse-2 · rev 2cdff696 · codex 4m12s · 61k tok ──
Verdict  changes requested
New      P1 R3-F1  payout retry re-issues blockchain_out after FAILED   accepted → fixed
         P2 R3-F2  inbound-wire identity fields still stripped           deferred
Prior    R1-F1 P0 ✓  R1-F2 P0 ✓  R1-F3 P1 ✓  R1-F4 P1 ✓
         R1-F5 P1 ⚠ still open, no new evidence → CONTESTED
Commit   a1b2c3d  refine(erebor-reverse-2): round 3 (1 accepted, 0 rejected, 1 deferred)
Status   STOPPING — 1 contested finding needs your ruling
```

`tok` is `input + output` from the meta, including any `repair_*` fields.
On any stop, a final summary: outcome; rounds run; total Codex tokens
(input, cached, output, reasoning, repair included) and wall time summed
from `round-N.meta`; findings by final status; the
contested block (Codex's claim, Claude's rejection, both cited); the
deferred list; the commit range; whether a confirm pass ran; and, for
CONTESTED or CODEX FAILURE, the exact resume command with absolute paths.

## 10. Cost model

Measured so far (Codex 0.155.0, `gpt-5.6-sol`):

| run | subject | effort | manifest | duration | tokens |
|-----|---------|--------|----------|----------|--------|
| prototype round 1 | 2,300-line plan + branch | high | file list, no ranges | ~8 min (not recorded) | 216,338 |
| this spec, round 1 | 374-line spec + 5 prototype files | high | ranges | 6 min 41 s | 54,953 |
| this spec, round 2 (delta) | 472-line spec, whole-file diff, 60 KB prompt | medium | section map | 2 min 2 s | 174,617 in (120,704 cached) + 6,395 out |
| this spec, round 3 (delta) | 509-line spec, 9 touched sections, 40 KB prompt | medium | touched sections | 1 min 17 s | 95,813 in (55,680 cached) + 3,853 out |
| this spec, round 4 (delta) | 523-line spec, 5 touched sections, 25 KB prompt | medium | touched sections | 1 min 11 s | 88,740 in (53,120 cached) + 2,988 out |
| SKILL.md, round 1 (first run of the built scripts) | 114-line procedure + spec sections + 9 script parsers | high | ranges | 5 min 48 s | 231,200 in (179,328 cached) + 18,700 out |
| SKILL.md, round 2 (delta) | 127-line procedure, 6 touched sections, 42 KB prompt | medium | touched sections | 1 min 39 s | 173,932 in (111,616 cached) + 4,695 out |
| SKILL.md, round 3 (delta) | 1 awaited ID | medium | touched sections | 0 min 41 s | 103,931 in (74,240 cached) + 1,717 out |

The three SKILL.md rows are the first measurement of the built scripts (`run-round.sh` and `round-summary.py --totals`), not the prototype; the run converged in three rounds with no failed attempts.

Round 1 is a discovery pass. Delta rounds ran at a third to a fifth of
round 1's wall time. Round 2's input count is high because a whole-file
rewrite made the diff the whole file; rounds 3 and 4, with targeted diffs,
halved it, and in every delta round more than half the input was served
from Codex's prompt cache. Every round writes its actuals to `round-N.meta`
(the prototype round 1 count above is the transcript's `tokens used` line;
from this run on the fields are the typed `usage` breakdown); these are the
data for adjusting effort tiers and the manifest instructions.

## 11. Testing the skill

- `run-round.sh --dry-run <run-dir> <N>` assembles and prints the prompt
  without calling Codex. Fixtures: a round-1 run dir and a round-3 run dir
  with ledger, diff, awaited findings and response; assert the marked
  sections, the regenerated What-to-review, the ledger, the awaited blocks,
  the diff and the delta manifest appear, and the round-1-only sections do
  not.
- Failure judgment. The primary fixture is real: the usage-limit event
  stream captured on 2026-09-18 (exit 1, no output file, `error` then
  `turn.failed` events), kept as `fixture-usage-limit.jsonl` in this spec's
  own run dir. The remaining cases are synthetic: exit 0 with no output
  file; exit 0 with an output file older than the prompt; exit 0 with
  invalid JSON. Each must produce a non-zero script exit, the attempt
  files, and a diagnostic.
- `parse-round.sh` against (a) this run's round 1 transcribed to the JSON
  shape — 3 P0, 6 P1, 2 P2 → IDs `R1-F1…R1-F11`, all `open`; (b) synthetic
  delta outputs covering every cell of the §6 transition table, including
  the two violation cells, a missing awaited ID, an unknown ID, a duplicate
  ID, and a non-empty `prior` in round 1.
- Response completeness: a file ending in the bare `## Files changed`
  heading, one with paths but no end marker, one with the marker but no
  heading, and one with a bare path (no `- ` prefix) between heading and
  marker are all incomplete; heading, zero or more `- path` entries, marker
  is complete. Same for `ruling-N.md`, plus: a pending ruling is
  recognised as pending, not as incomplete or absent.
- Commit isolation, in a fixture repo with a pre-staged unrelated file, a
  baseline-dirty file and a clean subject: a round commit must contain
  exactly the allowlist; a `## Files changed` entry naming the
  baseline-dirty file must yield BLOCKED PATH and no commit.
- Resume, in a fixture run dir at each row of the §7.3 table, the two
  post-commit cases (interrupted after the round-10 commit; interrupted
  after a converged round's commit), and the three ruling states (absent,
  pending, complete-uncommitted): the resumed position must match the
  table and the §8 outcome, the user must be asked only in the absent case,
  and no file may be overwritten.
- The schema itself: the probe call from 2026-09-18 (`--output-schema`,
  effort low, no file reads, 4 s) is the smoke test; keep it as
  `probe.sh` in the skill.
- One real end-to-end run before the skill is called done, per
  `superpowers:writing-skills`. Candidate: Plan 2 in the erebor-reverse-design
  worktree, whose round 2 has since completed by hand and whose round 3
  would be the first measured delta round.

## 12. Decisions made during design

| decision | choice | why |
|----------|--------|-----|
| Fixes between rounds | apply and commit per round | Codex reviews a pinned revision; the exchange cites rounds; a crash leaves labelled state. Invoking `/refine` is the standing authorization to commit |
| Disagreement | stop and escalate when Claude rejects and Codex re-raises (no new evidence, or twice); an accepted-but-incomplete fix reopens instead and escalates only at the third miss, with the round after the second miss at round-1 effort | two models can stalemate to the cap, and the user's ruling is cheaper than eight rounds; but the first two real runs showed every stop at "two misses" was an agreed, mostly trivial fix (rev 6) |
| Brief | shown, no wait (rev 7; was "wait for go") | the go was an approval on every run in practice; the printed brief still lets the user interrupt a mis-scoped round 1 |
| Context across rounds | fresh session per round + ledger (approach C) | mechanical termination checks, bounded prompt, any round reproducible from disk |
| Later rounds | delta reviews at lower effort | Codex's cost is re-reading the codebase, not the prompt; a fix review is a diff review |
| Confirm pass | off by default, `--confirm` | round 1 was the full pass; a fix breaking an untouched section is rare; the user chooses per subject |
| Output contract | schema-enforced JSON (`--output-schema`) + typed events (`--json`) | removes the markdown grammar, format-violation and transcript-grepping machinery; probed 2026-09-18 |
| Commit isolation | path-limited commits from an explicit allowlist | the working tree always holds unrelated work; `git add <paths>` alone does not exclude a pre-staged index |

## 13. Deferred

- **Persistent Codex session** (`codex exec resume`) for delta rounds. Would
  avoid re-reading further and benefit from prompt caching, but Codex would
  hold stale file contents across fixes, session state lives outside the
  repo, and it is unknown whether credit accounting discounts cached tokens.
  The session is already kept (not `--ephemeral`) for violation repair, so
  the experiment is cheap when wanted.
- **Parallel response.** Claude's respond-and-fix phase is sequential.
  Findings interact; the phase is Claude-token-bound, not the loop's
  bottleneck.
