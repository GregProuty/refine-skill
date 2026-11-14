#!/usr/bin/env python3
"""§7.3: derive where to resume from git and the run dir, evaluating §8 for the last committed round first."""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refine_lib as L

def valid_output(run_dir, n):
    out, meta, prompt = (os.path.join(run_dir, f) for f in (f"round-{n}.json", f"round-{n}.meta", f".prompt-round-{n}.md"))
    if not (os.path.exists(out) and os.path.exists(meta)): return False
    if L.read_kv(meta).get("exit") != "0": return False
    if os.path.exists(prompt) and os.stat(out).st_mtime_ns <= os.stat(prompt).st_mtime_ns: return False   # strictly newer, in ns (§7.2 step 2)
    try:
        with open(out) as f: json.load(f)
        return True
    except Exception: return False

def repair_needs_rerun(m):
    """§7.2 step 2 / §7.3: after a repair that was interrupted (repair_started, no repair_exit) or that failed
    (repair_exit != 0), the round is re-run from a fresh attempt; only a successful repair (repair_exit == 0) is parsed."""
    if "repair_started" in m and "repair_exit" not in m: return "repair interrupted; re-run the round"
    if m.get("repair_exit") not in (None, "0"): return "repair failed; re-run the round"
    return None

def position(run_dir):
    meta = L.read_kv(os.path.join(run_dir, "run.meta"))
    wt, topic = meta["worktree"], meta["topic"]
    rel = os.path.relpath(os.path.realpath(run_dir), os.path.realpath(wt))
    cap, confirm = int(meta.get("cap", "10")), meta.get("confirm", "0") == "1"
    released = L.refresh_baseline(wt, run_dir)   # §8 BLOCKED PATH recovery: paths the user cleaned are unblocked
    commits = L.run_commits(wt, rel, topic)
    if commits["brief"] is None:
        return {"n_done": 0, "outcome": None, "ruling": "none", "next_round": 1, "next_kind": "full", "phase": "setup", "reason": "no brief commit touching the run dir", "released": released}
    n_done = max(commits["rounds"], default=0)
    rows = L.committed_ledger(wt, rel)   # §7.3 step 2: termination is re-derived from committed state only
    confirm_ran = any(L.read_kv(os.path.join(run_dir, f"round-{m}.meta")).get("kind") == "confirm"
                      for m in range(1, n_done + 1) if os.path.exists(os.path.join(run_dir, f"round-{m}.meta")))
    outcome, ruling = None, "none"
    next_round, next_kind = n_done + 1, ("full" if n_done == 0 else "delta")
    if n_done >= 1:
        outcome = L.evaluate(rows, n_done, cap, confirm, confirm_ran)
        if outcome == "CONTESTED":
            ruling = L.record_state(os.path.join(run_dir, f"ruling-{n_done}.md"))
            phase = {"absent": "ask-ruling", "incomplete": "ask-ruling", "pending": "apply-ruling", "complete": "commit-ruling"}[ruling]
            return {"n_done": n_done, "outcome": outcome, "ruling": ruling, "next_round": next_round, "next_kind": next_kind, "phase": phase,
                    "reason": f"round {n_done} left contested rows; ruling file is {ruling}", "released": released}
        if outcome in ("CONVERGED", "CAP"):
            return {"n_done": n_done, "outcome": outcome, "ruling": ruling, "next_round": None, "next_kind": None, "phase": "stop", "reason": f"{outcome} at round {n_done}", "released": released}
        if outcome == "CONFIRM": next_kind = "confirm"
    n = next_round
    prompt = os.path.join(run_dir, f".prompt-round-{n}.md")
    m = L.read_kv(os.path.join(run_dir, f"round-{n}.meta")) if os.path.exists(os.path.join(run_dir, f"round-{n}.meta")) else {}
    if not os.path.exists(prompt): phase, reason = "assemble", f"no prompt for round {n}"
    elif repair_needs_rerun(m): phase, reason = "run", f"round {n}: {repair_needs_rerun(m)}"
    elif not valid_output(run_dir, n): phase, reason = "run", f"round {n} has no valid output"
    elif m.get("parsed") != "1" and "repair_exit" in m and m.get("parse_failed") == "1": phase, reason = "run", f"round {n} failed semantics again after its one repair; re-run"
    elif m.get("parsed") != "1": phase, reason = "parse", f"round {n} output not yet parsed"
    elif L.record_state(os.path.join(run_dir, f"response-{n}.md")) != "complete": phase, reason = "respond", f"round {n} response not complete"
    else: phase, reason = "verify-commit", f"round {n} response complete, not committed"
    return {"n_done": n_done, "outcome": outcome, "ruling": ruling, "next_round": n, "next_kind": next_kind, "phase": phase, "reason": reason, "released": released}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); a = ap.parse_args()
    print(json.dumps(position(a.run_dir)))

if __name__ == "__main__": main()
