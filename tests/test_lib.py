import os, sys, subprocess, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import refine_lib as L

LEDGER = """# Ledger: t

| id | sev | title | status | cycles | note |
|---|---|---|---|---|---|
| R1-F1 | P0 | first | fixed:R1 | 0 | a |
| R1-F2 | P1 | second | rejected | 1 | b |
| R1-F3 | P2 | third | deferred | 0 |  |
| R2-F1 | P1 | fourth | resolved | 0 | c |
"""

def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(text)

class LedgerTest(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ledger.md"); w(p, LEDGER)
            rows = L.read_ledger(p)
            self.assertEqual([r["id"] for r in rows], ["R1-F1", "R1-F2", "R1-F3", "R2-F1"])
            self.assertEqual(rows[1]["cycles"], 1); self.assertEqual(rows[2]["note"], "")
            L.write_ledger(p, rows, "t")
            self.assertEqual(L.read_ledger(p), rows)
    def test_sanitises_pipes_and_newlines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ledger.md")
            rows = [{"id": "R1-F1", "sev": "P1", "title": "bad `| R1-F1 |` title", "status": "open", "cycles": 0,
                     "note": "line one\nline two | with a pipe"}]
            L.write_ledger(p, rows, "t")
            back = L.read_ledger(p)
            self.assertEqual(len(back), 1)
            self.assertEqual(back[0]["title"], "bad `¦ R1-F1 ¦` title")
            self.assertEqual(back[0]["note"], "line one line two ¦ with a pipe")
    def test_awaited(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ledger.md"); w(p, LEDGER)
            self.assertEqual(L.awaited_ids(L.read_ledger(p)), ["R1-F1", "R1-F2"])
    def test_status_predicates(self):
        self.assertTrue(L.is_fixed("fixed:R3")); self.assertTrue(L.is_fixed("fixed:ruling2"))
        self.assertFalse(L.is_fixed("fixed@abc")); self.assertTrue(L.is_valid_status("closed-by-user"))
        self.assertFalse(L.is_valid_status("done")); self.assertTrue(L.terminal("withdrawn")); self.assertFalse(L.terminal("open"))

class RecordStateTest(unittest.TestCase):
    def check(self, text, expect):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.md"); w(p, text); self.assertEqual(L.record_state(p), expect)
    def test_absent(self):
        self.assertEqual(L.record_state("/nonexistent/x.md"), "absent")
    def test_bare_heading(self): self.check("# R\n\n## Files changed\n", "incomplete")
    def test_paths_no_marker(self): self.check("# R\n\n## Files changed\n\n- a/b.md\n", "incomplete")
    def test_marker_no_heading(self): self.check("# R\n\ntext\n\n<!-- end -->\n", "incomplete")
    def test_bare_path(self): self.check("# R\n\n## Files changed\n\na/b.md\n\n<!-- end -->\n", "incomplete")
    def test_complete_zero(self): self.check("# R\n\n## Files changed\n\n<!-- end -->\n", "complete")
    def test_complete(self): self.check("# R\n\n## Files changed\n\n- a/b.md\n- c.py\n\n<!-- end -->\n", "complete")
    def test_pending(self): self.check("# Ruling\n\n- R1-F1: accept\n\n<!-- pending -->\n", "pending")
    def test_files_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.md"); w(p, "# R\n\n## Files changed\n\n- a/b.md\n- c.py\n\n<!-- end -->\n")
            self.assertEqual(L.files_changed(p), ["a/b.md", "c.py"])

class SectionTest(unittest.TestCase):
    LINES = ["# T", "", "## 1. A", "x", "### 1.1 B", "y", "y", "## 2. C", "z"]
    def test_map_and_of(self):
        h = L.section_map(self.LINES)
        self.assertEqual(h, [(3, "## 1. A"), (5, "### 1.1 B"), (8, "## 2. C")])
        self.assertEqual(L.section_of(h, len(self.LINES), 6), (5, 7, "### 1.1 B"))
        self.assertEqual(L.section_of(h, len(self.LINES), 9), (8, 9, "## 2. C"))
        self.assertIsNone(L.section_of(h, len(self.LINES), 1))
    def test_touched(self):
        diff = "@@ -1,2 +6,2 @@\n+y\n@@ -9 +9 @@\n+z\n"
        self.assertEqual(L.touched_sections(diff, L.section_map(self.LINES), len(self.LINES)),
                         [(5, 7, "### 1.1 B"), (8, 9, "## 2. C")])
    def test_touched_hunk_spanning_sections(self):
        diff = "@@ -3,6 +3,7 @@\n"   # new range L3-L9 starts in 1. A and ends in 2. C; the section between is covered too
        self.assertEqual(L.touched_sections(diff, L.section_map(self.LINES), len(self.LINES)),
                         [(3, 4, "## 1. A"), (5, 7, "### 1.1 B"), (8, 9, "## 2. C")])

class RenderTest(unittest.TestCase):
    D = {"verdict": "changes requested",
         "findings": [{"severity": "P1", "title": "t", "claim": "c", "evidence": "e", "why": "w", "fix": "f"}],
         "prior": [{"id": "R1-F1", "result": "resolved", "note": "n"}], "verified": ["v"], "not_verified": []}
    def test_finding_block(self):
        self.assertEqual(L.finding_block(self.D, 2, 1), "### [P1] R2-F1 t\nc · e · w · f")
    def test_render(self):
        out = L.render_review(self.D, 2)
        self.assertTrue(out.startswith("Verdict: changes requested\n"))
        self.assertIn("### [P1] R2-F1 t", out); self.assertIn("- R1-F1: resolved — n", out); self.assertIn("## Not verified\n- (none)", out)

class EffortAndEvaluateTest(unittest.TestCase):
    def rows(self, *specs):
        return [{"id": i, "sev": s, "title": "", "status": st, "cycles": 0, "note": ""} for i, s, st in specs]
    def test_delta_effort(self):
        self.assertEqual([L.delta_effort(e) for e in ("high", "medium", "low")], ["medium", "low", "low"])
    def test_contested_first(self):
        r = self.rows(("R1-F1", "P1", "contested"), ("R2-F1", "P0", "open"))
        self.assertEqual(L.evaluate(r, 2, 10, False, False), "CONTESTED")
    def test_converged(self):
        r = self.rows(("R1-F1", "P1", "resolved"), ("R1-F2", "P2", "deferred"))
        self.assertEqual(L.evaluate(r, 2, 10, False, False), "CONVERGED")
    def test_confirm_only_once_and_under_cap(self):
        r = self.rows(("R1-F1", "P1", "resolved"))
        self.assertEqual(L.evaluate(r, 2, 10, True, False), "CONFIRM")
        self.assertEqual(L.evaluate(r, 2, 10, True, True), "CONVERGED")
        self.assertEqual(L.evaluate(r, 10, 10, True, False), "CONVERGED")
    def test_new_p01_continues_then_cap(self):
        r = self.rows(("R2-F1", "P1", "fixed:R2"))
        self.assertEqual(L.evaluate(r, 2, 10, False, False), "CONTINUE")
        self.assertEqual(L.evaluate(r, 10, 10, False, False), "CAP")

class GitTest(unittest.TestCase):
    def test_run_commits_anchored_to_run_dir(self):
        with tempfile.TemporaryDirectory() as d:
            def g(*a): return subprocess.check_output(["git", "-C", d, *a], text=True).strip()
            g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
            os.makedirs(os.path.join(d, "r/a")); os.makedirs(os.path.join(d, "r/b"))
            w(os.path.join(d, "r/a/brief.md"), "x"); g("add", "-A"); g("commit", "-qm", "refine(t): brief")
            w(os.path.join(d, "r/a/x"), "1"); g("add", "-A"); g("commit", "-qm", "refine(t): round 1 (1 accepted, 0 rejected, 0 deferred)")
            w(os.path.join(d, "r/b/x"), "2"); g("add", "-A"); g("commit", "-qm", "refine(t): round 2 (0 accepted, 0 rejected, 0 deferred)")
            w(os.path.join(d, "r/a/y"), "3"); g("add", "-A"); g("commit", "-qm", "refine(t): ruling after round 1 (R1-F1)")
            c = L.run_commits(d, "r/a", "t")
            self.assertEqual(sorted(c["rounds"]), [1]); self.assertEqual(sorted(c["rulings"]), [1]); self.assertIsNotNone(c["brief"])
            self.assertEqual(L.head(d), g("rev-parse", "--short", "HEAD"))
    def test_committed_ledger_ignores_working_tree(self):
        with tempfile.TemporaryDirectory() as d:
            def g(*a): return subprocess.check_output(["git", "-C", d, *a], text=True).strip()
            g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
            self.assertEqual(L.committed_ledger(d, "r"), [])
            os.makedirs(os.path.join(d, "r")); w(os.path.join(d, "r/ledger.md"), LEDGER); g("add", "-A"); g("commit", "-qm", "x")
            w(os.path.join(d, "r/ledger.md"), LEDGER.replace("fixed:R1", "resolved"))
            self.assertEqual(L.committed_ledger(d, "r")[0]["status"], "fixed:R1")
    def test_porcelain_and_refresh_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            def g(*a): return subprocess.check_output(["git", "-C", d, *a], text=True).strip()
            g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
            w(os.path.join(d, "a.txt"), "a"); g("add", "-A"); g("commit", "-qm", "x")
            w(os.path.join(d, "a.txt"), "a2"); w(os.path.join(d, "k/deep/n.md"), "n"); w(os.path.join(d, "odd -name.txt"), "o")
            self.assertEqual(sorted(L.porcelain_paths(d)), ["a.txt", "k/deep/n.md", "odd -name.txt"])
            run = os.path.join(d, "run"); os.makedirs(run); w(os.path.join(run, "dirty-baseline"), "a.txt\nk/deep/n.md\nodd -name.txt\n")
            g("add", "a.txt"); g("commit", "-qm", "user committed a")
            self.assertEqual(L.refresh_baseline(d, run), ["a.txt"])
            with open(os.path.join(run, "dirty-baseline")) as f: self.assertEqual(f.read().split("\n")[:2], ["k/deep/n.md", "odd -name.txt"])

class RelocateTest(unittest.TestCase):
    def test_relocate_by_title(self):
        old = ["# T", "## A", "x", "## B", "y", "y2", "## C", "z"]
        new = ["# T", "intro", "## A", "x", "## C", "z", "## B", "y", "y2", "y3"]
        self.assertEqual(L.relocate_sections(old, new, [5, 2, 99]), [(3, 4, "## A"), (7, 10, "## B")])
