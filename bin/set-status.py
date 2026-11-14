#!/usr/bin/env python3
"""Record Claude's decision on ledger rows: --status fixed:R2|rejected|deferred|contested|fixed:ruling3|closed-by-user, with a note."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refine_lib as L

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--id", action="append", required=True)
    ap.add_argument("--status", required=True); g = ap.add_mutually_exclusive_group()
    g.add_argument("--note"); g.add_argument("--append-note")
    a = ap.parse_args()
    if not L.is_valid_status(a.status): print(f"invalid status {a.status}"); sys.exit(1)
    meta = L.read_kv(os.path.join(a.run_dir, "run.meta")); lpath = os.path.join(a.run_dir, "ledger.md")
    rows = L.read_ledger(lpath)
    for id_ in a.id:
        r = L.get_row(rows, id_)
        if r is None: print(f"unknown id {id_}"); sys.exit(1)
        if a.status == "deferred" and r["sev"] in ("P0", "P1"): print(f"{id_} is {r['sev']}: P0/P1 are never deferred (spec §6)"); sys.exit(1)
    for id_ in a.id:
        r = L.get_row(rows, id_); r["status"] = a.status
        if a.note is not None: r["note"] = a.note
        if a.append_note is not None: r["note"] = f"{r['note']}; {a.append_note}".strip("; ")
    L.write_ledger(lpath, rows, meta["topic"])
    print(json.dumps({"updated": a.id}))

if __name__ == "__main__": main()
