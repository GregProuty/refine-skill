# /refine

A Claude Code skill that hardens a spec, a plan or a branch by running Codex review rounds until the review converges. Each round, Codex reviews the subject against a brief; Claude verifies every finding against the code, fixes or rejects it, commits, and starts the next round. The loop stops when no P0/P1 finding remains, a finding is contested (you rule on it), the round cap is reached, or Codex fails. Every round, response and ruling is committed under `docs/superpowers/reviews/<date>-<topic>/`, so the review history lives in the repo.

The design, including the ledger, round kinds and stop conditions, is in [`docs/design.md`](docs/design.md). `SKILL.md` refers to its sections by number.

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- The [Codex CLI](https://github.com/openai/codex), installed and logged in. Each round runs `codex exec`. The repository under review must be a trusted project in `~/.codex/config.toml`.
- `python3`, `git`, `bash`
- The [superpowers](https://github.com/obra/superpowers) plugin for Claude Code. The skill uses `superpowers:receiving-code-review` when judging findings.
- For implementation reviews, a verify command for the project (for example `pnpm verify`). The skill asks for one if it doesn't know it.

## Install

```bash
git clone https://github.com/GregProuty/refine-skill.git
bash refine-skill/install.sh    # symlinks ~/.claude/skills/refine to this checkout
bash refine-skill/probe.sh      # optional: checks your codex honours --output-schema and --json
```

`git pull` updates the skill in place.

## Use

In Claude Code:

```
/refine docs/specs/my-feature-design.md
/refine docs/plans/my-feature-plan.md "focus on the migration and the retry paths"
/refine main...HEAD --rounds 6
/refine --resume docs/superpowers/reviews/2026-01-01-my-feature
```

Options: `--rounds N` (round cap), `--effort high|medium|low` (round 1 effort; delta rounds run one tier lower), `--confirm` (a final confirm pass), `--resume <run-dir>`.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
