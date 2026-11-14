#!/usr/bin/env python3
"""§7.1 steps 1-3: preconditions, run dir, .gitignore, dirty-baseline, run.meta. The brief and its commit come after (Claude writes it; the user approves)."""
import argparse, datetime, json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refine_lib as L

GITIGNORE = "*.jsonl\n.round-*.attempt*\n!fixture-*.jsonl\n"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", required=True); ap.add_argument("--topic", required=True)
    ap.add_argument("--subject-kind", choices=["spec", "plan", "impl"], required=True); ap.add_argument("--subject", nargs="*", default=[])
    ap.add_argument("--base", default="main"); ap.add_argument("--cap", type=int, default=10); ap.add_argument("--effort", choices=["high", "medium", "low"], default="high")
    ap.add_argument("--confirm", action="store_true"); ap.add_argument("--verify", default=""); ap.add_argument("--format", default=None); ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    wt = os.path.realpath(a.worktree)
    subject = []
    if a.subject:
        for p in a.subject:   # explicit subjects: canonical, existing files under the worktree (R1-F4: derived impl lists may name deleted files)
            abs_p = p if os.path.isabs(p) else os.path.join(wt, p)
            rel_p = os.path.relpath(os.path.realpath(abs_p), wt)
            if rel_p.startswith("..") or not os.path.isfile(os.path.join(wt, rel_p)):
                print(f"subject path '{p}' is not a file under the worktree"); sys.exit(1)
            subject.append(rel_p)
    if a.subject_kind == "impl" and not subject:
        subject = L.git(wt, "diff", "--name-only", f"{a.base}...HEAD", "--", ".", ":!docs/superpowers/reviews").split()
    if not subject: print("no subject paths"); sys.exit(1)
    if L.git(wt, "diff", "--cached", "--name-only"): print("the index is not empty; commit or unstage first (§7.1 step 2)"); sys.exit(1)
    dirty_subject = L.porcelain_paths(wt, *subject)
    if dirty_subject: print(f"subject paths are dirty: {' '.join(dirty_subject)}; commit them first (§7.1 step 2)"); sys.exit(1)
    rel = f"docs/superpowers/reviews/{a.date}-{a.topic}"; run = os.path.join(wt, rel)
    if os.path.exists(run):
        if os.path.exists(os.path.join(run, "run.meta")): print(f"run dir exists: {run}; use --resume or pick another topic"); sys.exit(1)
        aside = run + ".incomplete-" + datetime.datetime.now().strftime("%Y%m%dT%H%M%S")   # a run dir without run.meta is an interrupted setup (R1-F3)
        os.rename(run, aside); print(f"moved incomplete run dir aside: {aside}", file=sys.stderr)
    os.makedirs(os.path.dirname(run), exist_ok=True)
    stage = tempfile.mkdtemp(prefix=os.path.basename(run) + ".tmp-", dir=os.path.dirname(run))   # build here, publish atomically
    baseline = [p for p in L.porcelain_paths(wt) if not (p == rel or p.startswith(rel + "/") or p.startswith(rel + ".tmp-") or p.startswith(rel + ".incomplete-"))]
    head0 = L.head(wt)
    with open(os.path.join(stage, ".gitignore"), "w") as f: f.write(GITIGNORE)
    with open(os.path.join(stage, "dirty-baseline"), "w") as f: f.write("".join(p + "\n" for p in baseline))
    L.write_kv(os.path.join(stage, "run.meta"), {"topic": a.topic, "subject_kind": a.subject_kind, "subject": " ".join(subject), "worktree": wt, "base": a.base,
                                               "cap": str(a.cap), "effort": a.effort, "confirm": "1" if a.confirm else "0", "verify": a.verify, "created": a.date,
                                               "head_at_setup": head0, **({"format": a.format} if a.format is not None else {})})
    os.rename(stage, run)   # every file exists before the run dir does (R1-F3)
    print(json.dumps({"run_dir": run, "subject": subject, "dirty_count": len(baseline), "head_at_setup": head0}))

if __name__ == "__main__": main()
