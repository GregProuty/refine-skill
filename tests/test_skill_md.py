import os, re, unittest
ROOT = os.path.join(os.path.dirname(__file__), "..")

class SkillMdTest(unittest.TestCase):
    def test_frontmatter_and_script_references(self):
        with open(os.path.join(ROOT, "SKILL.md")) as f:
            t = f.read()
        self.assertTrue(t.startswith("---\nname: refine\ndescription: "))
        for s in ("setup-run.py", "run-round.sh", "parse-round.py", "set-status.py", "commit-round.sh", "resume-position.py", "render-exchange.py", "round-summary.py"):
            self.assertIn(s, t, s)
        for phrase in ("wait for the user", "receiving-code-review", "<!-- pending -->", "BLOCKED PATH", "CONTESTED", "CONVERGED", "repair_exit", "released"):
            self.assertIn(phrase, t, phrase)
        self.assertNotIn("<<'PY'", t)   # no heredocs with unexpanded $SKILL/$RUN
        for gone in ("Wait for the user's go", "wait for the go", "brief gate"):
            self.assertNotIn(gone, t, gone)   # the brief go gate was removed
