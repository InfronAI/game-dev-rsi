import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, ok=True):
    result = subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, text=True, capture_output=True)
    if ok and result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result


class WorkflowTests(unittest.TestCase):
    def test_demo_gallery_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            info = json.loads(run("examples/demo.py", "--output", base/"runs").stdout)
            exp = Path(info["experiment"])
            self.assertEqual(info["scores"], [83.452381, 89.071429, 100.0])
            self.assertEqual((info["best_round"], info["stop_reason"]), (3, "round_budget_exhausted"))
            expected = json.loads((ROOT/"docs/demo-baseline.json").read_text())
            summary = json.loads((exp/"summary.json").read_text())
            self.assertEqual(summary["case_hash"], expected["case_hash"])
            for item in expected["rounds"]:
                self.assertEqual({key: summary["curve"][item["round"]-1][key] for key in item}, item)
            for n in range(1, 4):
                rd = exp/"rounds"/f"round-{n:04d}"
                for stage in ("generation","simulation","judge","planning"):
                    self.assertTrue((rd/(stage+".json")).is_file())
                self.assertEqual(len(json.loads((rd/"simulation.json").read_text())["samples"]), 7)
            run("tools/rsi.py", "showcase", "--experiments", base/"runs", "--destination", base/"gallery")
            catalog = json.loads((base/"gallery/catalog.json").read_text())
            self.assertFalse(catalog["errors"])
            for rd in catalog["runs"][0]["rounds"]:
                for sample in rd["evidence"]:
                    self.assertTrue((base/"gallery"/sample["href"]).is_file())
            self.assertEqual(json.loads(run("examples/demo.py","--resume",exp).stdout), info)
            original = exp/"rounds/round-0001/artifact/logic.mjs"
            original.write_text(original.read_text()+"\n// drift\n")
            self.assertNotEqual(run("tools/rsi.py","status","--experiment",exp,ok=False).returncode,0)

    def test_stale_response_leaves_generation_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = json.loads(run("tools/rsi.py","init","--case","cases/relay-vault","--agent","unit",
                                 "--model","none","--run-id","stale","--output",tmp).stdout)["experiment"]
            response = Path(tmp)/"wrong.json"
            response.write_text('{"request_id":"wrong","summary":"test","changes":[]}')
            self.assertNotEqual(run("tools/rsi.py","submit","--experiment",exp,"--response",response,ok=False).returncode,0)
            self.assertEqual(json.loads(run("tools/rsi.py","status","--experiment",exp).stdout)["stage"], "generation")
