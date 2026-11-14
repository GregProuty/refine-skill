"""Shared helpers for the /refine skill. Spec: docs/design.md."""
import json, os, re, shlex, subprocess

END = "<!-- end -->"
PENDING = "<!-- pending -->"
PLAIN_STATUSES = {"open", "resolved", "rejected", "withdrawn", "reopened", "contested", "closed-by-user", "deferred"}
FIXED_RE = re.compile(r"^fixed:(R\d+|ruling\d+)$")
ID_RE = re.compile(r"^R(\d+)-F(\d+)$")
ENTRY_RE = re.compile(r"^- (\S.*)$")
HEAD_RE = re.compile(r"^#{2,3} ")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)
EFFORT_DOWN = {"high": "medium", "medium": "low", "low": "low"}

# ---- statuses ----
def is_fixed(status): return bool(FIXED_RE.match(status))
def is_valid_status(status): return status in PLAIN_STATUSES or is_fixed(status)
def terminal(status): return status in ("resolved", "withdrawn", "closed-by-user")
def awaited_ids(rows): return [r["id"] for r in rows if is_fixed(r["status"]) or r["status"] == "rejected"]
def round_of(id_): return int(ID_RE.match(id_).group(1))

# ---- ledger (markdown table, one row per finding; no '|' inside cells) ----
def _rows(text):
    """Parse ledger rows from text (markdown format)."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("| R"): continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6: raise ValueError(f"bad ledger row: {line!r}")
        id_, sev, title, status, cycles, note = cells
        rows.append({"id": id_, "sev": sev, "title": title, "status": status, "cycles": int(cycles), "note": note})
    return rows

def read_ledger(path):
    with open(path) as f:
        return _rows(f.read())

def _sanitize_cell(s):
    """A ledger cell is one markdown-table field: no '|' (it would split the row) and no newline
    (it would truncate the cell at the first line). Collapse any whitespace run, newlines included, to
    one space, and swap '|' for a lookalike so a Codex- or Claude-authored title or note can never
    corrupt the table (finding 1)."""
    return re.sub(r"\s+", " ", s.replace("|", "¦")).strip()

def write_ledger(path, rows, topic):
    lines = [f"# Ledger: {topic}", "", "| id | sev | title | status | cycles | note |", "|---|---|---|---|---|---|"]
    for r in rows:
        title, note = _sanitize_cell(r["title"]), _sanitize_cell(r["note"])
        lines.append(f"| {r['id']} | {r['sev']} | {title} | {r['status']} | {r['cycles']} | {note} |")
    _atomic_write(path, "\n".join(lines) + "\n")

def get_row(rows, id_):
    return next((r for r in rows if r["id"] == id_), None)

# ---- key=value files (*.meta, run.meta) ----
def read_kv(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if "=" in line: k, v = line.split("=", 1); d[k] = v
    return d

def write_kv(path, d):
    _atomic_write(path, "".join(f"{k}={v}\n" for k, v in d.items()))

def format_command(wt, meta):
    """The command that formats the run dir's JSON before a commit (spec section 4.2), as argv, or None.
    run.meta `format=` wins (empty disables it). Without the key, the worktree's own prettier is used,
    with the --config of the first package.json script that runs prettier, so a repo-wide format check
    passes on committed round JSON. No prettier installed: None."""
    if "format" in meta:
        v = meta["format"].strip()
        return shlex.split(v) if v else None
    exe = os.path.join(wt, "node_modules", ".bin", "prettier")
    if not os.access(exe, os.X_OK): return None
    cmd = [exe]
    try:
        with open(os.path.join(wt, "package.json")) as f: scripts = json.load(f).get("scripts", {}) or {}
    except (OSError, ValueError, AttributeError):
        scripts = {}
    for script in scripts.values():
        if not isinstance(script, str) or "prettier" not in script: continue
        try: toks = shlex.split(script)
        except ValueError: continue
        if "--config" in toks and toks.index("--config") + 1 < len(toks):
            cmd += ["--config", toks[toks.index("--config") + 1]]
        break
    return cmd + ["--write"]

def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: f.write(text)
    os.replace(tmp, path)

# ---- response / ruling records (§7.2 step 4, §8) ----
def record_state(path):
    if not os.path.exists(path): return "absent"
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f]
    body = [l for l in lines if l.strip()]
    if not body: return "incomplete"
    if body[-1] == PENDING: return "pending"
    if body[-1] != END: return "incomplete"
    try: h = max(i for i, l in enumerate(lines) if l.strip() == "## Files changed")
    except ValueError: return "incomplete"
    e = max(i for i, l in enumerate(lines) if l.strip() == END)
    for l in lines[h + 1:e]:
        if l.strip() and not ENTRY_RE.match(l): return "incomplete"
    return "complete"

def files_changed(path):
    """Entries of the final `## Files changed` section, prefix stripped. Only meaningful for a complete record."""
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f]
    idx = [i for i, l in enumerate(lines) if l.strip() == "## Files changed"]
    if not idx: return []
    out = []
    for l in lines[idx[-1] + 1:]:
        if l.strip() in (END, PENDING): break
        m = ENTRY_RE.match(l)
        if m: out.append(m.group(1).strip())
    return out

# ---- sections of a markdown subject ----
def section_map(lines):
    return [(i + 1, l) for i, l in enumerate(lines) if HEAD_RE.match(l)]

def section_of(heads, nlines, line):
    cur = None
    for i, (ln, _) in enumerate(heads):
        if ln <= line: cur = i
    if cur is None: return None
    end = heads[cur + 1][0] - 1 if cur + 1 < len(heads) else nlines
    return (heads[cur][0], end, heads[cur][1])

def touched_sections(diff, heads, nlines):
    """Every section that overlaps a hunk's new-file range (a hunk may span several sections)."""
    found = {}
    for m in HUNK_RE.finditer(diff):
        a = int(m.group(1)); b = a + int(m.group(2) or 1) - 1
        for ln, _ in heads:
            s = section_of(heads, nlines, ln)
            if s and s[0] <= b and s[1] >= a: found[s[0]] = s
        for ln in (a, b):
            s = section_of(heads, nlines, ln)
            if s: found[s[0]] = s
    return [found[k] for k in sorted(found)]

def relocate_sections(old_lines, new_lines, line_numbers):
    """For each old line number, the section that contained it, found again by title in the new text (§7.2 step 1, cited sections)."""
    old_heads, new_heads = section_map(old_lines), section_map(new_lines)
    titles = []
    for ln in line_numbers:
        if ln < 1 or ln > len(old_lines): continue
        s = section_of(old_heads, len(old_lines), ln)
        if s and s[2] not in titles: titles.append(s[2])
    found = {}
    for t in titles:
        for ln, title in new_heads:
            if title == t:
                s = section_of(new_heads, len(new_lines), ln); found[s[0]] = s; break
    return [found[k] for k in sorted(found)]

# ---- rounds and rendering (§5.2 rendered form) ----
def load_round(run_dir, n):
    with open(os.path.join(run_dir, f"round-{n}.json")) as f:
        return json.load(f)

def finding_block(d, n, k):
    f = d["findings"][k - 1]
    return f"### [{f['severity']}] R{n}-F{k} {f['title']}\n{f['claim']} · {f['evidence']} · {f['why']} · {f['fix']}"

def render_review(d, n):
    out = [f"Verdict: {d['verdict']}", ""]
    if d["findings"]:
        out.append("## Findings"); out.append("")
        for k in range(1, len(d["findings"]) + 1): out += [finding_block(d, n, k), ""]
    if d["prior"]:
        out.append("## Prior findings")
        out += [f"- {p['id']}: {p['result']} — {p['note']}" for p in d["prior"]]; out.append("")
    out.append("## Verified"); out += [f"- {v}" for v in d["verified"]] or ["- (none)"]; out.append("")
    out.append("## Not verified"); out += [f"- {v}" for v in d["not_verified"]] or ["- (none)"]
    return "\n".join(out) + "\n"

# ---- git ----
def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).rstrip("\n")

def head(repo): return git(repo, "rev-parse", "--short", "HEAD")

def committed_ledger(repo, rel_run_dir):
    """The ledger as committed at HEAD (§7.3 step 2 evaluates from committed state). [] when HEAD has no ledger."""
    try: text = subprocess.check_output(["git", "-C", repo, "show", f"HEAD:{rel_run_dir}/ledger.md"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError: return []
    return _rows(text)

def porcelain_paths(repo, *paths):
    """Exact dirty paths, files inside untracked directories included, NUL-safe."""
    raw = subprocess.check_output(["git", "-C", repo, "status", "--porcelain", "-z", "--untracked-files=all", "--", *paths])
    out = []
    entries = raw.split(b"\0")
    i = 0
    while i < len(entries):
        e = entries[i].decode()
        if not e: i += 1; continue
        code, path = e[:2], e[3:]
        if code[0] in "RC": i += 1  # rename/copy: the next NUL entry is the original path
        out.append(path); i += 1
    return out

def refresh_baseline(repo, run_dir):
    """Drop baseline paths that are clean now (the user committed or moved the work aside); return what was released."""
    p = os.path.join(run_dir, "dirty-baseline")
    if not os.path.exists(p): return []
    with open(p) as f:
        base = [l for l in f.read().split("\n") if l]
    dirty = set(porcelain_paths(repo))
    released = [b for b in base if b not in dirty]
    if released: _atomic_write(p, "".join(b + "\n" for b in base if b in dirty))
    return released

def run_commits(repo, run_dir, topic):
    """Commits touching run_dir whose subject matches the §4.2 formats; anchored to the run dir (§7.3 step 1)."""
    out = {"brief": None, "rounds": {}, "rulings": {}}
    log = git(repo, "log", "--format=%h%x09%s", "--", run_dir)
    for line in log.splitlines():
        h, subj = line.split("\t", 1)
        if subj == f"refine({topic}): brief": out["brief"] = h
        m = re.match(rf"^refine\({re.escape(topic)}\): round (\d+) \(", subj)
        if m: out["rounds"].setdefault(int(m.group(1)), h)
        m = re.match(rf"^refine\({re.escape(topic)}\): ruling after round (\d+) \(", subj)
        if m: out["rulings"].setdefault(int(m.group(1)), h)
    return out

# ---- effort and termination (§3, §8 ledger-derived outcomes) ----
def delta_effort(e): return EFFORT_DOWN[e]

def evaluate(rows, n, cap, confirm, confirm_ran):
    p01 = [r for r in rows if r["sev"] in ("P0", "P1")]
    if any(r["status"] == "contested" for r in p01): return "CONTESTED"
    new_p01 = [r for r in p01 if r["id"].startswith(f"R{n}-")]
    if not new_p01 and all(terminal(r["status"]) for r in p01):
        if confirm and not confirm_ran and n < cap: return "CONFIRM"
        return "CONVERGED"
    if n >= cap: return "CAP"
    return "CONTINUE"
