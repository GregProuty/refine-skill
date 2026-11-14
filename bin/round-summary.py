#!/usr/bin/env python3
"""§9: the round block (after respond and commit) and the final-summary totals, from the ledger, the metas, the round JSON and git."""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refine_lib as L

TOK = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")

def num(m, k): return int(m.get(k) or 0)

def usage(m):  # a round's usage including its repair turn
    return {k: num(m, k) + num(m, "repair_" + k) for k in TOK} | {"duration_s": num(m, "duration_s") + num(m, "repair_duration_s")}

def k(n): return f"{(n + 500) // 1000}k"   # round half up: 98,500 -> 99k (Python's round() would give 98)

def block(run_dir, n, status_line):
    meta = L.read_kv(os.path.join(run_dir, "run.meta")); m = L.read_kv(os.path.join(run_dir, f"round-{n}.meta"))
    wt = meta["worktree"]; rel = os.path.relpath(os.path.realpath(run_dir), os.path.realpath(wt))
    rows = L.read_ledger(os.path.join(run_dir, "ledger.md"))
    try: d = L.load_round(run_dir, n)
    except FileNotFoundError: d = {"verdict": "(no output)", "prior": []}
    u = usage(m)
    dur = f"{u['duration_s'] // 60}m{u['duration_s'] % 60:02d}s"
    tok = u["input_tokens"] + u["output_tokens"]   # §9: tok = input + output, repair included; cached shown for cost reading
    out = [f"── /refine round {n}/{meta.get('cap', '10')} · {m.get('kind', '?')} {meta['topic']} · rev {m.get('head', '?')} · codex {dur} · "
           f"{k(tok)} tok ({k(u['cached_input_tokens'])} cached) ──", f"Verdict  {d['verdict']}"]
    new = [r for r in rows if r["id"].startswith(f"R{n}-")]
    disp = lambda st: "accepted → fixed" if L.is_fixed(st) else st
    out += [("New      " if i == 0 else "         ") + f"{r['sev']} {r['id']}  {r['title']:<52} {disp(r['status'])}" for i, r in enumerate(new)] or ["New      (none)"]
    prior = []
    for p in d["prior"]:
        r = L.get_row(rows, p["id"])
        if r is None: prior.append(f"{p['id']} ? ⚠ not in ledger")
        elif p["result"] == "resolved": prior.append(f"{p['id']} {r['sev']} ✓")
        elif p["result"] == "withdrawn": prior.append(f"{p['id']} {r['sev']} ✓ withdrawn")
        else: prior.append(f"{p['id']} {r['sev']} ⚠ still open (cycles {r['cycles']}) → {'CONTESTED' if r['status'] == 'contested' else r['status']}")
    out += ["Prior    " + "  ".join(prior)] if prior else ["Prior    (none)"]
    c = L.run_commits(wt, rel, meta["topic"]).get("rounds", {}).get(n)
    if c: out.append(f"Commit   {c}  " + L.git(wt, "log", "-1", "--format=%s", c))
    else: out.append("Commit   (not yet committed)")
    if status_line: out.append(f"Status   {status_line}")
    else:
        cap, confirm = int(meta.get("cap", "10")), meta.get("confirm", "0") == "1"
        ran = any(L.read_kv(f).get("kind") == "confirm" for f in glob.glob(os.path.join(run_dir, "round-*.meta")))
        o = L.evaluate(rows, n, cap, confirm, ran)
        bump = any(L.is_fixed(r["status"]) and r["cycles"] >= 2 for r in rows)   # a fix missed twice and fixed again: the next round runs at round-1 effort (§6)   # §6: a fix missed twice makes the next round run at round-1 effort
        eff = meta.get("effort", "high") if bump else L.delta_effort(meta.get("effort", "high"))
        out.append("Status   " + {"CONTINUE": f"CONTINUING → round {n + 1} (delta, effort {eff})",
                                  "CONFIRM": f"CONTINUING → round {n + 1} (confirm pass, effort {meta.get('effort', 'high')})"}.get(o, f"STOPPING — {o}"))
    return "\n".join(out)

def totals(run_dir):
    metas = sorted(glob.glob(os.path.join(run_dir, "round-*.meta"))); attempts = glob.glob(os.path.join(run_dir, ".round-*.attempt*.meta"))
    t = {"rounds": len(metas), "failed_attempts": 0, "duration_s": 0}
    t.update({x: 0 for x in TOK})
    for f in metas + attempts:
        m = L.read_kv(f)
        if m.get("kind") == "repair":   # a failed repair turn: only its own fields exist, and it failed iff repair_exit != 0
            if m.get("repair_exit", "1") != "0": t["failed_attempts"] += 1
        elif f in attempts and m.get("exit", "1") != "0": t["failed_attempts"] += 1
        u = usage(m); t["duration_s"] += u["duration_s"]
        for x in TOK: t[x] += u[x]
    by = {}
    for r in L.read_ledger(os.path.join(run_dir, "ledger.md")): by[r["status"]] = by.get(r["status"], 0) + 1
    t["by_status"] = by
    return t

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--round", type=int); ap.add_argument("--status"); ap.add_argument("--totals", action="store_true")
    a = ap.parse_args()
    if a.totals: print(json.dumps(totals(a.run_dir))); return
    if not a.round: ap.error("--round or --totals")
    print(block(a.run_dir, a.round, a.status))

if __name__ == "__main__": main()
