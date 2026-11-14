#!/usr/bin/env python3
"""§7.2 step 3: semantic checks on round-N.json, §6 transitions, ledger update. Exit 2 = violation, ledger untouched."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refine_lib as L

DECIDED = ("resolved", "withdrawn", "closed-by-user", "deferred")

def apply_round(rows, review, n, kind):
    rows = [dict(r) for r in rows]
    awaited = L.awaited_ids(rows)
    violations, transitions, judgment, contested = [], [], [], []
    seen = set()
    if kind == "full" and review["prior"]:
        violations.append("prior must be empty in round 1")
    for p in review["prior"]:
        id_, res, note = p["id"], p["result"], p["note"]
        if id_ in seen: violations.append(f"duplicate prior id {id_}"); continue
        seen.add(id_)
        row = L.get_row(rows, id_)
        if row is None: violations.append(f"unknown prior id {id_}"); continue
        st = row["status"]; before = st
        if id_ in awaited:
            if L.is_fixed(st):
                if res == "resolved": row["status"] = "resolved"; row["note"] = f"{row['note']}; confirmed R{n}".strip("; ")
                elif res == "withdrawn": violations.append(f"{id_}: withdrawn is not a valid result for a {st} row"); continue
                else: _still_open(row, n, note, "open", judgment, contested, limit=3)   # an incomplete fix, not a disagreement
            else:  # rejected
                if res == "withdrawn": row["status"] = "withdrawn"; row["note"] = f"{row['note']}; withdrawn R{n}".strip("; ")
                elif res == "resolved": violations.append(f"{id_}: resolved is not a valid result for a rejected row"); continue
                else: _still_open(row, n, note, "reopened", judgment, contested)
        elif kind == "confirm" and st in DECIDED:
            if res != "still open": continue  # no-op on a decided row
            if st == "closed-by-user": row["status"] = "contested"; contested.append(id_); _note_still_open(row, n, note)
            elif st == "deferred": _note_still_open(row, n, note)
            else: _still_open(row, n, note, "open", judgment, contested, from_decided=True, limit=3 if st == "resolved" else 2)
        else:
            violations.append(f"{id_} is not awaited (status {st})"); continue
        if row["status"] != before: transitions.append({"id": id_, "from": before, "to": row["status"], "cycles": row["cycles"]})
    for id_ in awaited:
        if id_ not in seen: violations.append(f"awaited id {id_} missing from prior")
    if violations: return None, {"violations": violations}
    new = []
    for k, f in enumerate(review["findings"], 1):
        id_ = f"R{n}-F{k}"
        rows.append({"id": id_, "sev": f["severity"], "title": f["title"], "status": "open", "cycles": 0, "note": ""})
        new.append({"id": id_, "sev": f["severity"], "title": f["title"]})
    return rows, {"round": n, "verdict": review["verdict"], "new": new, "transitions": transitions,
                  "needs_judgment": judgment, "contested": contested}

def _note_still_open(row, n, note):
    row["note"] = f"{row['note']}; R{n} still open: {note}".strip("; ")

def _still_open(row, n, note, else_status, judgment, contested, from_decided=False, limit=2):
    """§6: cycles is lifetime. A rejected row re-raised is a disagreement: contested at 2 (limit=2). A fixed row
    reported still open is an incomplete fix: it reopens, and only the third miss escalates (limit=3). Claude must
    judge new evidence when a rejected row is reopened or a decided row is re-raised in a confirm pass."""
    row["cycles"] += 1
    _note_still_open(row, n, note)
    if row["cycles"] >= limit:
        row["status"] = "contested"; contested.append(row["id"]); return
    row["status"] = else_status
    if else_status == "reopened" or from_decided: judgment.append(row["id"])

def _mark(mpath, **kv):
    if not os.path.exists(mpath): return
    m = L.read_kv(mpath)
    for k, v in kv.items():
        if v is None: m.pop(k, None)
        else: m[k] = v
    L.write_kv(mpath, m)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--kind", choices=["full", "delta", "confirm"], required=True)
    a = ap.parse_args()
    meta = L.read_kv(os.path.join(a.run_dir, "run.meta"))
    wt = meta["worktree"]; rel = os.path.relpath(os.path.realpath(a.run_dir), os.path.realpath(wt))
    rows = L.committed_ledger(wt, rel)   # the ledger at HEAD: idempotent input (§7.3)
    review = L.load_round(a.run_dir, a.round)
    mpath = os.path.join(a.run_dir, f"round-{a.round}.meta")
    new_rows, summary = apply_round(rows, review, a.round, a.kind)
    if new_rows is None:
        _mark(mpath, parse_failed="1")
        print(json.dumps(summary)); sys.exit(2)
    L.write_ledger(os.path.join(a.run_dir, "ledger.md"), new_rows, meta["topic"])
    _mark(mpath, parsed="1", parse_failed=None, needs_judgment=",".join(summary["needs_judgment"]))   # §7.3 respond resumes from this, not from a reconstruction (R1-F6)   # §7.3 reads `parsed`; the ledger write above is repaired by re-running if this write is lost
    print(json.dumps(summary)); sys.exit(0)

if __name__ == "__main__": main()
