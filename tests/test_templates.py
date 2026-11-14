import importlib.util, os, re, sys, tempfile, unittest
HERE = os.path.dirname(__file__); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "bin")); import refine_lib as L

def _load_assemble():
    spec = importlib.util.spec_from_file_location("ap", os.path.join(ROOT, "bin", "assemble-prompt.py"))
    ap = importlib.util.module_from_spec(spec); spec.loader.exec_module(ap)
    return ap

class TemplateTest(unittest.TestCase):
    def test_prior_sentence_is_in_the_brief_output_format_section(self):
        # assemble-prompt.py's confirm branch replaces PRIOR_SENTENCE by exact match (finding 4); if the
        # template's wording ever drifts from this constant, the confirm prompt would silently keep the
        # round-1 sentence instead of the confirm one, so this coupling needs an explicit guard.
        ap = _load_assemble()
        with open(os.path.join(ROOT, "brief-template.md")) as f:
            t = f.read()
        secs = [s for s in re.split(r"(?m)^(?=## )", t) if s.strip()]
        out_fmt = next(s for s in secs if s.startswith("## Output format"))
        self.assertIn(ap.PRIOR_SENTENCE, out_fmt)
    def test_brief_sections_and_markers(self):
        with open(os.path.join(ROOT, "brief-template.md")) as f:
            t = f.read()
        secs = [s for s in re.split(r"(?m)^(?=## )", t) if s.strip()]
        heads = [s.split("\n", 1)[0] for s in secs]
        self.assertEqual(heads, ["## Role", "## What to review", "## What to check, in priority order", "## Reading manifest",
                                 "## Constraints", "## Fixed decisions", "## Output format (strict)", "## Severities"])
        marked = [s.split("\n", 1)[0] for s in secs if s.split("\n")[1].strip() == "<!-- reuse -->"]
        self.assertEqual(marked, ["## Role", "## Constraints", "## Fixed decisions", "## Output format (strict)", "## Severities"])
        for kind in ("spec", "plan", "impl"): self.assertIn(f"{{{{checklist:{kind}}}}}", t)
    def test_response_and_ruling_templates_complete_when_filled(self):
        for name in ("response-template.md", "ruling-template.md"):
            with open(os.path.join(ROOT, name)) as f:
                t = f.read()
            t = t.replace("{{files}}", "- docs/x.md")
            t = re.sub(r"\{\{[^}]+\}\}", "text", t)
            t = "\n".join(l for l in t.splitlines() if l.strip() != "<!-- pending -->")   # the complete form drops the pending marker
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                f.write(t)
                p = f.name
            self.assertEqual(L.record_state(p), "complete", name)
        with open(os.path.join(ROOT, "ruling-template.md")) as f:
            t = f.read()
        self.assertIn("<!-- pending -->", t)   # the pending form is documented in the template
