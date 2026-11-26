"""Durable records for RSI performed by the Agent that loads this project."""
import contextlib
import copy
import datetime
import json
import os
import shutil
import socket
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .contracts import (ContractError, case_contract, development_dataset, digest, file_hash,
                        identifier, judge_contract, number, plan_contract, read, relative,
                        require, simulation_contract, tree, usage_contract)

UNKNOWN_USAGE = {"input_tokens": None, "output_tokens": None, "cost_usd": None}


def runner_hash():
    base = Path(__file__).resolve().parent
    return digest({p.name: file_hash(p) for p in (base / "engine.py", base / "contracts.py", base / "doctor.py", base.parent / "rsi.py")})


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def copy_tree(source, target):
    require(Path(source).is_dir(), "source directory does not exist: " + str(source))
    target.mkdir(parents=True, exist_ok=True)
    for name in tree(source):
        p = target / name
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(source) / name, p)


@contextlib.contextmanager
def locked(exp):
    # OS releases the lock if a process dies; no stale-PID guesses or lock stealing.
    with (Path(exp) / ".lock").open("a+b") as f:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                f.write(b"0")
                f.flush()
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise ContractError("experiment is in use by another runner") from e
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def identity_contract(p):
    require(isinstance(p, dict) and p.get("schema_version") == 1, "unsupported identity schema")
    required = {"schema_version", "agent", "model", "agent_version", "model_version",
                "reasoning_effort", "tools", "parameters"}
    require(set(p) == required, "identity records metadata only; adapters, judge endpoints and extra configuration are unsupported")
    for k in ("agent", "model", "agent_version", "model_version", "reasoning_effort"):
        require(isinstance(p[k], str) and p[k].strip(), "identity required (use unknown if unverifiable): " + k)
    require(isinstance(p["tools"], list) and all(isinstance(t, str) and t for t in p["tools"])
            and isinstance(p["parameters"], dict), "tools/parameters required")

def slug(value):
    import re
    base = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-.")[:65] or "unknown"
    # Preserve readable simple IDs; suffix transformed ones to prevent slash/hyphen collisions.
    return base if base == value else base + "-" + digest(value)[:8]


def initialize(case_dir, identity, output, run_id, budget, initial_artifact=None):
    c, _, _ = case_contract(case_dir)
    identity_contract(identity)
    for key in ("max_rounds", "max_wall_seconds", "max_stage_attempts"):
        number(budget[key], key, 1)
    require(type(budget["max_rounds"]) is int and type(budget["max_stage_attempts"]) is int, "integer budgets required")
    require(set(budget) == {"max_rounds", "max_wall_seconds", "max_stage_attempts"}, "unsupported session limits")
    if initial_artifact:
        require(Path(initial_artifact).is_dir(), "initial artifact directory is missing")
        require(set(c["artifact"]["required_files"]) <= set(tree(initial_artifact)), "initial artifact lacks required deliverable")
    identifier(run_id)
    exp = Path(output).resolve() / slug(identity["agent"]) / slug(identity["model"]) / c["id"] / run_id
    exp.mkdir(parents=True, exist_ok=False)
    try:
        copy_tree(case_dir, exp / "case")
        write(exp / "identity.json", identity)
        frozen = tree(exp / "case")
        state = {"schema_version": 1, "experiment_id": uuid.uuid4().hex, "run_id": run_id, "case_id": c["id"],
                 "created_at": now(), "created_epoch": time.time(), "updated_at": now(),
                 "case_hash": digest(frozen), "case_files": frozen, "identity_hash": digest(identity),
                 "budget": budget, "budget_hash": digest(budget), "runner_hash": runner_hash(), "status": "active", "stage": "generation", "round": 1,
                 "best_round": None, "history": [], "streak": [], "events": [], "sealed": {},
                 "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "unknown_stages": 0},
                 "attempts": {}, "failure_streaks": {}, "usage_ledger": {}, "pending_attempt": None, "stop_reason": None, "pending_stop": None, "origin": "cold_start"}
        if initial_artifact:
            copy_tree(initial_artifact, exp / "initial")
            state["initial_files"] = tree(exp / "initial")
            state["origin"] = "warm_start"
        (exp / "rounds" / "round-0001" / "workspace").mkdir(parents=True)
        if initial_artifact:
            copy_tree(exp / "initial", exp / "rounds" / "round-0001" / "workspace")
        event(state, "initialized", {"origin": state["origin"]})
        write(exp / "state.json", state)
        runner = Runner(exp)
        runner.prepare()
        runner.report()
    except Exception:
        # Keep a failed initialization for diagnosis; never silently create a usable half-run.
        write(exp / "INIT_FAILED.json", {"at": now(), "message": "initialization failed"})
        raise
    return exp


def event(state, kind, data):
    entry = {"seq": len(state["events"]) + 1, "at": now(), "kind": kind, "data": data,
             "previous_hash": state["events"][-1]["hash"] if state["events"] else None}
    entry["hash"] = digest(entry)
    state["events"].append(entry)
    state["updated_at"] = now()


def paired_progress(current, baseline):
    require(set(current) == set(baseline), "paired sample IDs differ")
    deltas = [current[k] - baseline[k] for k in sorted(current)]
    return {"mean_delta": sum(deltas) / len(deltas), "delta_range": [min(deltas), max(deltas)],
            "samples": len(deltas), "method": "self-review-sample-differences"}

class Runner:
    def __init__(self, exp, read_only=False):
        self.exp = Path(exp).resolve()
        self.read_only = read_only
        self.report_warning = None
        self.s = read(self.exp / "state.json")
        self.identity = read(self.exp / "identity.json")
        self.case, self.rubric, self.datasets = case_contract(self.exp / "case")
        self.dataset = development_dataset(self.datasets)
        self.verify()

    def verify(self):
        require(self.read_only or self.s.get("runner_hash") == runner_hash(),
                "runner code changed; artifacts remain viewable, but continuing requires a new experiment")
        require(self.s.get("budget_hash") == digest(self.s["budget"]), "frozen budget changed")
        require(digest(tree(self.exp / "case")) == self.s["case_hash"], "frozen case changed; create a new experiment")
        require(digest(self.identity) == self.s["identity_hash"], "frozen agent-model identity changed")
        prev = None
        for e in self.s["events"]:
            require(e["previous_hash"] == prev and e["hash"] == digest({k: v for k, v in e.items() if k != "hash"}),
                    "event chain corrupted")
            prev = e["hash"]
        for name, sha in self.s["sealed"].items():
            require(file_hash(relative(self.exp, name)) == sha, "sealed file changed: " + name)
        for h in self.s["history"]:
            gen = read(self.round_dir(h["round"]) / "generation.json")
            require(tree(self.round_dir(h["round"]) / "artifact") == gen["artifact_files"], "artifact changed")
        # Also check the current, not-yet-judged candidate.
        gp = self.round_dir() / "generation.json"
        if gp.relative_to(self.exp).as_posix() in self.s["sealed"]:
            require(tree(self.round_dir() / "artifact") == read(gp)["artifact_files"], "candidate changed after generation")
        if self.s["origin"] == "warm_start":
            require(tree(self.exp / "initial") == self.s["initial_files"], "initial artifact changed")

    def save(self):
        require(not self.read_only, "read-only session cannot change state")
        write(self.exp / "state.json", self.s)
        try:
            self.report()
            self.report_warning = None
        except (OSError, ValueError, KeyError, TypeError) as e:
            # A derived report must not make a committed stage look failed or trigger duplicate stage submission.
            self.report_warning = str(e)
            try:
                write(self.exp / "SHOWCASE_ERROR.json", {"at": now(), "error": str(e), "remedy": "run report again"})
            except OSError:
                pass

    def round_dir(self, n=None):
        return self.exp / "rounds" / f"round-{n or self.s['round']:04d}"

    def stage_dir(self):
        return self.round_dir()

    def seal(self, path, value=None):
        if value is not None:
            write(path, value)
        self.s["sealed"][path.relative_to(self.exp).as_posix()] = file_hash(path)

    def role(self):
        return self.s["stage"]

    def artifact_dir(self):
        return self.round_dir() / "artifact"

    def budget_reason(self):
        if time.time() - self.s["created_epoch"] >= self.s["budget"]["max_wall_seconds"]:
            return "wall_budget_exhausted"
        return None

    def finish_loop(self, reason):
        self.s.update(stop_reason=reason, pending_stop=None, status="completed", stage="done")
        event(self.s, "loop_stopped", {"reason": reason, "selected_round": self.s["best_round"]})

    def check_budget(self):
        if self.s["status"] == "active" and self.budget_reason():
            self.finish_loop(self.budget_reason())
            self.save()

    def request_id(self):
        context = {"experiment": self.s["experiment_id"], "runner": self.s["runner_hash"],
                   "budget": self.s["budget_hash"], "run": self.s["run_id"], "case": self.s["case_hash"], "identity": self.s["identity_hash"],
                   "round": self.s["round"], "stage": self.s["stage"]}
        if self.role() in ("simulation", "judge"):
            context["artifact"] = read(self.artifact_dir().parent / "generation.json")["artifact_hash"]
        if self.role() == "judge":
            context["simulation"] = digest(read(self.stage_dir() / "simulation.json"))
        if self.role() == "planning":
            context["judge"] = digest(read(self.round_dir() / "judge.json"))
        if self.role() == "generation" and self.s["round"] > 1:
            context["plan"] = digest(read(self.round_dir(self.s["round"] - 1) / "planning.json"))
        return digest(context)

    def prepare(self):
        require(not self.read_only, "read-only session cannot prepare a new stage")
        self.check_budget()
        if self.s["status"] != "active":
            (self.exp / "NEXT.md").write_text(
                f"# RSI handoff\n\nStatus: {self.s['status']}. Stop reason: {self.s['stop_reason']}.\n\n"
                "Read SHOWCASE.md and state.json. Completed runs cannot start new generations; "
                "blocked runs need infrastructure repair and resume.\n", encoding="utf-8")
            return {"status": self.s["status"], "reason": self.s["stop_reason"], "report": str(self.exp / "SHOWCASE.md")}
        stage, role = self.s["stage"], self.role()
        rd = self.stage_dir()
        rd.mkdir(parents=True, exist_ok=True)
        evidence = rd / "evidence"
        evidence.mkdir(exist_ok=True)
        request = {"schema_version": 1, "request_id": self.request_id(), "run_id": self.s["run_id"], "stage": stage,
                   "round": self.s["round"], "case_hash": self.s["case_hash"],
                   "identity": self.identity, "case_dir": str(self.exp / "case"),
                   "workspace": str(self.round_dir() / "workspace"),
                   "artifact_dir": str(self.artifact_dir()), "evidence_dir": str(evidence),
                   "split": "development", "dataset": self.dataset, "datasets": self.datasets,
                   "review_mode": "owner_self_review",
                   "response_path": str(rd / (stage + ".response.json")),
                   "budget": self.s["budget"], "usage_so_far": self.s["usage"],
                   "budget_remaining": self.remaining_budget(),
                   "instructions": self.instructions(role)}
        if role in ("simulation", "judge"):
            g = read(self.artifact_dir().parent / "generation.json")
            request["artifact_hash"] = g["artifact_hash"]
            request["rubric"] = self.rubric
        if role == "judge":
            request["simulation"] = read(rd / "simulation.json")
        if role == "planning":
            request["judgement"] = read(rd / "judge.json")
            request["incumbent_round"] = self.s["best_round"]
            request["pending_stop"] = self.s["pending_stop"]
        if role == "generation" and self.s["round"] > 1:
            request["plan"] = read(self.round_dir(self.s["round"] - 1) / "planning.json")
            request["previous_judgement"] = read(self.round_dir(self.s["round"] - 1) / "judge.json")
        path = rd / (stage + ".request.json")
        write(path, request)
        # Context is runner-owned, but never contains fabricated generated artifacts or scores.
        handoff = (f"# RSI handoff\n\nStage: `{stage}`; round: {self.s['round']}; case: `{self.s['case_id']}`.\n\n"
                   f"Read `AGENTS.md`, then `{path}`.\n\nEcho request_id in your response.\n\n{request['instructions']}\n\n"
                   f"Submit: `python3 tools/rsi.py submit --experiment '{self.exp}' --response '{request['response_path']}'`\n")
        (self.exp / "NEXT.md").write_text(handoff, encoding="utf-8")
        return {"status": "requires_action", "stage": stage, "request": str(path), "response": request["response_path"],
                "report_warning": self.report_warning}

    def remaining_budget(self):
        b, u = self.s["budget"], self.s["usage"]
        deadline = self.s["created_epoch"] + b["max_wall_seconds"]
        return {"rounds": max(0, b["max_rounds"] - self.s["round"] + 1),
                "wall_seconds": max(0, round(deadline - time.time(), 3)),
                "usage_complete": u["unknown_stages"] == 0}

    @staticmethod
    def instructions(role):
        return {
            "generation": "You are the loading Agent and the creator. Read frozen case goals, prompt, rubric and BOTH sample sets. "
                          "Implement in workspace only, following the previous plan. Return summary, changes and optional usage. "
                          "Do not stop after the first demo: submit, simulate, inspect, self-review, plan and regenerate.",
            "simulation": "You perform this stage using your available tools. The optional simulate command collects case-specific local evidence only. "
                          "Inspect it and add any task-specific runtime evidence before submitting; it does not review or advance the stage. "
                          "Keep the artifact and case unchanged. Return request_id, all samples, environment, confounds, diagnostic_only. "
                          "If tooling is unavailable report the actual blocker; never invent observations.",
            "judge": "Self-review the artifact and ALL collected evidence using the frozen rubric. You are also the creator, not an independent judge. "
                     "Return reviews [{sample_id, dimensions:{id:{score,evidence:[path],reason}}, gates:{id:{status,evidence:[path],reason}}}], "
                     "issues [{id,severity,dimension,description,reproduce,evidence}], summary and optional usage. "
                     "References are relative to evidence_dir. Keep unobserved gates unknown, and score quality, not effort. "
                     "Never fabricate human reviews. Feedback from both sets informs the next generation.",
            "planning": "Form a concrete improvement hypothesis from your self-review and best available artifact. Return hypothesis, strategy, "
                        "stop_the_line, expected_gain_points, actions:[{addresses:[issue_id],change,expected_effect,validation}] and optional usage. "
                        "Fix failed/unknown gates first, then the most consequential weakness; change strategy after repeated poor gains. "
                        "Keep the criteria fixed. If pending_stop is set, record remaining opportunities; this plan is saved without generating another round."
        }[role]

    def account(self, usage, key=None):
        usage = usage_contract(usage)
        key = key or "owner:" + self.request_id()
        if key not in self.s["usage_ledger"]:
            self.s["usage_ledger"][key] = copy.deepcopy(usage)
        ledger = list(self.s["usage_ledger"].values())
        self.s["usage"] = {k: sum(v[k] or 0 for v in ledger) for k in UNKNOWN_USAGE}
        self.s["usage"]["unknown_stages"] = sum(any(v[k] is None for k in UNKNOWN_USAGE) for v in ledger)

    def submit(self, response):
        require(not self.read_only, "read-only session cannot accept submissions")
        require(isinstance(response, dict), "stage response must be a JSON object")
        self.verify()
        original_request = self.request_id() if self.s["status"] == "active" else None
        self.check_budget()
        changed = self.s["status"] != "active" or self.request_id() != original_request
        if changed and original_request and response.get("request_id") == original_request:
            self.account(response.get("usage", UNKNOWN_USAGE.copy()), key="owner:" + original_request)
            event(self.s, "response_after_budget", {"request_id": original_request, "scored": False})
            self.save()
        require(self.s["status"] == "active", "experiment is not active")
        stage, role, rd = self.s["stage"], self.role(), self.stage_dir()
        require(response.get("request_id") == self.request_id(), "stale/missing request_id; response belongs to another stage or artifact")
        require(not self.s["pending_attempt"], "a local simulation is pending; recover with simulate before submission")
        value = copy.deepcopy(response)
        value.setdefault("usage", UNKNOWN_USAGE.copy())
        # Validate BEFORE accounting or committing any transition.
        if role == "generation":
            require(value["summary"] and isinstance(value["changes"], list), "generation summary/changes required")
            workspace = self.round_dir() / "workspace"
            files = tree(workspace)
            require(set(self.case["artifact"]["required_files"]) <= set(files), "required deliverable missing")
            if not self.case["artifact"].get("allow_extra_files", True):
                require(set(files) == set(self.case["artifact"]["required_files"]), "delivery file-set constraint violated")
            require(sum((workspace / x).stat().st_size for x in files) <= self.case["artifact"]["max_bytes"], "artifact too large")
            require(all((workspace / x).stat().st_size > 0 for x in files), "empty artifact")
            value.update(artifact_files=files, artifact_hash=digest(files))
        elif role == "simulation":
            ds = self.dataset
            value["evidence_registry"] = simulation_contract(value, self.case, ds, rd / "evidence")
            if any(s["status"] == "infra_failure" for s in value["samples"]):
                raise ContractError("infrastructure failure; retain receipt and retry, do not score as model failure")
            environment_hash = digest(value["environment"])
            if self.s.get("environment_hash") and self.s["environment_hash"] != environment_hash:
                value["confounds"] = list(value["confounds"]) + ["environment_changed_from_initial_simulation"]
            value["artifact_hash"] = read(self.artifact_dir().parent / "generation.json")["artifact_hash"]
            value["case_hash"] = self.s["case_hash"]
        elif role == "judge":
            sim = read(rd / "simulation.json")
            value["assessment"] = judge_contract(value, sim, self.rubric)
            value["reviewer"] = {"mode": "owner_self_review", "agent": self.identity["agent"], "model": self.identity["model"]}
        else:
            plan_contract(value, read(rd / "judge.json"))
        self.account(value["usage"])
        value["accepted_at"] = now()
        if role == "generation":
            artifact = self.round_dir() / "artifact"
            if artifact.exists():
                # Uncommitted output from a crashed submit; never remove a committed artifact.
                require((rd / "generation.json").relative_to(self.exp).as_posix() not in self.s["sealed"], "already frozen")
                shutil.rmtree(artifact)
            copy_tree(self.round_dir() / "workspace", artifact)
            self.seal(rd / "generation.json", value)
            self.s["stage"] = "simulation"
        elif role == "simulation":
            self.s.setdefault("environment_hash", digest(value["environment"]))
            for name in value["evidence_registry"]:
                self.seal(rd / "evidence" / name)
            self.seal(rd / "simulation.json", value)
            self.s["stage"] = "judge"
        elif role == "judge":
            self.seal(rd / "judge.json", value)
            self.assess_round(value)
        else:
            self.seal(rd / "planning.json", value)
            if self.s["pending_stop"]:
                self.finish_loop(self.s["pending_stop"])
            else:
                parent = self.s["best_round"] or self.s["round"]
                self.s["round"] += 1
                workspace = self.round_dir() / "workspace"
                if workspace.exists():
                    actual, expected = tree(workspace), tree(self.round_dir(parent) / "artifact")
                    require(all(expected.get(k) == v for k, v in actual.items()),
                            "new workspace contains edits incompatible with interrupted branch copy")
                copy_tree(self.round_dir(parent) / "artifact", workspace)
                self.s["stage"] = "generation"
                event(self.s, "branched_from", {"round": self.s["round"], "parent_round": parent})
        event(self.s, "stage_accepted", {"request_id": response["request_id"],"round": int(rd.name.removeprefix("round-")),
                                         "stage": stage, "response_hash": digest(value)})
        self.save()
        return self.prepare()

    def assess_round(self, judge):
        n, c = self.s["round"], self.case["convergence"]
        a = judge["assessment"]
        gen = read(self.round_dir() / "generation.json")
        sim = read(self.round_dir() / "simulation.json")
        record = {"round": n, "artifact_hash": gen["artifact_hash"], **a,
                  "environment_hash": digest(sim["environment"]), "comparison": None, "strategy": "initial",
                  "usage_cumulative": copy.deepcopy(self.s["usage"]),
                  "elapsed_seconds": round(time.time() - self.s["created_epoch"], 3)}
        if n > 1:
            record["strategy"] = read(self.round_dir(n - 1) / "planning.json")["strategy"]
        best = next((h for h in self.s["history"] if h["round"] == self.s["best_round"]), None)
        stable_environment = self.s.get("environment_hash", record["environment_hash"]) == record["environment_hash"]
        record["eligible"] = a["eligible"] and stable_environment
        record["measurement_valid"] = stable_environment and not sim["confounds"] and not sim["diagnostic_only"]
        record["limitations"] = list(sim["confounds"])
        if not stable_environment:
            record["limitations"].append("environment_drift")
        if sim["diagnostic_only"]:
            record["limitations"].append("diagnostic_only")
        record["limitations"] += ["gate:" + k + ":" + v for k, v in a["gate_status"].items() if v != "pass"]
        record["limitations"] += ["sample:" + v["id"] + ":" + v["status"] for v in sim["samples"] if v["status"] != "completed"]
        record["metrics"] = {}
        for metric in self.case["metrics"]:
            values = [sample["metrics"][metric["id"]] for sample in sim["samples"]
                      if sample["metrics"][metric["id"]] is not None]
            record["metrics"][metric["id"]] = {
                "mean": sum(values) / len(values) if values else None,
                "min": min(values) if values else None, "max": max(values) if values else None,
                "observed": len(values), "total": len(sim["samples"])}
        unique = all(h["artifact_hash"] != record["artifact_hash"] for h in self.s["history"])
        comparable = bool(best and best["eligible"] and record["eligible"] and best["environment_hash"] == record["environment_hash"])
        plateau = False
        if comparable:
            comparison = paired_progress(a["sample_scores"], best["sample_scores"])
            record["comparison"] = {"baseline_round": best["round"], **comparison}
            low, high = comparison["delta_range"]
            plateau = (unique and comparison["samples"] >= c["min_samples"] and
                       -c["epsilon_points"] < low and high < c["epsilon_points"])
        record["unique_artifact"] = unique
        # Always retain a viewable best available work, even when evidence has limitations.
        if best is None or ((record["eligible"], record["measurement_valid"], a["score"]) >
                            (best["eligible"], best["measurement_valid"], best["score"])):
            self.s["best_round"] = n
        if plateau:
            self.s["streak"].append(n)
        else:
            self.s["streak"] = []
        self.s["history"].append(record)
        self.seal(self.round_dir() / "assessment.json", record)
        window = self.s["streak"][-c["patience"]:]
        strategies = {h["strategy"] for h in self.s["history"] if h["round"] in window}
        valid_rounds = sum(h["eligible"] and h["unique_artifact"] for h in self.s["history"])
        if len(window) >= c["patience"] and valid_rounds >= c["min_rounds"] and len(strategies) >= c["min_strategies"]:
            self.s["pending_stop"] = "observed_plateau"
        elif n >= self.s["budget"]["max_rounds"]:
            self.s["pending_stop"] = "round_budget_exhausted"
        elif self.budget_reason():
            self.s["pending_stop"] = self.budget_reason()
        self.s["stage"] = "planning"

    def fail_attempt(self, attempt, error):
        self.s = read(self.exp / "state.json")
        self.s["pending_attempt"] = None
        key = attempt["key"]
        self.s["failure_streaks"][key] = self.s["failure_streaks"].get(key, 0) + 1
        if self.s["failure_streaks"][key] >= self.s["budget"]["max_stage_attempts"]:
            self.s["status"] = "blocked"
            self.s["stop_reason"] = "local_simulation_failed"
        event(self.s, "simulation_failed", {"attempt_id": attempt["id"], "error": str(error)})
        self.save()
        return {"status": self.s["status"], "stage": self.s["stage"], "error": str(error),
                "attempt_id": attempt["id"], "retryable": self.s["status"] == "active"}

    def recover_attempt(self):
        attempt = self.s["pending_attempt"]
        pid = attempt.get("pid") or attempt["owner_pid"]
        if attempt["host"] != socket.gethostname():
            return {"status": "waiting", "error": "simulation belongs to another host; recover there first"}
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        except PermissionError:
            return {"status": "waiting", "pid": pid, "error": "recorded process exists but is inaccessible"}
        else:
            return {"status": "waiting", "pid": pid, "attempt_id": attempt["id"]}
        result = self.fail_attempt(attempt, "interrupted local simulation; inspect retained evidence and retry")
        write(self.exp / attempt["directory"] / "receipt.json", {**result, "status": "interrupted", "ended_at": now()})
        return result

    def simulate(self):
        """Only execute the case's local evidence collector. Never invoke an Agent or judge."""
        if self.s["pending_attempt"]:
            return self.recover_attempt()
        info = self.prepare()
        if self.s["status"] != "active":
            return info
        require(self.role() == "simulation", "simulate is available only during the simulation stage; the loading Agent performs other stages")
        spec = self.case["simulation"]
        if "argv" not in spec:
            return {**info, "next": "This case uses the loading Agent’s tools. Follow its simulation instructions, collect evidence and submit."}
        key = f"{self.s['round']}:simulation"
        count = self.s["attempts"].get(key, 0) + 1
        self.s["attempts"][key] = count
        log_dir = self.stage_dir() / "attempts" / f"simulation-{count:03d}"
        log_dir.mkdir(parents=True, exist_ok=False)
        request = read(info["request"])
        response_path, request_path = log_dir / "response.json", log_dir / "request.json"
        prefix = f"attempt-{count:03d}"
        request.update(response_path=str(response_path), evidence_dir=str(self.stage_dir() / "evidence" / prefix))
        Path(request["evidence_dir"]).mkdir(parents=True, exist_ok=False)
        write(request_path, request)
        attempt = {"id": f"{key}:{count}", "key": key, "request_id": request["request_id"],
                   "directory": log_dir.relative_to(self.exp).as_posix(), "host": socket.gethostname(),
                   "pid": None, "owner_pid": os.getpid()}
        self.s["pending_attempt"] = attempt
        event(self.s, "simulation_started", {"attempt_id": attempt["id"]})
        self.save()
        substitutions = {"case_dir": str(self.exp / "case"), "python": sys.executable,
                         "request": str(request_path), "response": str(response_path), "workspace": request["workspace"]}
        env = os.environ.copy()
        env.update(RSI_REQUEST=str(request_path), RSI_RESPONSE=str(response_path), RSI_WORKSPACE=request["workspace"],
                   RSI_EVIDENCE=request["evidence_dir"], RSI_CASE=request["case_dir"], RSI_ARTIFACT=request["artifact_dir"])
        remaining = self.s["created_epoch"] + self.s["budget"]["max_wall_seconds"] - time.time()
        timeout = max(0.01, min(spec["timeout_seconds"], remaining))
        receipt = {"attempt_id": attempt["id"], "started_at": now(), "timeout_seconds": timeout}
        try:
            argv = [v.format_map(substitutions) for v in spec["argv"]]
            receipt["argv"] = argv
            with (log_dir / "stdout.log").open("wb") as out, (log_dir / "stderr.log").open("wb") as err:
                proc = subprocess.Popen(argv, cwd=self.exp / "case", env=env, stdin=subprocess.PIPE,
                                        stdout=out, stderr=err, start_new_session=(os.name != "nt"))
                attempt["pid"] = proc.pid
                try:
                    self.save()
                    proc.communicate(json.dumps(request).encode(), timeout=timeout)
                except BaseException:
                    if proc.poll() is None:
                        if os.name != "nt":
                            os.killpg(proc.pid, signal.SIGKILL)
                        else:
                            proc.kill()
                        proc.wait()
                    raise
            receipt["exit_code"] = proc.returncode
            require(proc.returncode == 0, "simulation exited " + str(proc.returncode))
            response = read(response_path)
            require(response.get("request_id") == request["request_id"], "simulation response request_id mismatch")
            simulation_contract(response, self.case, self.dataset, request["evidence_dir"])
            require(not any(v["status"] == "infra_failure" for v in response["samples"]),
                    "simulation infrastructure failed; raw evidence retained")
            for sample in response["samples"]:
                for evidence in sample["evidence"]:
                    relative(request["evidence_dir"], evidence["path"])
                    evidence["path"] = prefix + "/" + evidence["path"]
            response.setdefault("usage", dict.fromkeys(UNKNOWN_USAGE, 0))
            collected = log_dir / "collected.response.json"
            write(collected, response)
            self.s["pending_attempt"] = None
            self.s["failure_streaks"][key] = 0
            event(self.s, "simulation_collected", {"attempt_id": attempt["id"], "response": str(collected.relative_to(self.exp))})
            self.save()
            receipt["status"] = "collected"
            return {"status": "requires_action", "stage": "simulation", "response": str(collected),
                    "next": "Inspect and supplement evidence, then submit this response. The loading Agent performs the self-review."}
        except (ContractError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired, KeyboardInterrupt) as e:
            receipt.update(status="interrupted" if isinstance(e, KeyboardInterrupt) else "failed", error=str(e))
            result = self.fail_attempt(attempt, e)
            if isinstance(e, KeyboardInterrupt):
                raise
            return result
        finally:
            receipt["ended_at"] = now()
            write(log_dir / "receipt.json", receipt)

    def block(self, reason):
        require(self.s["status"] == "active" and not self.s["pending_attempt"], "only an active idle stage can be blocked")
        require(isinstance(reason, str) and reason.strip(), "concrete blocker required")
        self.s.update(status="blocked", stop_reason="owner_blocked")
        self.s["blocker"] = {"stage": self.s["stage"], "reason": reason, "at": now()}
        event(self.s, "owner_blocked", self.s["blocker"])
        self.save()
        return self.prepare()

    def resume(self):
        require(self.s["status"] == "blocked", "only blocked runs need resume")
        self.s.update(status="active", stop_reason=None)
        self.s.pop("blocker", None)
        self.s["failure_streaks"][f"{self.s['round']}:{self.s['stage']}"] = 0
        event(self.s, "resumed", {})
        self.save()
        return self.prepare()

    def report(self):
        from .showcase import render_run
        render_run(self)
        (self.exp / "SHOWCASE_ERROR.json").unlink(missing_ok=True)
