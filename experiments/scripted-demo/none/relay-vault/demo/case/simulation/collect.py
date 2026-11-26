"""Collect paired state evidence using the same module as the browser game."""
import json
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELDS = {"movement": ["x", "y", "phase"], "resources": ["power", "relays"]}


def replay(module, actions):
    result = subprocess.run(["node", str(HERE / "run-route.mjs"), str(module)],
                            input=json.dumps(actions), capture_output=True, text=True,
                            check=True, timeout=5)
    return json.loads(result.stdout)


def collect(req):
    root = Path(req["evidence_dir"])
    result = {"request_id": req["request_id"], "confounds": [], "diagnostic_only": False,
              "environment": {"collector": "relay-state-v1", "python": platform.python_version(),
                              "node": subprocess.check_output(["node", "--version"], text=True).strip()},
              "samples": []}
    for sample in req["dataset"]["samples"]:
        actions = sample["payload"]["actions"]
        for repeat in range(1, sample.get("repeats", 1) + 1):
            sample_id = sample["id"]
            expected = replay(HERE.parent / "assets/reference/logic.mjs", actions)
            error = None
            try:
                actual = replay(Path(req["artifact_dir"]) / "logic.mjs", actions)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
                actual = []
                error = str(exc)
                if isinstance(exc, subprocess.CalledProcessError):
                    error = exc.stderr[-2000:] or error
            checkpoints = []
            for i, state in enumerate(expected):
                observed = actual[i] if i < len(actual) else {}
                differences = [key for keys in FIELDS.values() for key in keys if observed.get(key) != state[key]]
                checkpoints.append({"step": i, "input": actions[i-1] if i else "start",
                                    "expected": state, "observed": observed, "different": differences})
            scores = {k: sum(not set(keys).intersection(c["different"]) for c in checkpoints) / len(checkpoints)
                      for k, keys in FIELDS.items()}
            receipt = {"route": sample_id, "error": error, "checkpoints": checkpoints, "ratios": scores,
                       "first_difference": next((c["step"] for c in checkpoints if c["different"]), None)}
            filename = f"{sample_id}-{repeat}.json"
            (root / filename).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")
            view = filename.replace(".json", ".html")
            template = (HERE / "replay.html").read_text(encoding="utf8")
            payload = json.dumps(receipt).replace("<", r"\u003c")
            (root / view).write_text(template.replace("<!--DATA-->", payload), encoding="utf8")
            result["samples"].append({"id": f"{sample_id}:{repeat}",
                "status": "completed" if receipt["first_difference"] is None else "artifact_failure",
                "metrics": scores, "evidence": [{"kind": "runtime", "path": filename}, {"kind": "diagnostic", "path": view}]})
    return result


if __name__ == "__main__":
    request, response = map(Path, sys.argv[1:])
    response.write_text(json.dumps(collect(json.loads(request.read_text())), indent=2) + "\n")
