import json, os, shutil, stat, subprocess, tempfile, time, unittest
HERE = os.path.dirname(__file__)
BIN = os.path.join(HERE, "..", "bin", "run-round.sh")
FIX = os.path.join(HERE, "fixtures")
FAKE = r'''#!/usr/bin/env bash
# fake codex for tests. Modes: ok | usage-limit | stale | old | badjson
echo "$*" >> "$FAKE_CODEX_LOG"
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
cat > /dev/null   # consume stdin prompt
case "$FAKE_CODEX_MODE" in
  ok)
    echo '{"type":"thread.started","thread_id":"tid-123"}'
    echo '{"type":"turn.started"}'
    echo '{"verdict":"ready","findings":[],"prior":[],"verified":["v"],"not_verified":[]}' > "$out"
    echo '{"type":"turn.completed","usage":{"input_tokens":1000,"cached_input_tokens":400,"output_tokens":50,"reasoning_output_tokens":20}}'
    exit 0 ;;
  usage-limit) cat "$FAKE_CODEX_FIXTURE"; exit 1 ;;
  stale) echo '{"type":"thread.started","thread_id":"tid-9"}'; exit 0 ;;
  old) echo '{"type":"thread.started","thread_id":"tid-9"}'; echo '{"verdict":"ready","findings":[],"prior":[],"verified":[],"not_verified":[]}' > "$out"; touch -t 200001010000 "$out"; exit 0 ;;
  badjson) echo '{"type":"thread.started","thread_id":"tid-9"}'; echo 'not json' > "$out"; echo '{"type":"turn.completed","usage":{}}'; exit 0 ;;
esac
'''

def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(t)

class Env:
    def __init__(self):
        self.d = tempfile.mkdtemp(); self.bin = os.path.join(self.d, "fakebin"); os.makedirs(self.bin)
        fake = os.path.join(self.bin, "codex"); w(fake, FAKE); os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        self.wt = os.path.join(self.d, "wt"); os.makedirs(self.wt)
        subprocess.check_call(["git", "-C", self.wt, "init", "-q"]); subprocess.check_call(["git", "-C", self.wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"])
        self.run = os.path.join(self.wt, "docs/superpowers/reviews/2026-01-01-t"); os.makedirs(self.run)
        w(os.path.join(self.run, "run.meta"), f"topic=t\nsubject_kind=spec\nsubject=docs/spec.md\nworktree={self.wt}\ncap=10\neffort=high\nconfirm=0\n")
        w(os.path.join(self.run, "brief.md"), "## Role\n<!-- reuse -->\n\nreview\n")
        self.log = os.path.join(self.d, "argv.log")
    def go(self, *args, mode="ok"):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], FAKE_CODEX_MODE=mode, FAKE_CODEX_LOG=self.log,
                   FAKE_CODEX_FIXTURE=os.path.join(FIX, "usage-limit.jsonl"))
        return subprocess.run(["bash", BIN, "--run-dir", self.run, *args], capture_output=True, text=True, env=env)
    def meta(self, n=1):
        with open(os.path.join(self.run, f"round-{n}.meta")) as f:
            return dict(l.split("=", 1) for l in f.read().split())

class RunRoundTest(unittest.TestCase):
    def test_ok_full_round_assembles_and_records_meta(self):
        e = Env(); p = e.go("--round", "1", "--kind", "full")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(os.path.join(e.run, "round-1.json")) as f:
            self.assertEqual(json.load(f)["verdict"], "ready")
        m = e.meta(); self.assertEqual(m["thread_id"], "tid-123"); self.assertEqual(m["input_tokens"], "1000"); self.assertEqual(m["cached_input_tokens"], "400")
        self.assertEqual(m["exit"], "0"); self.assertEqual(m["kind"], "full"); self.assertEqual(m["effort"], "high"); self.assertTrue(m["head"])
        with open(e.log) as f:
            argv = f.read()
        self.assertIn("-s read-only", argv); self.assertIn(f"-C {e.wt}", argv); self.assertIn('model_reasoning_effort="high"', argv)
        self.assertIn("--json", argv); self.assertIn("--output-schema", argv); self.assertTrue(argv.strip().endswith("-"))
        self.assertTrue(os.path.exists(os.path.join(e.run, ".prompt-round-1.md")))
    def test_delta_effort_is_one_tier_lower(self):
        e = Env(); w(os.path.join(e.run, ".prompt-round-2.md"), "p")
        p = e.go("--round", "2", "--kind", "delta", "--no-assemble"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(e.meta(2)["effort"], "medium");
        with open(e.log) as f: self.assertIn('model_reasoning_effort="medium"', f.read())
    def test_usage_limit_fails_cleanly_and_preserves_immediately(self):
        e = Env(); p = e.go("--round", "1", "--kind", "full", mode="usage-limit")
        self.assertEqual(p.returncode, 1); self.assertIn("usage limit", p.stdout); self.assertFalse(os.path.exists(os.path.join(e.run, "round-1.json")))
        for ext in ("md", "jsonl", "meta"): self.assertTrue(os.path.exists(os.path.join(e.run, f".round-1.attempt1.{ext}")), ext)
        with open(os.path.join(e.run, ".round-1.attempt1.meta")) as f:
            am = dict(l.split("=", 1) for l in f.read().split())
        self.assertEqual(am["exit"], "1"); self.assertEqual(am["input_tokens"], "")
        self.assertFalse(os.path.exists(os.path.join(e.run, ".codex-round-1.jsonl"))); self.assertFalse(os.path.exists(os.path.join(e.run, "round-1.meta")))
        p = e.go("--round", "1", "--kind", "full", mode="ok"); self.assertEqual(p.returncode, 0)
        self.assertEqual(e.meta()["exit"], "0"); self.assertFalse(os.path.exists(os.path.join(e.run, ".round-1.attempt2.meta")))
    def test_stale_old_and_badjson_fail(self):
        for mode, needle, has_json in (("stale", "missing", False), ("old", "older than prompt", True), ("badjson", "valid JSON", True)):
            e = Env(); p = e.go("--round", "1", "--kind", "full", mode=mode)
            self.assertEqual(p.returncode, 1, mode); self.assertIn(needle, p.stdout, mode)
            for ext in ("md", "jsonl", "meta"): self.assertTrue(os.path.exists(os.path.join(e.run, f".round-1.attempt1.{ext}")), (mode, ext))
            self.assertEqual(os.path.exists(os.path.join(e.run, ".round-1.attempt1.json")), has_json, mode)
            for live in ("round-1.json", "round-1.meta", ".codex-round-1.jsonl"): self.assertFalse(os.path.exists(os.path.join(e.run, live)), (mode, live))
    def test_dry_run_writes_nothing(self):
        e = Env(); p = e.go("--round", "1", "--kind", "full", "--dry-run")
        self.assertEqual(p.returncode, 0); self.assertIn("## Role", p.stdout); self.assertFalse(os.path.exists(e.log)); self.assertFalse(os.path.exists(os.path.join(e.run, "round-1.meta")))
    def test_repair_resumes_thread_and_meters(self):
        e = Env(); self.assertEqual(e.go("--round", "1", "--kind", "full").returncode, 0)
        p = e.go("--round", "1", "--kind", "full", "--repair", "awaited id R1-F1 missing from prior")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(e.log) as f:
            argv = f.read().splitlines()[-1]
        self.assertIn("exec resume tid-123", argv); self.assertIn("--output-schema", argv); self.assertTrue(argv.endswith("-"))
        m = e.meta(); self.assertEqual(m["repair_input_tokens"], "1000"); self.assertEqual(m["repair_exit"], "0"); self.assertEqual(m["thread_id"], "tid-123"); self.assertNotIn("repair_started", m)
        self.assertTrue(os.path.exists(os.path.join(e.run, ".round-1.attempt1.json"))); self.assertTrue(os.path.exists(os.path.join(e.run, ".codex-round-1.repair.jsonl")))
    def test_failed_repair_is_preserved_with_its_own_meta(self):
        e = Env(); self.assertEqual(e.go("--round", "1", "--kind", "full").returncode, 0)
        p = e.go("--round", "1", "--kind", "full", "--repair", "x", mode="usage-limit"); self.assertEqual(p.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(e.run, ".codex-round-1.repair.jsonl")))
        for ext in ("md", "repair.jsonl", "meta"): self.assertTrue(os.path.exists(os.path.join(e.run, f".round-1.attempt2.{ext}")), ext)
        with open(os.path.join(e.run, ".round-1.attempt2.meta")) as f:
            am = dict(l.split("=", 1) for l in f.read().split())
        self.assertEqual((am["kind"], am["repair_exit"], am["thread_id"]), ("repair", "1", "tid-123")); self.assertNotIn("exit", am); self.assertNotIn("input_tokens", am)
        m = e.meta(); self.assertEqual(m["repair_exit"], "1"); self.assertNotIn("repair_started", m); self.assertEqual(m["exit"], "0"); self.assertEqual(m["input_tokens"], "1000")
    def test_failed_repair_restores_pre_repair_meta(self):
        e = Env(); self.assertEqual(e.go("--round", "1", "--kind", "full").returncode, 0)
        with open(os.path.join(e.run, "round-1.meta"), "a") as f: f.write("parse_failed=1\n")
        p = e.go("--round", "1", "--kind", "full", "--repair", "x", mode="usage-limit"); self.assertEqual(p.returncode, 1)
        m = e.meta()
        self.assertEqual(m["parse_failed"], "1"); self.assertEqual(m["repair_exit"], "1"); self.assertNotIn("repair_started", m); self.assertEqual(m["exit"], "0")
        with open(os.path.join(e.run, ".round-1.attempt2.meta")) as f:
            am = dict(l.split("=", 1) for l in f.read().split())
        self.assertEqual((am["kind"], am["repair_exit"]), ("repair", "1"))
    def test_stale_bundle_keeps_its_own_prompt(self):
        e = Env(); self.assertEqual(e.go("--round", "1", "--kind", "full").returncode, 0)
        with open(os.path.join(e.run, ".prompt-round-1.md"), "w") as f: f.write("OLD PROMPT")
        p = e.go("--round", "1", "--kind", "full"); self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(os.path.join(e.run, ".round-1.attempt1.md")) as f: self.assertIn("OLD PROMPT", f.read())
        with open(os.path.join(e.run, ".prompt-round-1.md")) as f: self.assertNotIn("OLD PROMPT", f.read())
