#!/usr/bin/env python3
"""Records and local tools for RSI performed by the Agent loading this project; no model orchestration."""
import argparse
import json
import sys
from pathlib import Path

from rsi_engine.contracts import ContractError, case_contract, digest, read, tree
from rsi_engine.doctor import diagnose
from rsi_engine.engine import Runner, initialize, locked

ROOT = Path(__file__).resolve().parents[1]


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate-case", help="validate a portable creation task")
    v.add_argument("case", type=Path)
    catalog = sub.add_parser("cases", help="discover independent task packages")
    catalog.add_argument("--root", type=Path, default=ROOT / "cases")
    d = sub.add_parser("doctor", help="check local case dependencies without installing or invoking an Agent")
    source = d.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", type=Path)
    source.add_argument("--experiment", type=Path)
    i = sub.add_parser("init", help="freeze case and owner identity; hand generation to the loading Agent")
    i.add_argument("--case", type=Path, required=True)
    i.add_argument("--identity", type=Path, help="metadata JSON only; never invocation configuration")
    i.add_argument("--agent", help="actual loading Agent, used without --identity")
    i.add_argument("--model", help="actual model ID, used without --identity")
    i.add_argument("--agent-version", default="unknown")
    i.add_argument("--model-version", default="unknown")
    i.add_argument("--reasoning-effort", default="unknown")
    i.add_argument("--tool", action="append", default=[], help="enabled tool; repeat for multiple tools")
    i.add_argument("--run-id", required=True)
    i.add_argument("--output", type=Path, default=ROOT / "experiments")
    i.add_argument("--initial-artifact", type=Path, help="explicit warm start from a previous work")
    i.add_argument("--max-rounds", type=int, default=30)
    i.add_argument("--max-wall-seconds", type=int, default=28800)
    i.add_argument("--max-stage-attempts", type=int, default=3)
    for name, help_text in [
        ("next", "write the next stage request for the loading Agent"),
        ("submit", "validate and save the loading Agent's current stage response"),
        ("simulate", "collect local case evidence; requires owner inspection and submit afterwards"),
        ("status", "verify immutable inputs and show progress"),
        ("block", "record a concrete blocker encountered by the loading Agent"),
        ("report", "rebuild this run's artifact-first SHOWCASE.md"),
        ("resume", "resume after repairing a local simulation blocker")]:
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--experiment", type=Path, required=True)
        if name == "submit":
            s.add_argument("--response", type=Path, required=True)
        if name == "block":
            s.add_argument("--reason", required=True)
    listing = sub.add_parser("list", help="list generation sessions by agent/model/case")
    listing.add_argument("--output", type=Path, default=ROOT / "experiments")
    gallery = sub.add_parser("showcase", help="build a local gallery of works and their RSI histories")
    gallery.add_argument("--experiments", type=Path, default=ROOT / "experiments")
    gallery.add_argument("--destination", type=Path, default=ROOT / "showcase")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "validate-case":
            c, _, _ = case_contract(args.case)
            result = {"valid": True, "case_id": c["id"], "hash": digest(tree(args.case))}
        elif args.command == "cases":
            result = []
            for manifest in sorted(args.root.glob("*/case.json")):
                try:
                    c, _, datasets = case_contract(manifest.parent)
                    from rsi_engine.contracts import expected_samples
                    result.append({"case_id": c["id"], "title": c["title"], "path": str(manifest.parent.resolve()),
                                   "samples": {k: len(expected_samples(v)) for k, v in datasets.items()},
                                   "local_collector": "argv" in c["simulation"]})
                except (OSError, ValueError, KeyError, TypeError) as e:
                    result.append({"path": str(manifest.parent), "error": str(e)})
        elif args.command == "doctor":
            result = diagnose(Runner(args.experiment).exp / "case" if args.experiment else args.case)
        elif args.command == "init":
            if args.identity:
                if args.agent or args.model or args.tool or any(getattr(args, k) != "unknown" for k in
                        ("agent_version", "model_version", "reasoning_effort")):
                    raise ContractError("use either --identity or direct identity metadata flags")
                identity = read(args.identity)
            else:
                identity = {"schema_version": 1, "agent": args.agent, "model": args.model,
                            "agent_version": args.agent_version, "model_version": args.model_version,
                            "reasoning_effort": args.reasoning_effort, "tools": args.tool, "parameters": {}}
            budget = {k: getattr(args, k) for k in ("max_rounds", "max_wall_seconds", "max_stage_attempts")}
            exp = initialize(args.case, identity, args.output, args.run_id, budget, args.initial_artifact)
            result = {"experiment": str(exp), "next": str(exp / "NEXT.md")}
        elif args.command == "list":
            result = []
            for p in sorted(args.output.glob("*/*/*/*/state.json")):
                try:
                    s, owner = read(p), read(p.parent / "identity.json")
                    result.append({"experiment": str(p.parent), "agent": owner["agent"], "model": owner["model"],
                                   "case": s["case_id"], "status": s["status"], "stage": s["stage"],
                                   "round": s["round"], "best_round": s["best_round"]})
                except (OSError, ValueError, KeyError, TypeError) as e:
                    result.append({"experiment": str(p.parent), "status": "invalid_state", "error": str(e)})
        elif args.command == "showcase":
            from rsi_engine.showcase import build_gallery
            result = build_gallery(args.experiments, args.destination)
        elif args.command == "status":
            r = Runner(args.experiment)
            result = {k: r.s[k] for k in ("status", "stage", "round", "best_round", "stop_reason", "pending_stop", "usage")}
            result["identity"] = r.identity
        else:
            with locked(args.experiment):
                r = Runner(args.experiment, read_only=args.command == "report")
                if args.command == "next": result = r.prepare()
                elif args.command == "submit": result = r.submit(read(args.response))
                elif args.command == "simulate": result = r.simulate()
                elif args.command == "block": result = r.block(args.reason)
                elif args.command == "resume": result = r.resume()
                elif args.command == "report":
                    r.report()
                    result = {"showcase": str(r.exp / "SHOWCASE.md"), "summary": str(r.exp / "summary.json")}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if isinstance(result, dict) and (result.get("error") or result.get("ready") is False) else 0
    except (ContractError, OSError, KeyError, ValueError, TypeError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
