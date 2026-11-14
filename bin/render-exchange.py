#!/usr/bin/env python3
"""Render exchange.md from round-N.json, response-N.md and ruling-N.md in order (spec §4.2)."""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refine_lib as L

def render(run_dir):
    meta = L.read_kv(os.path.join(run_dir, "run.meta"))
    parts = [f"# Codex review exchange: {meta['topic']}", "", f"Subject: `{meta['subject']}` ({meta['subject_kind']}). Reviewer: Codex CLI via `codex exec`. Responder: Claude.", "", "---", ""]
    n = 1
    while os.path.exists(os.path.join(run_dir, f"round-{n}.meta")):
        m = L.read_kv(os.path.join(run_dir, f"round-{n}.meta"))
        failed = sum(1 for f in glob.glob(os.path.join(run_dir, f".round-{n}.attempt*.meta")) if L.read_kv(f).get("exit", "1") != "0")
        extra = f"; {failed} failed attempt{'s' if failed != 1 else ''}" if failed else ""
        parts += [f"# Round {n} ({m.get('kind', '?')}, reviewing {m.get('head', '?')}, effort {m.get('effort', '?')}, {m.get('duration_s', '?')} s, "
                  f"{m.get('input_tokens', '?')} in / {m.get('cached_input_tokens', '?')} cached / {m.get('output_tokens', '?')} out{extra})", ""]
        if os.path.exists(os.path.join(run_dir, f"round-{n}.json")): parts += [L.render_review(L.load_round(run_dir, n), n), "---", ""]
        for name in (f"response-{n}.md", f"ruling-{n}.md"):
            p = os.path.join(run_dir, name)
            if os.path.exists(p):
                with open(p) as f: parts += [f.read().rstrip("\n"), "", "---", ""]
        n += 1
    L._atomic_write(os.path.join(run_dir, "exchange.md"), "\n".join(parts) + "\n")
    return n - 1

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); a = ap.parse_args()
    print(json.dumps({"rounds": render(a.run_dir)}))

if __name__ == "__main__": main()
