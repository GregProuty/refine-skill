import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(__file__)
BIN = os.path.join(HERE, "..", "bin", "render-exchange.py")

def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(t)

class RenderExchangeTest(unittest.TestCase):
    def test_order_and_content(self):
        d = tempfile.mkdtemp()
        w(os.path.join(d, "run.meta"), "topic=t\nsubject_kind=spec\nsubject=docs/spec.md\nworktree=/x\n")
        rv = lambda v, f: json.dumps({"verdict": v, "findings": f, "prior": [], "verified": ["ok"], "not_verified": []})
        w(os.path.join(d, "round-1.json"), rv("changes requested", [{"severity": "P1", "title": "one", "claim": "c", "evidence": "e", "why": "w", "fix": "f"}]))
        w(os.path.join(d, "round-1.meta"), "kind=full\nhead=abc1234\neffort=high\nduration_s=401\ninput_tokens=50000\ncached_input_tokens=0\noutput_tokens=4000\nexit=0\n")
        w(os.path.join(d, "response-1.md"), "# Round 1 response\n\nfixed\n\n## Files changed\n\n- docs/spec.md\n\n<!-- end -->\n")
        w(os.path.join(d, "ruling-1.md"), "# Ruling after round 1\n\n- R1-F1: accept\n\n## Files changed\n\n<!-- end -->\n")
        w(os.path.join(d, "round-2.json"), rv("ready", []))
        w(os.path.join(d, "round-2.meta"), "kind=delta\nhead=def5678\neffort=medium\nduration_s=63\ninput_tokens=88000\ncached_input_tokens=31000\noutput_tokens=2300\nexit=0\n")
        w(os.path.join(d, ".round-2.attempt1.meta"), "kind=delta\nhead=def5678\nexit=1\n")
        p = subprocess.run(["python3", BIN, "--run-dir", d], capture_output=True, text=True); self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {"rounds": 2})
        with open(os.path.join(d, "exchange.md")) as f: x = f.read()
        i = [x.index(s) for s in ("# Codex review exchange: t", "# Round 1 (full, reviewing abc1234, effort high, 401 s, 50000 in / 0 cached / 4000 out)",
                                   "### [P1] R1-F1 one", "# Round 1 response", "# Ruling after round 1", "# Round 2 (delta, reviewing def5678, effort medium, 63 s, 88000 in / 31000 cached / 2300 out; 1 failed attempt)", "Verdict: ready")]
        self.assertEqual(i, sorted(i))

class RoundSummaryTest(unittest.TestCase):
    SUM = os.path.join(HERE, "..", "bin", "round-summary.py")
    def repo(self):
        d = tempfile.mkdtemp(); run = os.path.join(d, "docs/superpowers/reviews/2026-01-01-t"); os.makedirs(run)
        g = lambda *a: subprocess.check_output(["git", "-C", d, *a], text=True).strip()
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        w(os.path.join(run, "run.meta"), f"topic=t\nsubject_kind=spec\nsubject=docs/spec.md\nworktree={d}\ncap=10\n")
        w(os.path.join(run, "brief.md"), "b"); g("add", "-A"); g("commit", "-qm", "refine(t): brief")
        rv = {"verdict": "changes requested", "findings": [{"severity": "P1", "title": "new one", "claim": "c", "evidence": "e", "why": "w", "fix": "f"},
                                                           {"severity": "P2", "title": "small", "claim": "c", "evidence": "e", "why": "w", "fix": "f"}],
              "prior": [{"id": "R1-F1", "result": "resolved", "note": "ok"}, {"id": "R1-F2", "result": "still open", "note": "still"}], "verified": [], "not_verified": []}
        w(os.path.join(run, "round-2.json"), json.dumps(rv))
        w(os.path.join(run, "round-2.meta"), "kind=delta\nhead=abc1234\neffort=medium\nduration_s=77\ninput_tokens=90000\ncached_input_tokens=50000\noutput_tokens=3000\nreasoning_output_tokens=2000\nexit=0\nrepair_duration_s=10\nrepair_input_tokens=5000\nrepair_cached_input_tokens=0\nrepair_output_tokens=500\nrepair_reasoning_output_tokens=100\n")
        w(os.path.join(run, "round-1.meta"), "kind=full\nhead=aaa\neffort=high\nduration_s=400\ninput_tokens=50000\ncached_input_tokens=0\noutput_tokens=4000\nreasoning_output_tokens=3000\nexit=0\n")
        w(os.path.join(run, ".round-2.attempt1.meta"), "kind=delta\nhead=abc1234\nexit=1\nduration_s=3\ninput_tokens=\n")
        w(os.path.join(run, ".round-2.attempt2.meta"), "kind=repair\nhead=abc1234\nthread_id=t\nrepair_exit=1\nrepair_duration_s=5\nrepair_input_tokens=2000\nrepair_cached_input_tokens=0\nrepair_output_tokens=0\nrepair_reasoning_output_tokens=0\n")
        w(os.path.join(run, "ledger.md"), "# Ledger: t\n\n| id | sev | title | status | cycles | note |\n|---|---|---|---|---|---|\n"
          "| R1-F1 | P0 | first | resolved | 0 | n |\n| R1-F2 | P1 | second | contested | 2 | n |\n| R2-F1 | P1 | new one | fixed:R2 | 0 | n |\n| R2-F2 | P2 | small | deferred | 0 | n |\n")
        g("add", "-A"); g("commit", "-qm", "refine(t): round 2 (1 accepted, 0 rejected, 1 deferred)")
        return d, run, g
    def test_block(self):
        d, run, g = self.repo()
        p = subprocess.run(["python3", self.SUM, "--run-dir", run, "--round", "2"], capture_output=True, text=True); self.assertEqual(p.returncode, 0, p.stderr)
        b = p.stdout; h = g("rev-parse", "--short", "HEAD")
        self.assertIn("round 2/10 · delta t · rev abc1234 · codex 1m27s · 99k tok (50k cached)", b)   # 77+10 s; 95000+3500 tokens, repair included
        self.assertIn("Verdict  changes requested", b)
        self.assertIn("P1 R2-F1  new one", b); self.assertIn("fixed", b.split("R2-F1")[1].split("\n")[0])
        self.assertIn("P2 R2-F2  small", b); self.assertIn("deferred", b.split("R2-F2")[1].split("\n")[0])
        self.assertIn("R1-F1 P0 ✓", b); self.assertIn("R1-F2 P1 ⚠ still open (cycles 2) → CONTESTED", b)
        self.assertIn(f"Commit   {h}  refine(t): round 2 (1 accepted, 0 rejected, 1 deferred)", b)
        self.assertIn("Status   STOPPING — CONTESTED", b)
    def test_totals(self):
        d, run, g = self.repo()
        p = subprocess.run(["python3", self.SUM, "--run-dir", run, "--totals"], capture_output=True, text=True); self.assertEqual(p.returncode, 0, p.stderr)
        t = json.loads(p.stdout)
        self.assertEqual((t["rounds"], t["failed_attempts"], t["duration_s"]), (2, 2, 495))   # a failed round attempt and a failed repair turn
        self.assertEqual((t["input_tokens"], t["cached_input_tokens"], t["output_tokens"], t["reasoning_output_tokens"]), (147000, 50000, 7500, 5100))
        self.assertEqual(t["by_status"], {"resolved": 1, "contested": 1, "fixed:R2": 1, "deferred": 1})
    def test_status_continue_and_effort_bump(self):
        d, run, g = self.repo()
        sys_path = os.path.join(HERE, "..", "bin")
        sys.path.insert(0, sys_path)
        import refine_lib as L
        rows = [{"id": "R1-F1", "sev": "P0", "title": "first", "status": "resolved", "cycles": 0, "note": "n"},
                {"id": "R1-F2", "sev": "P1", "title": "second", "status": "resolved", "cycles": 0, "note": "n"},
                {"id": "R2-F1", "sev": "P1", "title": "new one", "status": "fixed:R2", "cycles": 0, "note": "n"},
                {"id": "R2-F2", "sev": "P2", "title": "small", "status": "deferred", "cycles": 0, "note": "n"}]
        L.write_ledger(os.path.join(run, "ledger.md"), rows, "t")
        g("add", "-A"); g("commit", "-qm", "refine(t): round 2 (1 accepted, 0 rejected, 1 deferred)")
        p = subprocess.run(["python3", self.SUM, "--run-dir", run, "--round", "2"], capture_output=True, text=True); self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Status   CONTINUING → round 3 (delta, effort medium)", p.stdout)
        rows[2]["cycles"] = 2   # a fixed:R2 row missed twice and fixed again: bump
        L.write_ledger(os.path.join(run, "ledger.md"), rows, "t")
        g("add", "-A"); g("commit", "-qm", "refine(t): updated ledger")
        p = subprocess.run(["python3", self.SUM, "--run-dir", run, "--round", "2"], capture_output=True, text=True); self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Status   CONTINUING → round 3 (delta, effort high)", p.stdout)
