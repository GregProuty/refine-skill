import json, os, shutil, subprocess, tempfile, unittest
HERE = os.path.dirname(__file__)
BIN = os.path.join(HERE, "..", "bin", "assemble-prompt.py")
FIX = os.path.join(HERE, "fixtures")
SPEC_V1 = "# Spec\n\n## 1. Intro\n\nold intro\n\n## 2. Rules\n\nrule a\nrule b\n\n## 3. Tests\n\nt\n"
SPEC_V2 = SPEC_V1.replace("rule b", "rule b\nrule c")

def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(t)

class Repo:
    """Reproduces the real sequence: subject committed (h0) -> brief written citing h0 -> brief committed (h1 = round-1 head) -> fix committed (h2)."""
    def __init__(self, kind="spec"):
        self.d = tempfile.mkdtemp(); self.run = os.path.join(self.d, "docs/superpowers/reviews/2026-01-01-t")
        self.g("init", "-q"); self.g("config", "user.email", "t@t"); self.g("config", "user.name", "t")
        w(os.path.join(self.d, "docs/spec.md"), SPEC_V1); w(os.path.join(self.d, "src/a.py"), "a = 1\n"); self.g("add", "-A"); self.g("commit", "-qm", "subject")
        self.g("branch", "-M", "main")
        if kind == "impl": self.g("checkout", "-qb", "feat")   # impl work lives on a branch off main, as in a real run
        self.h0 = self.g("rev-parse", "--short", "HEAD")
        subject = "docs/spec.md" if kind == "spec" else "src/a.py"
        with open(os.path.join(FIX, "brief.md")) as f: brief = f.read().replace("ROUND1HEAD", self.h0).replace("WORKTREE", self.d)
        w(os.path.join(self.run, "brief.md"), brief)
        w(os.path.join(self.run, "run.meta"), f"topic=t\nsubject_kind={kind}\nsubject={subject}\nworktree={self.d}\nbase=main\ncap=10\neffort=high\nconfirm=0\nhead_at_setup={self.h0}\n")
        self.g("add", "-A"); self.g("commit", "-qm", "refine(t): brief")
        self.h1 = self.g("rev-parse", "--short", "HEAD")
        w(os.path.join(self.run, "round-1.meta"), f"kind=full\nhead={self.h1}\n")
        w(os.path.join(self.run, "round-1.json"), json.dumps({"verdict": "changes requested", "findings": [
            {"severity": "P1", "title": "rules incomplete", "claim": "c", "evidence": "docs/spec.md:L5 and L9, src/a.py:L1", "why": "w", "fix": "f"},
            {"severity": "P2", "title": "minor", "claim": "c2", "evidence": "e2", "why": "w2", "fix": "f2"}], "prior": [], "verified": [], "not_verified": []}))
        w(os.path.join(self.run, "ledger.md"), "# Ledger: t\n\n| id | sev | title | status | cycles | note |\n|---|---|---|---|---|---|\n| R1-F1 | P1 | rules incomplete | fixed:R1 | 0 | n |\n| R1-F2 | P2 | minor | deferred | 0 | n |\n")
        w(os.path.join(self.run, "response-1.md"), "# Round 1 response\n\nfixed R1-F1\n\n## Files changed\n\n- docs/spec.md\n\n<!-- end -->\n")
        w(os.path.join(self.d, "docs/spec.md"), SPEC_V2); w(os.path.join(self.d, "src/a.py"), "a = 2\n"); w(os.path.join(self.d, "tests/test_a.py"), "def test(): pass\n")
        self.g("add", "-A"); self.g("commit", "-qm", "refine(t): round 1 (1 accepted, 0 rejected, 1 deferred)")
    def g(self, *a): return subprocess.check_output(["git", "-C", self.d, *a], text=True).strip()
    def assemble(self, n, kind):
        p = subprocess.run(["python3", BIN, "--run-dir", self.run, "--round", str(n), "--kind", kind], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        with open(os.path.join(self.run, f".prompt-round-{n}.md")) as f: prompt = f.read()
        return json.loads(p.stdout), prompt

class AssembleTest(unittest.TestCase):
    def test_full_is_brief_verbatim(self):
        r = Repo(); out, prompt = r.assemble(1, "full")
        with open(os.path.join(r.run, "brief.md")) as f: expected = f.read()
        self.assertEqual(prompt, expected)
    def test_delta(self):
        r = Repo(); out, prompt = r.assemble(2, "delta")
        h2 = r.g("rev-parse", "--short", "HEAD")
        self.assertEqual(out["prev"], r.h1); self.assertEqual(out["head"], h2); self.assertEqual(out["awaited"], ["R1-F1"])
        self.assertTrue(prompt.startswith("## Role\n"))
        wtr = prompt.split("## What to review", 1)[1].split("## Delta round", 1)[0]
        self.assertIn(f"at commit `{h2}`", wtr); self.assertNotIn(r.h0, wtr); self.assertNotIn(r.h1, wtr)
        self.assertIn("## Delta round 2", prompt); self.assertIn("| R1-F1 | P1 |", prompt)
        self.assertIn("### [P1] R1-F1 rules incomplete\nc · docs/spec.md:L5 and L9, src/a.py:L1 · w · f", prompt); self.assertNotIn("R1-F2 minor", prompt.split("## Awaited")[1].split("## Diff")[0])
        self.assertIn("+rule c", prompt); self.assertNotIn("tests/test_a.py", prompt.split("## Diff")[1].split("## Delta manifest")[0])
        self.assertIn("## Delta manifest", prompt); self.assertIn("docs/spec.md:L7-L12`  ## 2. Rules", prompt)
        self.assertIn("docs/spec.md:L3-L6`  ## 1. Intro (cited by R1-F1)", prompt)
        self.assertEqual(out["touched"], [[7, 12, "## 2. Rules"]]); self.assertEqual(out["cited"], [[3, 6, "## 1. Intro"]])
        self.assertIn("## Constraints\n", prompt); self.assertIn("## Severities\n", prompt); self.assertIn("fixed R1-F1", prompt)
        self.assertIn("and nothing else", prompt)
        self.assertNotIn("## What to check", prompt); self.assertNotIn("## Reading manifest", prompt)
        self.assertNotIn("<!-- reuse -->", prompt)
    def test_citation_refs_are_path_aware(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ap", BIN); ap = importlib.util.module_from_spec(spec); spec.loader.exec_module(ap)
        ev = "docs/spec.md:L5 and L9, src/a.py:L1; plan L40-L44; other.md:L7"
        self.assertEqual(ap.refs_for(ev, "docs/spec.md", primary=True), [5, 9, 40, 44])     # its own refs plus the bare ones
        self.assertEqual(ap.refs_for(ev, "docs/other.md", primary=False), [7])             # basename match, no bare refs
        self.assertEqual(ap.refs_for(ev, "src/a.py", primary=False), [1])
    def test_impl_delta_manifests_a_markdown_file_a_fix_added(self):
        r = Repo(kind="impl"); w(os.path.join(r.d, "docs/new.md"), "# New\n\n## 1. Added\n\nbody\n"); r.g("add", "-A"); r.g("commit", "-qm", "refine(t): round 1 (fix adds a doc)")
        out, prompt = r.assemble(2, "delta")
        self.assertIn("docs/new.md:L3-L6`  ## 1. Added", prompt)
    def test_impl_delta_survives_a_deleted_markdown_file(self):
        r = Repo(kind="impl"); r.g("rm", "-q", "docs/spec.md"); r.g("commit", "-qm", "refine(t): round 1 (fix deletes the spec)")
        out, prompt = r.assemble(2, "delta")
        self.assertIn("deleted file mode", prompt); self.assertNotIn("Section map of `docs/spec.md`", prompt)
    def test_impl_delta_diffs_everything_but_the_run_dir(self):
        r = Repo(kind="impl"); out, prompt = r.assemble(2, "delta")
        diff = prompt.split("## Diff")[1].split("## Delta manifest")[0]
        self.assertIn("tests/test_a.py", diff); self.assertIn("-a = 1", diff); self.assertNotIn("docs/superpowers/reviews", diff)
        self.assertIn("docs/spec.md:L7-L12`  ## 2. Rules", prompt)   # markdown files in the range get section ranges; code files only appear in the diff
    def test_delta_includes_ruling(self):
        r = Repo(); w(os.path.join(r.run, "ruling-1.md"), "# Ruling after round 1\n\n- R1-F1: accept\n\n## Files changed\n\n<!-- end -->\n")
        out, prompt = r.assemble(2, "delta"); self.assertIn("## User's ruling after round 1", prompt); self.assertIn("R1-F1: accept", prompt)
    def test_confirm(self):
        r = Repo(); out, prompt = r.assemble(2, "confirm")
        h2 = r.g("rev-parse", "--short", "HEAD")
        self.assertIn("## What to check", prompt); self.assertIn(f"at commit `{h2}`", prompt); self.assertNotIn(r.h0, prompt.split("## What to check")[0])
        self.assertIn("## Reading manifest\n", prompt); self.assertIn("L7 ## 2. Rules", prompt); self.assertNotIn("L1-L20", prompt)
        self.assertIn("## Ledger", prompt); self.assertIn("## Decided findings", prompt); self.assertIn("R1-F2 minor", prompt)
        self.assertIn("only as a `prior` entry", prompt); self.assertNotIn("and nothing else", prompt)
        self.assertIn("every awaited ID (status `fixed:*` or `rejected`) exactly once", prompt)
    def test_confirm_refuses_when_prior_sentence_is_missing_from_the_brief(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ap", BIN); ap = importlib.util.module_from_spec(spec); spec.loader.exec_module(ap)
        r = Repo()
        with open(os.path.join(r.run, "brief.md")) as f: brief = f.read()
        self.assertIn(ap.PRIOR_SENTENCE, brief)
        with open(os.path.join(r.run, "brief.md"), "w") as f: f.write(brief.replace(ap.PRIOR_SENTENCE, "some other sentence entirely."))
        p = subprocess.run(["python3", BIN, "--run-dir", r.run, "--round", "2", "--kind", "confirm"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("prior", p.stderr.lower())
        self.assertFalse(os.path.exists(os.path.join(r.run, ".prompt-round-2.md")))
    def test_stdout_flag_writes_nothing(self):
        r = Repo(); p = subprocess.run(["python3", BIN, "--run-dir", r.run, "--round", "2", "--kind", "delta", "--stdout"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0); self.assertIn("## Delta round 2", p.stdout); self.assertFalse(os.path.exists(os.path.join(r.run, ".prompt-round-2.md")))
