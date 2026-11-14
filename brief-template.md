## Role
<!-- reuse -->

{{role: one paragraph. What the subject is, what it will become (plan, code, a running system), and the standard it must meet, e.g. "an implementation plan for a fund-moving rail that fresh subagents will execute verbatim, so anything left to 'check at execution' is a defect".}}

## What to review

- THE SUBJECT ({{spec|plan|impl}}): `{{subject path or diff range}}` at commit `{{head}}`, worktree `{{worktree}}`, branch `{{branch}}`.
- {{documents it must conform to, with paths; for impl the spec and plan it implements}}
- {{the codebase areas that matter, with paths}}
- The run dir `{{run dir}}/` holds `ledger.md` and every round's output.

## What to check, in priority order

{{checklist:spec}}
1. **Internal contradictions.** Any two sections that cannot both be true as written.
2. **Ambiguity.** Any requirement two implementers would build differently.
3. **Unstated assumptions** about the codebase, the vendor, the operator, or timing.
4. **Missing failure modes and degraded states.** What happens when each dependency fails, is slow, or returns something unexpected.
5. **Untestable acceptance criteria.** Any criterion with no observable check.
6. **Interfaces described that the codebase does not have.** Verify against the source.
{{/checklist:spec}}
{{checklist:plan}}
1. **Executability against the actual branch.** For every interface the plan consumes (methods, signatures, types, schemas, helpers, exports), grep the source and confirm it exists with the assumed shape. A task that would fail to compile or import as written is a P1.
2. **Spec conformance.** Where the plan deviates from the spec, is the deviation stated and justified?
3. **Task ordering and dependencies.** Does any task consume something a later task produces?
4. **Test adequacy.** Can the tests the plan writes pass against the helpers that exist, and do they cover the risky paths?
{{/checklist:plan}}
{{checklist:impl}}
1. **Correctness against the spec/plan.** Every behaviour the plan promised, present and right.
2. **The invariants named in the focus notes below.** Each one, traced through the diff.
3. **`tsc --noEmit` clean** (run it); lint if the project has it.
4. **Test adequacy** for the risky paths, and whether the tests actually exercise the diff.
5. **Anything the plan said to do that the diff does not.**
{{/checklist:impl}}
{{focus: the user's focus notes, then Claude's own low-confidence list from the session, each as a numbered item continuing the list}}

## Reading manifest

{{manifest: one line per file or range, as `path:L<a>-L<b>` with what it is for; for impl the `--name-only` file list of the diff plus the spec/plan}}

Read by range (`sed -n`), not whole files. Do not `ls` or explore beyond this manifest unless a finding requires it, and say so under `not_verified` if you do.

## Constraints
<!-- reuse -->

- Read-only. Do not modify any file. Do not run `codex`. {{allowed commands, e.g. `cat`, `sed`, `grep`, `git log/show/diff`, `tsc --noEmit`}} are fine. Never run the Jest suite (it can hang).
- Do not read `.env*`, `secrets/`, `node_modules/`, `.pnpm-store/`, or any credential or key file.
- Be specific. Every finding's `evidence` cites the subject by line (`spec L<n>`, `plan L<n>`, or `file:L<n>` for code) and, where the claim is about the codebase, the source file and line. No generic advice.

## Fixed decisions
<!-- reuse -->

These were made by {{user}} and are not up for reversal. Flag a violation of one; do not propose replacing it.

{{fixed decisions, one per line, or "- None."}}

## Output format (strict)
<!-- reuse -->

Your final message is validated against a JSON Schema; it must be a single JSON object and nothing else:

```
{ "verdict":      "changes requested" | "ready with P2s" | "ready",
  "findings":     [ { "severity": "P0"|"P1"|"P2"|"P3", "title": "<one line>",
                      "claim": "<what is wrong>", "evidence": "<subject L<n>, file:L<n>>",
                      "why": "<why it matters>", "fix": "<concrete fix>" } ],
  "prior":        [ { "id": "R<N>-F<k>", "result": "resolved" | "withdrawn" | "still open",
                      "note": "<for still open: what is still wrong, with new evidence>" } ],
  "verified":     [ "<what you checked and found correct, with citations>" ],
  "not_verified": [ "<what you could not verify and why>" ] }
```

Findings ordered by severity then importance. Do not invent IDs; new findings have no ID (the responder assigns `R<N>-F<k>` in array order). `prior` lists exactly the awaited IDs given to you, once each, and nothing else. In round 1 `prior` is empty.

## Severities
<!-- reuse -->

- **P0**: {{what P0 means for this subject, e.g. "funds can move wrongly, twice, or become unrecoverable, or the plan is unexecutable as a whole"}}
- **P1**: {{e.g. "a task will fail at execution (tsc, missing interface, wrong signature), a rule is ambiguous in a way two implementers would build differently, or a case hit in ordinary use is unhandled"}}
- **P2**: should fix, not blocking.
- **P3**: nit.

At most 12 findings; prefer fewer verified ones over many speculative ones. If you are unsure whether something is a problem, put it under `not_verified` rather than inventing a finding.
