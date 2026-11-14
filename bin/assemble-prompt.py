#!/usr/bin/env python3
"""§7.2 step 1: build .prompt-round-N.md for a full (round 1), delta, or confirm round."""
import argparse, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refine_lib as L

REUSE = "<!-- reuse -->"
READ_RULE = ("Read by range (`sed -n`). Do not `ls` or explore beyond the subject, the run dir files named above and "
             "the files an awaited finding cites, unless a finding requires it, and say so if you do.")

def sections(text):
    return [s for s in re.split(r"(?m)^(?=## )", text) if s.strip()]

def refs_for(evidence, path, primary):
    """Line numbers an evidence string cites for `path`: `<path>:L<n>` / `<basename>:L<n>` (also `L<a>-L<b>` ranges),
    plus bare `L<n>` references (`spec L5`) when `path` is the primary (first) subject."""
    out = []
    def add(m):
        a = int(m.group(1)); b = int(m.group(2)) if m.group(2) else a
        for n in (a, b):
            if n not in out: out.append(n)
    base = os.path.basename(path)
    for m in re.finditer(r"(?:%s|%s):L(\d+)(?:-L(\d+))?" % (re.escape(path), re.escape(base)), evidence): add(m)
    if primary:
        for m in re.finditer(r"(?:^|[\s,(;])L(\d+)(?:-L(\d+))?", evidence): add(m)
    return out

def is_reuse(sec):
    lines = sec.split("\n")
    return len(lines) > 1 and lines[1].strip() == REUSE

def strip_marker(sec):
    return sec.replace(REUSE + "\n", "", 1)

def find(secs, prefix):
    return next((s for s in secs if s.startswith(prefix)), None)

PRIOR_SENTENCE = "`prior` lists exactly the awaited IDs given to you, once each, and nothing else."
CONFIRM_SENTENCE = ("`prior` lists every awaited ID (status `fixed:*` or `rejected`) exactly once, and may additionally list a decided ID "
                    "(`resolved`, `withdrawn`, `closed-by-user`, `deferred`) only with result `still open` and new evidence.")

def _read(path):
    with open(path) as f: return f.read()

def what_to_review(brief_secs, old_heads, cur_head, subjects, wt):
    sec = find(brief_secs, "## What to review") or "## What to review\n\n"
    for h in old_heads:
        if h: sec = sec.replace(h, cur_head)
    sizes = ", ".join(f"`{p}` ({len(_read(os.path.join(wt, p)).splitlines())} lines)" for p in subjects if os.path.isfile(os.path.join(wt, p)))
    return sec.rstrip("\n") + f"\n- Current revision `{cur_head}`; current subject size: {sizes or 'n/a'}.\n\n"

def manifest_for(wt, subjects, kind, base):
    if kind == "impl":
        files = L.git(wt, "diff", "--name-only", f"{base}...HEAD", "--", ".", ":!docs/superpowers/reviews")
        return "## Reading manifest\n\nFiles in the diff (`git diff --name-only " + f"{base}...HEAD`):\n\n" + "\n".join(f"- `{f}`" for f in files.splitlines()) + "\n\n" + READ_RULE + "\n\n"
    out = ["## Reading manifest", "", "Current section map of each subject (line numbers for the current revision):", ""]
    for p in subjects:
        lines = _read(os.path.join(wt, p)).split("\n")
        out.append(f"`{p}`:"); out += [f"L{ln} {t}" for ln, t in L.section_map(lines)]; out.append("")
    out += [READ_RULE, ""]
    return "\n".join(out) + "\n"

def build(run_dir, n, kind):
    meta = L.read_kv(os.path.join(run_dir, "run.meta"))
    wt, subjects, skind = meta["worktree"], meta["subject"].split(), meta["subject_kind"]
    if skind == "impl":   # the current range, so files a fix added or first edited are subjects too (R1-F5); deleted files stay listed
        try: subjects = L.git(wt, "diff", "--name-only", f"{meta.get('base', 'main')}...HEAD", "--", ".", ":!docs/superpowers/reviews").split() or subjects
        except subprocess.CalledProcessError: pass   # base ref unavailable: keep the setup-time list
    brief = _read(os.path.join(run_dir, "brief.md"))
    if kind == "full":
        return brief, {"prompt_bytes": len(brief.encode()), "prev": None, "head": L.head(wt), "awaited": [], "touched": [], "cited": []}
    cur = L.head(wt); secs = sections(brief)
    r1 = L.read_kv(os.path.join(run_dir, "round-1.meta"))["head"]
    old_heads = [meta.get("head_at_setup", ""), r1]
    rel = os.path.relpath(os.path.realpath(run_dir), os.path.realpath(wt))
    rows = L.read_ledger(os.path.join(run_dir, "ledger.md"))
    ledger_md = _read(os.path.join(run_dir, "ledger.md"))
    if kind == "confirm":
        decided = [r for r in rows if r["status"] in ("resolved", "withdrawn", "closed-by-user", "deferred")]
        blocks = [L.finding_block(L.load_round(run_dir, L.round_of(r["id"])), L.round_of(r["id"]), int(r["id"].split("-F")[1])) for r in decided]
        out = []
        for s in secs:
            if s.startswith("## What to review"): out.append(what_to_review(secs, old_heads, cur, subjects, wt))
            elif s.startswith("## Reading manifest"): out.append(manifest_for(wt, subjects, skind, meta.get("base", "main")))
            elif s.startswith("## Output format"):
                plain = strip_marker(s)
                if PRIOR_SENTENCE not in plain:
                    print(f"assemble-prompt: brief.md's Output format section does not contain the expected "
                          f"`prior` sentence ({PRIOR_SENTENCE!r}); refusing to build a confirm prompt that would "
                          "silently keep the round-1 sentence instead of the confirm one.", file=sys.stderr)
                    sys.exit(1)
                out.append(plain.replace(PRIOR_SENTENCE, CONFIRM_SENTENCE))
            else: out.append(strip_marker(s))
        out.append("## Confirm pass\n\nThis is a full review of the current revision after the loop converged. The ledger below records every decision so far. "
                   "A decided ID may be raised again only as a `prior` entry with result `still open` and new evidence, never as a new finding; "
                   "awaited IDs (status `fixed:*` or `rejected`) must appear in `prior` exactly once.\n\n")
        out.append("## Ledger\n\n" + ledger_md + "\n")
        out.append("## Decided findings\n\n" + "\n\n".join(blocks) + "\n\n")
        text = "".join(out)
        return text, {"prompt_bytes": len(text.encode()), "prev": r1, "head": cur, "awaited": L.awaited_ids(rows), "touched": [], "cited": []}
    # delta
    prev = L.read_kv(os.path.join(run_dir, f"round-{n-1}.meta"))["head"]
    if skind == "impl": diff = L.git(wt, "diff", f"{prev}..HEAD", "--", ".", f":!{rel}")   # the whole fix, files a fix added included (§3)
    else: diff = L.git(wt, "diff", f"{prev}..HEAD", "--", *subjects)
    touched = []
    for p in subjects:
        if not p.endswith(".md") or not os.path.isfile(os.path.join(wt, p)): continue   # a deleted file has no current sections (R1-F4)
        pdiff = L.git(wt, "diff", "-U0", f"{prev}..HEAD", "--", p)
        lines = _read(os.path.join(wt, p)).split("\n")
        for a, b, t in L.touched_sections(pdiff, L.section_map(lines), len(lines)): touched.append([a, b, t, p])
    awaited = L.awaited_ids(rows)
    blocks = [L.finding_block(L.load_round(run_dir, L.round_of(i)), L.round_of(i), int(i.split("-F")[1])) for i in awaited]
    # sections an awaited finding cites, located in the revision it reviewed and relocated by title (§7.2 step 1)
    cited = []
    for i in awaited:
        m = L.round_of(i); f = L.load_round(run_dir, m)["findings"][int(i.split("-F")[1]) - 1]
        old_head = L.read_kv(os.path.join(run_dir, f"round-{m}.meta"))["head"]
        for j, p in enumerate(subjects):
            if not p.endswith(".md") or not os.path.isfile(os.path.join(wt, p)): continue
            refs = refs_for(f["evidence"], p, primary=(j == 0))
            if not refs: continue
            try: old_lines = L.git(wt, "show", f"{old_head}:{p}").split("\n")
            except subprocess.CalledProcessError: continue   # the file did not exist in the revision that finding reviewed
            new_lines = _read(os.path.join(wt, p)).split("\n")
            for a, b, t in L.relocate_sections(old_lines, new_lines, refs):
                is_cited = any(c[0] == a and c[3] == p for c in cited)
                is_touched = any(tt[0] == a and tt[3] == p for tt in touched)
                if not is_cited and not is_touched: cited.append([a, b, t, p, i])
    reuse = [s for s in secs if is_reuse(s)]
    role = [strip_marker(s) for s in reuse if s.startswith("## Role")]
    rest = [strip_marker(s) for s in reuse if not s.startswith("## Role")]
    preamble = (f"## Delta round {n}\n\nThe subject was revised since your findings. Verify each awaited finding below against the diff and the current text, by ID. "
                "Look for regressions in the regions the diff touches, and for contradictions the changes introduced with unchanged sections. "
                "Report every awaited ID in `prior`, exactly once: `resolved` if the fix is correct and complete, `still open` with what is still wrong and new evidence if not. "
                "Raise new findings only in touched regions or where a fix directly caused them; do not re-review unchanged material. Same severities and cap as before.\n\n")
    man = ["## Delta manifest", "", f"Sections of the current revision (`{cur}`) that the diff touches, then the sections awaited findings cite:", ""]
    man += [f"- `{p}:L{a}-L{b}`  {t}" for a, b, t, p in touched] or ["- (no markdown sections; see the diff)"]
    man += [f"- `{p}:L{a}-L{b}`  {t} (cited by {i})" for a, b, t, p, i in cited]
    man += ["", READ_RULE, ""]
    for p in subjects:
        if p.endswith(".md") and os.path.isfile(os.path.join(wt, p)):   # a deleted markdown file has no current section map (R1-F4)
            lines = _read(os.path.join(wt, p)).split("\n")
            man += [f"Section map of `{p}`:", ""] + [f"L{ln} {t}" for ln, t in L.section_map(lines)] + [""]
    resp = _read(os.path.join(run_dir, f"response-{n-1}.md"))
    rul = os.path.join(run_dir, f"ruling-{n-1}.md")
    if os.path.exists(rul):
        resp += f"\n\n## User's ruling after round {n-1} (the awaited fixes were made under it)\n\n" + _read(rul)
    text = ("".join(role) + what_to_review(secs, old_heads, cur, subjects, wt) + preamble + "## Ledger\n\n" + ledger_md + "\n"
            + f"## Awaited findings ({len(awaited)} IDs, verbatim)\n\n" + "\n\n".join(blocks) + "\n\n"
            + f"## Diff since round {n-1} (`git diff {prev}..HEAD -- <subject>`)\n\n```diff\n" + diff + "\n```\n\n"
            + "\n".join(man) + "\n" + "".join(rest) + f"\n## Responder's round-{n-1} response\n\n" + resp)
    return text, {"prompt_bytes": len(text.encode()), "prev": prev, "head": cur, "awaited": awaited,
                  "touched": [[a, b, t] for a, b, t, _ in touched], "cited": [[a, b, t] for a, b, t, _, _ in cited]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--kind", choices=["full", "delta", "confirm"], required=True); ap.add_argument("--stdout", action="store_true")
    a = ap.parse_args()
    text, info = build(a.run_dir, a.round, a.kind)
    if a.stdout: sys.stdout.write(text); return
    L._atomic_write(os.path.join(a.run_dir, f".prompt-round-{a.round}.md"), text)
    print(json.dumps(info))

if __name__ == "__main__": main()
