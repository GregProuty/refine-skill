import os, subprocess, tempfile, unittest
HERE = os.path.dirname(__file__)
BIN = os.path.join(HERE, "..", "bin", "commit-round.sh")

def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(t)

class Repo:
    def __init__(self):
        self.d = tempfile.mkdtemp(); self.rel = "docs/superpowers/reviews/2026-01-01-t"; self.run = os.path.join(self.d, self.rel)
        self.g("init", "-q"); self.g("config", "user.email", "t@t"); self.g("config", "user.name", "t")
        w(os.path.join(self.d, "docs/spec.md"), "v1\n"); w(os.path.join(self.d, "other.txt"), "o\n"); w(os.path.join(self.d, "dirty.txt"), "d\n")
        w(os.path.join(self.run, "run.meta"), f"topic=t\nsubject_kind=spec\nsubject=docs/spec.md\nworktree={self.d}\n")
        w(os.path.join(self.run, ".gitignore"), "*.jsonl\n.round-*.attempt*\n!fixture-*.jsonl\n")
        w(os.path.join(self.run, "dirty-baseline"), "dirty.txt\n")
        self.g("add", "-A"); self.g("commit", "-qm", "base")
        w(os.path.join(self.d, "dirty.txt"), "d2\n")                      # baseline-dirty, unstaged
        w(os.path.join(self.d, "other.txt"), "o2\n"); self.g("add", "other.txt")  # pre-staged unrelated
        w(os.path.join(self.d, "docs/spec.md"), "v2\n")                   # the fix
        w(os.path.join(self.run, "ledger.md"), "# Ledger: t\n"); w(os.path.join(self.run, ".codex-round-2.jsonl"), "ignored\n")
    def g(self, *a): return subprocess.check_output(["git", "-C", self.d, *a], text=True).rstrip("\n")
    def run_(self, *args):
        return subprocess.run(["bash", BIN, "--run-dir", self.run, *args], capture_output=True, text=True)
    def files_in_head(self): return set(self.g("show", "--name-only", "--format=", "HEAD").splitlines())

class CommitTest(unittest.TestCase):
    def test_round_commit_is_path_limited(self):
        r = Repo(); w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- docs/spec.md\n\n<!-- end -->\n")
        p = r.run_("--kind", "round", "--round", "2", "--summary", "1 accepted, 0 rejected, 0 deferred")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(r.g("log", "-1", "--format=%s"), "refine(t): round 2 (1 accepted, 0 rejected, 0 deferred)")
        self.assertEqual(r.files_in_head(), {"docs/spec.md", f"{r.rel}/response-2.md", f"{r.rel}/ledger.md"})
        self.assertIn("M  other.txt", r.g("status", "--porcelain"))   # still staged, untouched
        self.assertIn(" M dirty.txt", r.g("status", "--porcelain"))   # still dirty, untouched
        self.assertEqual(p.stdout.strip(), r.g("rev-parse", "--short", "HEAD"))
    def test_blocked_path(self):
        r = Repo(); w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- docs/spec.md\n- dirty.txt\n\n<!-- end -->\n")
        before = r.g("rev-parse", "HEAD"); p = r.run_("--kind", "round", "--round", "2", "--summary", "s")
        self.assertEqual(p.returncode, 3); self.assertIn("BLOCKED PATH dirty.txt", p.stdout); self.assertEqual(r.g("rev-parse", "HEAD"), before)
    def test_incomplete_record_refused(self):
        r = Repo(); w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- docs/spec.md\n")
        before = r.g("rev-parse", "HEAD"); p = r.run_("--kind", "round", "--round", "2", "--summary", "s")
        self.assertEqual(p.returncode, 1); self.assertIn("incomplete", p.stdout); self.assertEqual(r.g("rev-parse", "HEAD"), before)
    def test_ruling_commit(self):
        r = Repo(); w(os.path.join(r.run, "ruling-2.md"), "# Ruling\n\n- R1-F1: accept\n\n## Files changed\n\n- docs/spec.md\n\n<!-- end -->\n")
        p = r.run_("--kind", "ruling", "--round", "2", "--ids", "R1-F1"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(r.g("log", "-1", "--format=%s"), "refine(t): ruling after round 2 (R1-F1)"); self.assertIn("docs/spec.md", r.files_in_head())
    def test_pending_ruling_refused(self):
        r = Repo(); w(os.path.join(r.run, "ruling-2.md"), "# Ruling\n\n- R1-F1: accept\n\n<!-- pending -->\n")
        p = r.run_("--kind", "ruling", "--round", "2", "--ids", "R1-F1"); self.assertEqual(p.returncode, 1); self.assertIn("pending", p.stdout)
    def test_zero_entry_response_commits_run_dir_only(self):
        r = Repo(); w(os.path.join(r.run, "response-2.md"), "# R\n\nall rejected\n\n## Files changed\n\n<!-- end -->\n")
        p = r.run_("--kind", "round", "--round", "2", "--summary", "0 accepted, 2 rejected, 0 deferred"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(r.files_in_head(), {f"{r.rel}/response-2.md", f"{r.rel}/ledger.md"}); self.assertIn(" M docs/spec.md", r.g("status", "--porcelain"))
    def test_nested_untracked_baseline_path_is_blocked(self):
        r = Repo(); w(os.path.join(r.run, "dirty-baseline"), "dirty.txt\nk/deep/n.md\n"); w(os.path.join(r.d, "k/deep/n.md"), "user work\n")
        w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- k/deep/n.md\n\n<!-- end -->\n")
        p = r.run_("--kind", "round", "--round", "2", "--summary", "s"); self.assertEqual(p.returncode, 3); self.assertIn("BLOCKED PATH k/deep/n.md", p.stdout)
    def test_directory_entry_is_rejected_even_when_baseline_would_have_missed_it(self):
        r = Repo(); w(os.path.join(r.run, "dirty-baseline"), "dirty.txt\nk/deep/user-work.md\n"); w(os.path.join(r.d, "k/deep/user-work.md"), "user work\n")
        w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- k/deep\n\n<!-- end -->\n")
        before = r.g("rev-parse", "HEAD"); p = r.run_("--kind", "round", "--round", "2", "--summary", "s")
        self.assertEqual(p.returncode, 1); self.assertIn("directory", p.stdout); self.assertEqual(r.g("rev-parse", "HEAD"), before)
    def test_baseline_prefix_still_blocks_the_exact_file(self):
        r = Repo(); w(os.path.join(r.run, "dirty-baseline"), "dirty.txt\nk/deep/user-work.md\n"); w(os.path.join(r.d, "k/deep/user-work.md"), "user work\n")
        w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- k/deep/user-work.md\n\n<!-- end -->\n")
        before = r.g("rev-parse", "HEAD"); p = r.run_("--kind", "round", "--round", "2", "--summary", "s")
        self.assertEqual(p.returncode, 3); self.assertIn("BLOCKED PATH k/deep/user-work.md", p.stdout); self.assertEqual(r.g("rev-parse", "HEAD"), before)
    def test_dotslash_and_dotdot_entries_are_rejected(self):
        r = Repo(); w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- ./docs/spec.md\n\n<!-- end -->\n")
        before = r.g("rev-parse", "HEAD"); p = r.run_("--kind", "round", "--round", "2", "--summary", "s")
        self.assertEqual(p.returncode, 1); self.assertIn("./docs/spec.md", p.stdout); self.assertEqual(r.g("rev-parse", "HEAD"), before)
        r2 = Repo(); w(os.path.join(r2.run, "response-2.md"), "# R\n\n## Files changed\n\n- docs/../secrets.txt\n\n<!-- end -->\n")
        before2 = r2.g("rev-parse", "HEAD"); p2 = r2.run_("--kind", "round", "--round", "2", "--summary", "s")
        self.assertEqual(p2.returncode, 1); self.assertIn("..", p2.stdout); self.assertEqual(r2.g("rev-parse", "HEAD"), before2)
    def test_missing_dirty_baseline_refuses_to_commit(self):
        r = Repo(); os.remove(os.path.join(r.run, "dirty-baseline"))
        w(os.path.join(r.run, "response-2.md"), "# R\n\n## Files changed\n\n- docs/spec.md\n\n<!-- end -->\n")
        before = r.g("rev-parse", "HEAD"); p = r.run_("--kind", "round", "--round", "2", "--summary", "s")
        self.assertEqual(p.returncode, 1); self.assertIn("dirty-baseline", p.stdout); self.assertEqual(r.g("rev-parse", "HEAD"), before)
    def test_pathspec_magic_and_globs_are_rejected(self):
        for entry in (":(top)dirty.txt", "docs/*.md", "/docs/spec.md", "docs/./spec.md"):
            r = Repo(); w(os.path.join(r.run, "response-2.md"), f"# R\n\n## Files changed\n\n- {entry}\n\n<!-- end -->\n")
            before = r.g("rev-parse", "HEAD"); p = r.run_("--kind", "round", "--round", "2", "--summary", "s")
            self.assertEqual(p.returncode, 1, entry); self.assertIn("no commit made", p.stdout, entry); self.assertEqual(r.g("rev-parse", "HEAD"), before, entry)
    def test_brief_commit_is_run_dir_only(self):
        r = Repo(); w(os.path.join(r.run, "brief.md"), "b\n")
        p = r.run_("--kind", "brief"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(r.g("log", "-1", "--format=%s"), "refine(t): brief"); self.assertNotIn("docs/spec.md", r.files_in_head())
        self.assertNotIn(".codex-round-2.jsonl", " ".join(r.files_in_head()))


FAKE_PRETTIER = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_PRETTIER_LOG"], "a") as f: f.write(os.getcwd() + "|" + " ".join(args) + "\\n")
if os.environ.get("FAKE_PRETTIER_FAIL"): sys.exit(2)
for p in [a for a in args if a.endswith(".json")]:
    d = json.load(open(p)); open(p, "w").write(json.dumps(d, indent=2) + "\\n")
"""

class FormatTest(unittest.TestCase):
    """Round JSON is formatted with the repo's prettier before staging, so a repo-wide format check passes."""
    def setUp(self):
        self.r = Repo(); self.log = os.path.join(self.r.d, "..", os.path.basename(self.r.d) + ".prettier.log")
        os.environ["FAKE_PRETTIER_LOG"] = self.log; os.environ.pop("FAKE_PRETTIER_FAIL", None)
        w(os.path.join(self.r.run, "round-2.json"), '{"verdict":"ready","findings":[]}')
        w(os.path.join(self.r.run, "response-2.md"), "# R\n\n## Files changed\n\n<!-- end -->\n")
    def tearDown(self): os.environ.pop("FAKE_PRETTIER_FAIL", None)
    def prettier(self, script='"format:check": "prettier --config config/.prettierrc --ignore-path config/.prettierignore --check ."'):
        b = os.path.join(self.r.d, "node_modules", ".bin", "prettier"); w(b, FAKE_PRETTIER); os.chmod(b, 0o755)
        w(os.path.join(self.r.d, "package.json"), '{"scripts": {' + script + '}}')
    def commit(self): return self.r.run_("--kind", "round", "--round", "2", "--summary", "s")
    def committed_json(self): return self.r.g("show", f"HEAD:{self.r.rel}/round-2.json")
    def calls(self): return open(self.log).read().splitlines() if os.path.exists(self.log) else []

    def test_round_json_formatted_with_detected_config(self):
        self.prettier(); p = self.commit(); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.committed_json(), '{\n  "verdict": "ready",\n  "findings": []\n}')
        [call] = self.calls(); cwd, args = call.split("|")
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(self.r.d))
        self.assertTrue(args.startswith("--config config/.prettierrc --write "), args)
        self.assertTrue(args.endswith("round-2.json"), args)
    def test_no_config_in_script_lets_prettier_discover(self):
        self.prettier('"fmt": "prettier --check ."'); p = self.commit(); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        [call] = self.calls(); self.assertTrue(call.split("|")[1].startswith("--write "))
    def test_no_prettier_installed_commits_unformatted(self):
        p = self.commit(); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.committed_json(), '{"verdict":"ready","findings":[]}')
    def test_meta_format_empty_disables(self):
        self.prettier(); w(os.path.join(self.r.run, "run.meta"), open(os.path.join(self.r.run, "run.meta")).read() + "format=\n")
        p = self.commit(); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.calls(), []); self.assertEqual(self.committed_json(), '{"verdict":"ready","findings":[]}')
    def test_meta_format_overrides_detection(self):
        self.prettier(); w(os.path.join(self.r.run, "run.meta"), open(os.path.join(self.r.run, "run.meta")).read() + "format=node_modules/.bin/prettier --write\n")
        p = self.commit(); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        [call] = self.calls(); self.assertTrue(call.split("|")[1].startswith("--write "))
    def test_format_failure_refuses_commit(self):
        self.prettier(); os.environ["FAKE_PRETTIER_FAIL"] = "1"; before = self.r.g("rev-parse", "HEAD")
        p = self.commit(); self.assertEqual(p.returncode, 1); self.assertIn("format", p.stdout); self.assertEqual(self.r.g("rev-parse", "HEAD"), before)
