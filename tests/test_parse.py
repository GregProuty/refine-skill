import json, os, shutil, subprocess, tempfile, unittest
HERE = os.path.dirname(__file__)
BIN = os.path.join(HERE, "..", "bin", "parse-round.py")
FIX = os.path.join(HERE, "fixtures")

def run(run_dir, n, kind):
    p = subprocess.run(["python3", BIN, "--run-dir", run_dir, "--round", str(n), "--kind", kind], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)

def mk(rows, review, n, meta=True):
    """A git repo whose HEAD holds the ledger (parse reads the committed ledger), with round-n.json in the working tree."""
    wt = tempfile.mkdtemp(); d = os.path.join(wt, "docs/superpowers/reviews/2026-01-01-t"); os.makedirs(d)
    g = lambda *a: subprocess.check_output(["git", "-C", wt, *a], text=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    with open(os.path.join(d, "run.meta"), "w") as f: f.write(f"topic=t\nworktree={wt}\n")
    lines = ["# Ledger: t", "", "| id | sev | title | status | cycles | note |", "|---|---|---|---|---|---|"]
    for i, s, st, c in rows: lines.append(f"| {i} | {s} | t | {st} | {c} | n |")
    with open(os.path.join(d, "ledger.md"), "w") as f: f.write("\n".join(lines) + "\n")
    g("add", "-A"); g("commit", "-qm", "refine(t): brief")
    with open(os.path.join(d, f"round-{n}.json"), "w") as f: json.dump(review, f)
    if meta:
        with open(os.path.join(d, f"round-{n}.meta"), "w") as f: f.write("kind=delta\nhead=x\nexit=0\n")
    return d

def review(prior, findings=()):
    return {"verdict": "changes requested", "findings": [{"severity": s, "title": t, "claim": "c", "evidence": "e", "why": "w", "fix": "f"} for s, t in findings],
            "prior": [{"id": i, "result": r, "note": "note"} for i, r in prior], "verified": [], "not_verified": []}

def ledger(d):
    import sys; sys.path.insert(0, os.path.join(HERE, "..", "bin")); import refine_lib
    return {r["id"]: r for r in refine_lib.read_ledger(os.path.join(d, "ledger.md"))}

def meta(d, n):
    with open(os.path.join(d, f"round-{n}.meta")) as f:
        return dict(l.split("=", 1) for l in f.read().split())

class Round1Test(unittest.TestCase):
    def test_fixture_becomes_open_rows(self):
        with open(os.path.join(FIX, "round-1.json")) as f:
            d = mk([], json.load(f), 1)
        rc, out = run(d, 1, "full")
        self.assertEqual(rc, 0); self.assertEqual([x["id"] for x in out["new"]], [f"R1-F{k}" for k in range(1, 12)])
        L = ledger(d); self.assertEqual(len(L), 11); self.assertEqual(L["R1-F3"]["status"], "open"); self.assertEqual(L["R1-F3"]["sev"], "P0")
    def test_round1_prior_must_be_empty(self):
        d = mk([], review([("R1-F1", "resolved")]), 1)
        rc, out = run(d, 1, "full"); self.assertEqual(rc, 2); self.assertIn("prior", out["violations"][0]); self.assertEqual(ledger(d), {})
        self.assertEqual(meta(d, 1)["parse_failed"], "1")
    def test_parse_is_idempotent_and_marks_meta(self):
        d = mk([("R1-F1", "P0", "fixed:R1", 0)], review([("R1-F1", "resolved")], [("P1", "n")]), 2)
        self.assertEqual(run(d, 2, "delta")[0], 0)
        with open(os.path.join(d, "ledger.md")) as f:
            first = f.read()
        self.assertEqual(meta(d, 2)["parsed"], "1"); self.assertNotIn("parse_failed", meta(d, 2))
        self.assertEqual(run(d, 2, "delta")[0], 0)
        with open(os.path.join(d, "ledger.md")) as f:
            self.assertEqual(f.read(), first)

class DeltaTransitionsTest(unittest.TestCase):
    def test_table(self):
        rows = [("R1-F1", "P0", "fixed:R1", 0), ("R1-F2", "P1", "rejected", 0), ("R1-F3", "P1", "fixed:R1", 1), ("R1-F4", "P1", "rejected", 1),
                ("R1-F5", "P1", "fixed:R1", 0), ("R1-F6", "P1", "rejected", 0), ("R1-F7", "P2", "deferred", 0), ("R1-F8", "P1", "fixed:R1", 2)]
        pri = [("R1-F1", "resolved"), ("R1-F2", "withdrawn"), ("R1-F3", "still open"), ("R1-F4", "still open"), ("R1-F5", "still open"), ("R1-F6", "still open"), ("R1-F8", "still open")]
        d = mk(rows, review(pri, [("P1", "new one")]), 2)
        rc, out = run(d, 2, "delta"); self.assertEqual(rc, 0)
        L = ledger(d)
        self.assertEqual(L["R1-F1"]["status"], "resolved"); self.assertEqual(L["R1-F2"]["status"], "withdrawn")
        self.assertEqual((L["R1-F3"]["status"], L["R1-F3"]["cycles"]), ("open", 2))         # second miss on a fix: reopen, not contested
        self.assertEqual((L["R1-F4"]["status"], L["R1-F4"]["cycles"]), ("contested", 2))    # second rejection: disagreement
        self.assertEqual((L["R1-F8"]["status"], L["R1-F8"]["cycles"]), ("contested", 3))    # third miss on a fix: escalate
        self.assertEqual((L["R1-F5"]["status"], L["R1-F5"]["cycles"]), ("open", 1))
        self.assertEqual((L["R1-F6"]["status"], L["R1-F6"]["cycles"]), ("reopened", 1))
        self.assertEqual(L["R1-F7"]["status"], "deferred")
        self.assertEqual(L["R2-F1"]["status"], "open"); self.assertEqual(L["R2-F1"]["title"], "new one")
        self.assertEqual(out["needs_judgment"], ["R1-F6"]); self.assertEqual(sorted(out["contested"]), ["R1-F4", "R1-F8"])
        self.assertEqual(meta(d, 2)["needs_judgment"], "R1-F6")
        self.assertIn("R2 still open: note", L["R1-F5"]["note"])

class ViolationsTest(unittest.TestCase):
    def base(self): return [("R1-F1", "P0", "fixed:R1", 0), ("R1-F2", "P1", "rejected", 0)]
    def check(self, prior, needle):
        d = mk(self.base(), review(prior), 2)
        before = ledger(d); rc, out = run(d, 2, "delta")
        self.assertEqual(rc, 2, out); self.assertTrue(any(needle in v for v in out["violations"]), out); self.assertEqual(ledger(d), before)
    def test_missing_awaited(self): self.check([("R1-F1", "resolved")], "R1-F2")
    def test_unknown_id(self): self.check([("R1-F1", "resolved"), ("R1-F2", "withdrawn"), ("R9-F9", "resolved")], "R9-F9")
    def test_duplicate(self): self.check([("R1-F1", "resolved"), ("R1-F1", "resolved"), ("R1-F2", "withdrawn")], "R1-F1")
    def test_fixed_withdrawn(self): self.check([("R1-F1", "withdrawn"), ("R1-F2", "withdrawn")], "R1-F1")
    def test_rejected_resolved(self): self.check([("R1-F1", "resolved"), ("R1-F2", "resolved")], "R1-F2")

class ConfirmTest(unittest.TestCase):
    def test_decided_rows(self):
        rows = [("R1-F1", "P1", "resolved", 0), ("R1-F2", "P1", "closed-by-user", 2), ("R1-F3", "P2", "deferred", 0), ("R1-F4", "P1", "withdrawn", 1)]
        pri = [("R1-F1", "still open"), ("R1-F2", "still open"), ("R1-F3", "still open"), ("R1-F4", "still open")]
        d = mk(rows, review(pri), 5)
        rc, out = run(d, 5, "confirm"); self.assertEqual(rc, 0, out)
        L = ledger(d)
        self.assertEqual((L["R1-F1"]["status"], L["R1-F1"]["cycles"]), ("open", 1))
        self.assertEqual(L["R1-F2"]["status"], "contested")
        self.assertEqual(L["R1-F3"]["status"], "deferred"); self.assertIn("R5 still open", L["R1-F3"]["note"])
        self.assertEqual((L["R1-F4"]["status"], L["R1-F4"]["cycles"]), ("contested", 2))
        self.assertEqual(out["needs_judgment"], ["R1-F1"])
    def test_decided_resolved_is_noop_and_delta_rejects_decided(self):
        rows = [("R1-F1", "P1", "resolved", 0)]
        d = mk(rows, review([("R1-F1", "resolved")]), 5)
        rc, out = run(d, 5, "confirm"); self.assertEqual(rc, 0); self.assertEqual(ledger(d)["R1-F1"]["status"], "resolved")
        d = mk(rows, review([("R1-F1", "still open")]), 5)
        rc, out = run(d, 5, "delta"); self.assertEqual(rc, 2)

class SetStatusTest(unittest.TestCase):
    SET = os.path.join(HERE, "..", "bin", "set-status.py")
    def go(self, d, *args):
        p = subprocess.run(["python3", self.SET, "--run-dir", d, *args], capture_output=True, text=True); return p.returncode, p.stdout
    def test_set_and_append(self):
        d = mk([("R1-F1", "P0", "open", 0), ("R1-F2", "P1", "open", 1)], review([]), 2)
        rc, out = self.go(d, "--id", "R1-F1", "--id", "R1-F2", "--status", "fixed:R2", "--note", "moved the check to step 3")
        self.assertEqual(rc, 0); self.assertEqual(json.loads(out), {"updated": ["R1-F1", "R1-F2"]})
        L = ledger(d); self.assertEqual((L["R1-F1"]["status"], L["R1-F1"]["note"], L["R1-F2"]["cycles"]), ("fixed:R2", "moved the check to step 3", 1))
        self.assertEqual(self.go(d, "--id", "R1-F2", "--status", "contested", "--append-note", "no new evidence")[0], 0)
        self.assertEqual(ledger(d)["R1-F2"]["note"], "moved the check to step 3; no new evidence")
    def test_rejects_bad_input(self):
        d = mk([("R1-F1", "P0", "open", 0), ("R1-F2", "P2", "open", 0)], review([]), 2)
        self.assertEqual(self.go(d, "--id", "R9-F9", "--status", "rejected")[0], 1)
        self.assertEqual(self.go(d, "--id", "R1-F1", "--status", "done")[0], 1)
        self.assertEqual(self.go(d, "--id", "R1-F2", "--id", "R1-F1", "--status", "deferred")[0], 1)   # P0 in the set: refused atomically
        self.assertEqual(ledger(d)["R1-F1"]["status"], "open"); self.assertEqual(ledger(d)["R1-F2"]["status"], "open")
        self.assertEqual(self.go(d, "--id", "R1-F2", "--status", "deferred")[0], 0); self.assertEqual(ledger(d)["R1-F2"]["status"], "deferred")
