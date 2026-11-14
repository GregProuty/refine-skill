import json, os, subprocess, tempfile, time, unittest
HERE = os.path.dirname(__file__)
BIN = os.path.join(HERE, "..", "bin", "resume-position.py")

def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(t)

class Repo:
    def __init__(self, cap=10, confirm=0):
        self.d = tempfile.mkdtemp(); self.rel = "docs/superpowers/reviews/2026-01-01-t"; self.run = os.path.join(self.d, self.rel)
        self.g("init", "-q"); self.g("config", "user.email", "t@t"); self.g("config", "user.name", "t")
        w(os.path.join(self.run, "run.meta"), f"topic=t\nsubject_kind=spec\nsubject=docs/spec.md\nworktree={self.d}\ncap={cap}\neffort=high\nconfirm={confirm}\n")
        w(os.path.join(self.run, "brief.md"), "b"); self.commit("refine(t): brief")
    def g(self, *a): return subprocess.check_output(["git", "-C", self.d, *a], text=True).strip()
    def commit(self, msg): self.g("add", "-A"); self.g("commit", "-qm", msg)
    def ledger(self, *rows):
        lines = ["# Ledger: t", "", "| id | sev | title | status | cycles | note |", "|---|---|---|---|---|---|"] + [f"| {i} | {s} | t | {st} | 0 | n |" for i, s, st in rows]
        w(os.path.join(self.run, "ledger.md"), "\n".join(lines) + "\n")
    def round_done(self, n, *rows, kind="delta"):
        self.ledger(*rows); w(os.path.join(self.run, f"round-{n}.meta"), f"kind={kind}\nhead=x\nexit=0\nparsed=1\n")
        w(os.path.join(self.run, f"round-{n}.json"), "{}"); w(os.path.join(self.run, f"response-{n}.md"), "# r\n\n## Files changed\n\n<!-- end -->\n")
        self.commit(f"refine(t): round {n} (0 accepted, 0 rejected, 0 deferred)")
    def pos(self):
        p = subprocess.run(["python3", BIN, "--run-dir", self.run], capture_output=True, text=True); assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)

class ResumeTest(unittest.TestCase):
    def test_fresh_run_starts_round_1(self):
        r = Repo(); p = r.pos()
        self.assertEqual((p["n_done"], p["outcome"], p["next_round"], p["next_kind"], p["phase"]), (0, None, 1, "full", "assemble"))
    def test_continue_to_delta(self):
        r = Repo(); r.round_done(1, ("R1-F1", "P1", "fixed:R1"), kind="full"); p = r.pos()
        self.assertEqual((p["n_done"], p["outcome"], p["next_round"], p["next_kind"], p["phase"]), (1, "CONTINUE", 2, "delta", "assemble"))
    def test_phases_within_round(self):
        r = Repo(); r.round_done(1, ("R1-F1", "P1", "fixed:R1"), kind="full")
        w(os.path.join(r.run, ".prompt-round-2.md"), "p"); self.assertEqual(r.pos()["phase"], "run")
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=1\n"); self.assertEqual(r.pos()["phase"], "run")
        time.sleep(0.01); w(os.path.join(r.run, "round-2.json"), '{"verdict":"ready","findings":[],"prior":[],"verified":[],"not_verified":[]}')
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\n"); self.assertEqual(r.pos()["phase"], "parse")
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nparsed=1\n"); self.assertEqual(r.pos()["phase"], "respond")
        w(os.path.join(r.run, "response-2.md"), "# r\n\n## Files changed\n"); self.assertEqual(r.pos()["phase"], "respond")
        w(os.path.join(r.run, "response-2.md"), "# r\n\n## Files changed\n\n<!-- end -->\n"); self.assertEqual(r.pos()["phase"], "verify-commit")
    def test_stale_or_equal_output_means_rerun(self):
        r = Repo(); r.round_done(1, ("R1-F1", "P1", "fixed:R1"), kind="full")
        w(os.path.join(r.run, "round-2.json"), "{}"); w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\n")
        time.sleep(0.01); w(os.path.join(r.run, ".prompt-round-2.md"), "p"); self.assertEqual(r.pos()["phase"], "run")
        t = os.stat(os.path.join(r.run, ".prompt-round-2.md")).st_mtime_ns; os.utime(os.path.join(r.run, "round-2.json"), ns=(t, t))
        self.assertEqual(r.pos()["phase"], "run")   # equal timestamps are not "newer"
        os.utime(os.path.join(r.run, "round-2.json"), ns=(t + 1, t + 1)); self.assertEqual(r.pos()["phase"], "parse")
    def test_ruling_states(self):
        r = Repo(); r.round_done(1, ("R1-F1", "P1", "contested"), kind="full")
        self.assertEqual((r.pos()["outcome"], r.pos()["ruling"], r.pos()["phase"]), ("CONTESTED", "absent", "ask-ruling"))
        w(os.path.join(r.run, "ruling-1.md"), "# Ruling\n\n- R1-F1: accept\n\n<!-- pending -->\n"); self.assertEqual(r.pos()["phase"], "apply-ruling")
        w(os.path.join(r.run, "ruling-1.md"), "# Ruling\n\n- R1-F1: accept\n\n## Files changed\n\n<!-- end -->\n"); self.assertEqual(r.pos()["phase"], "commit-ruling")
    def test_converged_stops_and_confirm_schedules(self):
        r = Repo(); r.round_done(2, ("R1-F1", "P1", "resolved"), kind="delta"); p = r.pos()
        self.assertEqual((p["outcome"], p["phase"]), ("CONVERGED", "stop"))
        r = Repo(confirm=1); r.round_done(2, ("R1-F1", "P1", "resolved"), kind="delta"); p = r.pos()
        self.assertEqual((p["outcome"], p["next_round"], p["next_kind"], p["phase"]), ("CONFIRM", 3, "confirm", "assemble"))
        r.round_done(3, ("R1-F1", "P1", "resolved"), kind="confirm"); p = r.pos()
        self.assertEqual((p["outcome"], p["phase"]), ("CONVERGED", "stop"))
    def test_cap_stops(self):
        r = Repo(cap=2); r.round_done(2, ("R2-F1", "P1", "fixed:R2"), kind="delta"); p = r.pos()
        self.assertEqual((p["outcome"], p["phase"]), ("CAP", "stop"))
    def test_outcome_uses_committed_ledger_not_working_tree(self):
        r = Repo(); r.round_done(1, ("R1-F1", "P1", "fixed:R1"), kind="full")
        # an uncommitted parse of round 2 already resolved R1-F1 and added a new P1; the §8 answer for round 1 must still be CONTINUE
        r.ledger(("R1-F1", "P1", "resolved"), ("R2-F1", "P1", "open"))
        w(os.path.join(r.run, ".prompt-round-2.md"), "p"); time.sleep(0.01)
        w(os.path.join(r.run, "round-2.json"), "{}"); w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nparsed=1\n")
        p = r.pos(); self.assertEqual((p["n_done"], p["outcome"], p["next_round"], p["phase"]), (1, "CONTINUE", 2, "respond"))
        r.ledger(("R1-F1", "P1", "resolved")); r.commit("refine(t): round 2 (0 accepted, 0 rejected, 0 deferred)")
        r.ledger(("R1-F1", "P1", "resolved"), ("R3-F1", "P0", "open"))   # uncommitted again; committed says converged
        self.assertEqual((r.pos()["outcome"], r.pos()["phase"]), ("CONVERGED", "stop"))

    def test_refreshes_baseline_and_reports_released(self):
        r = Repo(); w(os.path.join(r.d, "user.txt"), "u\n"); w(os.path.join(r.run, "dirty-baseline"), "user.txt\nother.txt\n")
        self.assertEqual(r.pos()["released"], ["other.txt"]);
        with open(os.path.join(r.run, "dirty-baseline")) as f: self.assertEqual(f.read(), "user.txt\n")
        r.g("add", "user.txt"); r.g("commit", "-qm", "user committed"); self.assertEqual(r.pos()["released"], ["user.txt"])
    def test_repair_states_route_to_run_or_parse(self):
        r = Repo(); r.round_done(1, ("R1-F1", "P1", "fixed:R1"), kind="full")
        w(os.path.join(r.run, ".prompt-round-2.md"), "p"); time.sleep(0.01)
        w(os.path.join(r.run, "round-2.json"), '{"verdict":"ready","findings":[],"prior":[],"verified":[],"not_verified":[]}')
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nparse_failed=1\nrepair_started=1\n"); self.assertEqual(r.pos()["phase"], "run")   # interrupted repair
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nparse_failed=1\nrepair_exit=1\n"); self.assertEqual(r.pos()["phase"], "run")       # failed repair
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nrepair_exit=0\n"); self.assertEqual(r.pos()["phase"], "parse")                     # successful repair, unparsed
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nrepair_exit=0\nparse_failed=1\n"); self.assertEqual(r.pos()["phase"], "run")     # second violation

    def test_second_violation_after_repair_reruns(self):
        r = Repo(); r.round_done(1, ("R1-F1", "P1", "fixed:R1"), kind="full")
        w(os.path.join(r.run, ".prompt-round-2.md"), "p"); time.sleep(0.01)
        w(os.path.join(r.run, "round-2.json"), '{"verdict":"ready","findings":[],"prior":[],"verified":[],"not_verified":[]}')
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nparse_failed=1\n"); self.assertEqual(r.pos()["phase"], "parse")
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nparse_failed=1\nrepair_exit=0\n"); self.assertEqual(r.pos()["phase"], "run")
        w(os.path.join(r.run, "round-2.meta"), "kind=delta\nhead=x\nexit=0\nrepair_exit=0\n"); self.assertEqual(r.pos()["phase"], "parse")
