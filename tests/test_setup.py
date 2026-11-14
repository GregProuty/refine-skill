import json, os, subprocess, tempfile, unittest
HERE = os.path.dirname(__file__)
BIN = os.path.join(HERE, "..", "bin", "setup-run.py")

def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(t)

class Repo:
    def __init__(self):
        self.d = tempfile.mkdtemp(); self.g("init", "-q"); self.g("config", "user.email", "t@t"); self.g("config", "user.name", "t")
        w(os.path.join(self.d, "docs/spec.md"), "s\n"); w(os.path.join(self.d, "src/a.py"), "a\n"); w(os.path.join(self.d, "notes.md"), "n\n")
        self.g("add", "-A"); self.g("commit", "-qm", "base"); self.g("branch", "-M", "main")
    def g(self, *a): return subprocess.check_output(["git", "-C", self.d, *a], text=True).strip()
    def setup(self, *args):
        return subprocess.run(["python3", BIN, "--worktree", self.d, "--topic", "t", "--date", "2026-01-01", *args], capture_output=True, text=True)

class SetupTest(unittest.TestCase):
    def test_creates_run_dir_and_baseline(self):
        r = Repo(); w(os.path.join(r.d, "notes.md"), "n2\n"); w(os.path.join(r.d, "scratch.txt"), "x\n"); w(os.path.join(r.d, "k/deep/n.md"), "nested untracked\n")
        p = r.setup("--subject-kind", "spec", "--subject", "docs/spec.md", "--verify", "true"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout); run = out["run_dir"]
        self.assertTrue(run.endswith("docs/superpowers/reviews/2026-01-01-t")); self.assertEqual(out["dirty_count"], 3)
        with open(os.path.join(run, "dirty-baseline")) as f: self.assertEqual(sorted(f.read().split()), ["k/deep/n.md", "notes.md", "scratch.txt"])
        self.assertEqual(out["head_at_setup"], r.g("rev-parse", "--short", "HEAD"))
        with open(os.path.join(run, ".gitignore")) as f: self.assertIn("!fixture-*.jsonl", f.read())
        with open(os.path.join(run, "run.meta")) as f: meta = dict(l.split("=", 1) for l in f.read().split("\n") if "=" in l)
        self.assertEqual((meta["topic"], meta["subject_kind"], meta["subject"], meta["cap"], meta["effort"], meta["confirm"], meta["verify"]), ("t", "spec", "docs/spec.md", "10", "high", "0", "true"))
        self.assertEqual(meta["head_at_setup"], out["head_at_setup"])
    def test_refuses_staged_index(self):
        r = Repo(); w(os.path.join(r.d, "notes.md"), "n2\n"); r.g("add", "notes.md")
        p = r.setup("--subject-kind", "spec", "--subject", "docs/spec.md"); self.assertEqual(p.returncode, 1); self.assertIn("index", p.stdout)
    def test_refuses_dirty_subject(self):
        r = Repo(); w(os.path.join(r.d, "docs/spec.md"), "changed\n")
        p = r.setup("--subject-kind", "spec", "--subject", "docs/spec.md"); self.assertEqual(p.returncode, 1); self.assertIn("docs/spec.md", p.stdout)
    def test_absolute_subject_is_normalised_to_worktree_relative(self):
        r = Repo(); abs_path = os.path.join(r.d, "docs/spec.md")
        p = r.setup("--subject-kind", "spec", "--subject", abs_path); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout); self.assertEqual(out["subject"], ["docs/spec.md"])
        with open(os.path.join(out["run_dir"], "run.meta")) as f: meta = dict(l.split("=", 1) for l in f.read().split("\n") if "=" in l)
        self.assertEqual(meta["subject"], "docs/spec.md")
    def test_refuses_nonexistent_subject(self):
        r = Repo()
        p = r.setup("--subject-kind", "spec", "--subject", "docs/missing.md"); self.assertEqual(p.returncode, 1); self.assertIn("docs/missing.md", p.stdout)
    def test_refuses_subject_outside_the_worktree(self):
        r = Repo(); outside = tempfile.mkdtemp(); w(os.path.join(outside, "x.md"), "x\n")
        p = r.setup("--subject-kind", "spec", "--subject", os.path.join(outside, "x.md")); self.assertEqual(p.returncode, 1)
    def test_impl_subject_from_diff(self):
        r = Repo(); r.g("checkout", "-qb", "feat"); w(os.path.join(r.d, "src/b.py"), "b\n"); w(os.path.join(r.d, "src/a.py"), "a2\n"); r.g("add", "-A"); r.g("commit", "-qm", "work")
        p = r.setup("--subject-kind", "impl", "--base", "main", "--confirm", "--effort", "medium"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout); self.assertEqual(out["subject"], ["src/a.py", "src/b.py"])
        with open(os.path.join(out["run_dir"], "run.meta")) as f: meta = dict(l.split("=", 1) for l in f.read().split("\n") if "=" in l)
        self.assertEqual((meta["confirm"], meta["effort"], meta["base"]), ("1", "medium", "main"))
    def test_impl_range_with_a_deleted_file_is_accepted(self):
        r = Repo(); r.g("checkout", "-qb", "feat"); r.g("rm", "-q", "src/a.py"); w(os.path.join(r.d, "src/b.py"), "b\n"); r.g("add", "-A"); r.g("commit", "-qm", "delete a, add b")
        p = r.setup("--subject-kind", "impl", "--base", "main"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(json.loads(p.stdout)["subject"], ["src/a.py", "src/b.py"])
    def test_incomplete_run_dir_is_moved_aside_and_publish_is_atomic(self):
        r = Repo(); partial = os.path.join(r.d, "docs/superpowers/reviews/2026-01-01-t"); os.makedirs(partial); w(os.path.join(partial, ".gitignore"), "x\n")
        p = r.setup("--subject-kind", "spec", "--subject", "docs/spec.md"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        run = json.loads(p.stdout)["run_dir"]; self.assertTrue(os.path.exists(os.path.join(run, "run.meta")))
        aside = [d for d in os.listdir(os.path.dirname(run)) if d.startswith("2026-01-01-t.incomplete-")]; self.assertEqual(len(aside), 1)
        self.assertEqual([d for d in os.listdir(os.path.dirname(run)) if ".tmp-" in d], [])
    def test_refuses_existing_run_dir(self):
        r = Repo(); self.assertEqual(r.setup("--subject-kind", "spec", "--subject", "docs/spec.md").returncode, 0)
        p = r.setup("--subject-kind", "spec", "--subject", "docs/spec.md"); self.assertEqual(p.returncode, 1); self.assertIn("exists", p.stdout)
    def test_baseline_keeps_sibling_run_dirs(self):
        r = Repo(); w(os.path.join(r.d, "docs/superpowers/reviews/2026-01-01-t-other/leftover.txt"), "sibling\n")
        p = r.setup("--subject-kind", "spec", "--subject", "docs/spec.md"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout); self.assertEqual(out["dirty_count"], 1)
        with open(os.path.join(out["run_dir"], "dirty-baseline")) as f: baseline = f.read().split()
        self.assertIn("docs/superpowers/reviews/2026-01-01-t-other/leftover.txt", baseline)
