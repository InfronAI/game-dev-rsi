"""Run an offline, explicitly scripted creator through the public RSI CLI."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/relay-vault"


def cli(*args):
    p = subprocess.run([sys.executable, str(ROOT/"tools/rsi.py"), *map(str, args)],
                       text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return json.loads(p.stdout)


def generate(req):
    workspace = Path(req["workspace"])
    module = workspace / "logic.mjs"
    if req["round"] == 1:
        for file in (Path(req["case_dir"])/"assets/reference").iterdir():
            shutil.copyfile(file, workspace/file.name)
        text = module.read_text().replace("requiredRelays = 2", "requiredRelays = 1").replace("wallCost = 0", "wallCost = 1")
        change = "Seed an early exit and a collision energy penalty in the starter."
    else:
        text = module.read_text()
        strategy = req["plan"]["strategy"]
        rules = {"exit-rule": ("requiredRelays = 1", "requiredRelays = 2"),
                 "wall-cost": ("wallCost = 1", "wallCost = 0")}
        old, new = rules[strategy]
        if text.count(old) != 1 and text.count(new) != 1:
            raise RuntimeError("Planned change does not apply to the selected baseline")
        text = text.replace(old, new)
        change = req["plan"]["actions"][0]["change"]
    module.write_text(text)
    return {"summary": change, "changes": [change]}


def review(req):
    reviews, issues = [], []
    for sample in req["simulation"]["samples"]:
        ref = sample["evidence"][0]["path"]
        evidence = json.loads((Path(req["evidence_dir"])/ref).read_text())
        failed = evidence["first_difference"] is not None
        ratios = evidence["ratios"]
        dims = {key: {"score": ratio*100, "evidence": [ref], "reason": f"Matching checkpoint fraction: {ratio:.4f}"}
                for key, ratio in ratios.items()}
        reason = "All checkpoints match."
        if failed:
            first = evidence["checkpoints"][evidence["first_difference"]]
            reason = f"First mismatch at input {first['step']} ({first['input']}): {', '.join(first['different'])}."
            issues.append({"id": evidence["route"], "dimension": "movement" if ratios["movement"]<1 else "resources",
                           "severity": "major", "description": reason, "reproduce": f"Replay {sample['id']}.", "evidence": [ref]})
        gate = {"status": "fail" if failed else "pass", "evidence": [ref], "reason": reason}
        reviews.append({"sample_id": sample["id"], "dimensions": dims, "gates": {"transition_parity": gate}})
    return {"reviews": reviews, "issues": issues, "summary": f"{len(issues)} routes differ from the reference."}


def plan(req):
    issues = req["judgement"]["issues"]
    selected = [i for i in issues if i["dimension"] == "movement"]
    if selected:
        strategy, change = "exit-rule", "Require both relays before accepting a move into the exit."
    elif issues:
        selected = issues
        strategy, change = "wall-cost", "Preserve power on a rejected move."
    else:
        strategy, change = "extra-routes", "Try new input sequences in a separate evaluation."
    return {"hypothesis": change, "strategy": strategy, "stop_the_line": bool(issues), "expected_gain_points": 0,
            "actions": [{"addresses": [i["id"] for i in selected], "change": change,
                         "expected_effect": "Keep accepted routes stable and remove the observed discrepancy.",
                         "validation": "Replay both public suites and compare each state."}]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT/"experiments")
    p.add_argument("--run-id", default="demo")
    p.add_argument("--resume", type=Path, help="Continue an existing scripted session")
    args = p.parse_args()
    if args.resume:
        exp = args.resume.resolve()
        status = cli("status", "--experiment", exp)
        if status["identity"]["agent"] != "scripted-demo" or status["identity"]["model"] != "none":
            raise ValueError("Only scripted demo sessions can be resumed with this driver")
    else:
        exp = Path(cli("init", "--case", CASE, "--agent", "scripted-demo", "--model", "none",
                       "--output", args.output.resolve(), "--run-id", args.run_id, "--max-rounds", 3)["experiment"])
    while True:
        handoff = cli("next", "--experiment", exp)
        if handoff["status"] == "completed":
            break
        if handoff["status"] != "requires_action":
            raise RuntimeError(str(handoff))
        req = json.loads(Path(handoff["request"]).read_text())
        if req["stage"] == "simulation":
            collected = cli("simulate", "--experiment", exp)
            if "response" not in collected:
                raise RuntimeError(str(collected))
            path = Path(collected["response"])
        else:
            response = {"generation": generate, "judge": review, "planning": plan}[req["stage"]](req)
            path = Path(req["response_path"])
            path.write_text(json.dumps(dict(response, request_id=req["request_id"])))
        cli("submit", "--experiment", exp, "--response", path)
    summary = json.loads((exp/"summary.json").read_text())
    print(json.dumps({"experiment": str(exp), "scores": [r["score"] for r in summary["curve"]],
                      "best_round": summary["best_round"], "stop_reason": summary["stop_reason"]}, indent=2))


if __name__ == "__main__":
    main()
