import json, os, unittest
HERE = os.path.dirname(__file__)
SCHEMA = os.path.join(HERE, "..", "review.schema.json")

class SchemaTest(unittest.TestCase):
    def test_schema_shape(self):
        with open(SCHEMA) as f:
            s = json.load(f)
        self.assertEqual(s["type"], "object")
        self.assertFalse(s["additionalProperties"])
        self.assertEqual(set(s["required"]), {"verdict", "findings", "prior", "verified", "not_verified"})
        self.assertEqual(s["properties"]["verdict"]["enum"], ["changes requested", "ready with P2s", "ready"])
        f = s["properties"]["findings"]["items"]
        self.assertEqual(set(f["required"]), {"severity", "title", "claim", "evidence", "why", "fix"})
        self.assertEqual(f["properties"]["severity"]["enum"], ["P0", "P1", "P2", "P3"])
        p = s["properties"]["prior"]["items"]
        self.assertEqual(set(p["required"]), {"id", "result", "note"})
        self.assertEqual(p["properties"]["result"]["enum"], ["resolved", "withdrawn", "still open"])
