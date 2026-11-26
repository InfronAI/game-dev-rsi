"""Portable creation tasks, observable evidence and the loading Agent's self-review."""
import hashlib
import json
import math
import re
import string
from pathlib import Path


class ContractError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise ContractError(message)


def read(path):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, "duplicate JSON key: " + k)
            out[k] = v
        return out

    def nonfinite(value):
        raise ContractError("nonfinite JSON number: " + value)

    with Path(path).open(encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=pairs, parse_constant=nonfinite)


def command_contract(argv):
    require(isinstance(argv, list) and argv and isinstance(argv[0], str) and argv[0], "nonempty argv required")
    for arg in argv:
        require(isinstance(arg, str), "argv entries must be strings")
        for _, field, spec, conversion in string.Formatter().parse(arg):
            require(field is None or (field in {"python", "case_dir", "request", "response", "workspace"}
                    and not spec and conversion is None), "unsupported argv placeholder: " + str(field))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(root, name):
    require(isinstance(name, str) and name and not Path(name).is_absolute(), "relative path required")
    require(".." not in Path(name).parts, "parent traversal forbidden")
    root = Path(root).resolve()
    target = root / name
    require(not any(p.is_symlink() for p in [target, *target.parents] if p != root.parent),
            "symlinks are not portable artifacts")
    require(root in target.resolve().parents, "path escapes root")
    return target


def tree(root):
    root = Path(root)
    excluded = {"node_modules", "__pycache__", ".git", ".DS_Store"}
    result = {}
    for p in sorted(root.rglob("*")):
        if any(x in excluded for x in p.relative_to(root).parts):
            continue
        require(not p.is_symlink(), "symlinks forbidden: " + str(p))
        if p.is_file():
            result[p.relative_to(root).as_posix()] = file_hash(p)
    return result


def number(v, label, lo=0, hi=None):
    require(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)
            and v >= lo and (hi is None or v <= hi), "invalid number: " + label)
    return v


def identifier(v):
    require(isinstance(v, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", v),
            "invalid identifier: " + str(v))
    return v


def case_contract(root):
    """Validate the common envelope; domain payloads and their checks belong to the case."""
    root = Path(root)
    c = read(root / "case.json")
    require(c["schema_version"] == 1, "unsupported case schema")
    identifier(c["id"])
    require(isinstance(c["title"], str) and c["title"].strip(), "case title required")
    require(not (root / "runs").exists(), "case cannot contain model runs")
    for key in ("objective", "prompt", "rubric", "environment", "assets"):
        require(relative(root, c[key]).exists(), "missing case file: " + key)
    rubric = read(relative(root, c["rubric"]))
    require(isinstance(rubric["scale"], list) and len(rubric["scale"]) == 2, "scale needs lower/upper bounds")
    lo, hi = rubric["scale"]
    number(lo, "scale lower", -float("inf")); number(hi, "scale upper", lo)
    require(hi > lo, "scale must have positive width")
    policy = rubric["evidence_policy"]
    number(policy["score_cap_without_observation"], "evidence cap", lo, hi)
    require(isinstance(policy["observation_kinds"], list) and policy["observation_kinds"] and
            set(policy["observation_kinds"]) <= {"artifact", "runtime", "code", "human", "diagnostic"}, "invalid evidence policy")
    dims = rubric["dimensions"]
    require(dims and len({d["id"] for d in dims}) == len(dims), "duplicate/empty dimensions")
    for d in dims:
        identifier(d["id"])
        number(d["weight"], "weight", 0, 1)
        require(isinstance(d["description"], str) and d["description"], "dimension needs description")
        require(isinstance(d["metrics"], list), "dimension metric references must be a list")
        anchors = d["anchors"]
        require(isinstance(anchors, dict) and anchors, "score anchors required")
        levels = [number(float(k), "anchor", lo, hi) for k in anchors]
        require(lo in levels and hi in levels and len(set(levels)) == len(levels)
                and all(isinstance(v, str) and v.strip() for v in anchors.values()), "anchors must describe both endpoints without duplicate levels")
    require(abs(sum(d["weight"] for d in dims) - 1) < 1e-8, "rubric weights must sum to 1")
    require(isinstance(rubric["gates"], dict) and len(set(rubric["gates"])) == len(rubric["gates"]), "invalid gates")
    for gate, description in rubric["gates"].items():
        identifier(gate)
        require(isinstance(description, str) and description.strip(), "gate description required")
    metrics = {m["id"] for m in c["metrics"]}
    require(len(metrics) == len(c["metrics"]), "duplicate metrics")
    for m in c["metrics"]:
        require(m["direction"] in ("higher", "lower") and m["unit"] and m["description"], "invalid metric")
        identifier(m["id"])
        require(isinstance(m.get("required_for_completed", False), bool), "metric requirement must be boolean")
        if m.get("required_for_completed"):
            require(m.get("target") is not None, "required metric needs a target")
        for key in ("target", "minimum", "maximum"):
            if m.get(key) is not None:
                number(m[key], "metric " + key, -float("inf"))
        if m.get("minimum") is not None and m.get("maximum") is not None:
            require(m["minimum"] <= m["maximum"], "metric bounds reversed")
    require(all(set(d["metrics"]) <= metrics for d in dims), "unknown dimension metric")
    datasets, sample_ids = {}, set()
    for split in ("validation", "test"):
        ds = read(relative(root, c["datasets"][split]))
        require(ds["split"] == split and isinstance(ds["samples"], list) and ds["samples"], "invalid split")
        require(type(ds.get("repeats", 1)) is int and ds.get("repeats", 1) >= 1, "invalid repeats")
        for sample in ds["samples"]:
            identifier(sample["id"])
            require(sample["id"] not in sample_ids, "overlapping/duplicate sample IDs")
            sample_ids.add(sample["id"])
            repeats = sample.get("repeats", ds.get("repeats", 1))
            require(type(repeats) is int and repeats >= 1, "invalid sample repeats")
            require(isinstance(sample.get("payload", {}), dict), "sample payload must be an object; its contents are case-owned")
        datasets[split] = ds
    simulation = c["simulation"]
    require(relative(root, simulation["instructions"]).is_file(), "simulation instructions missing")
    if "argv" in simulation:
        command_contract(simulation["argv"])
        require(relative(root, simulation["entrypoint"]).is_file(), "simulation entrypoint missing")
        number(simulation["timeout_seconds"], "simulation timeout", 1)
    environment = read(relative(root, c["environment"]))
    if environment.get("preflight"):
        command_contract(environment["preflight"]["argv"])
        require(relative(root, environment["preflight"]["entrypoint"]).is_file(), "preflight entrypoint missing")
        number(environment["preflight"]["timeout_seconds"], "preflight timeout", 1)
    number(c["artifact"]["max_bytes"], "artifact max_bytes", 1)
    require(isinstance(c["artifact"].get("allow_extra_files", True), bool), "allow_extra_files must be boolean")
    require(c["artifact"]["required_files"], "required files missing")
    for name in c["artifact"]["required_files"]:
        relative(root, name)
    if c["artifact"].get("entrypoint"):
        require(c["artifact"]["entrypoint"] in c["artifact"]["required_files"], "artifact entrypoint must be a required file")
    for k in ("patience", "min_rounds", "min_samples", "min_strategies"):
        require(type(c["convergence"][k]) is int and c["convergence"][k] >= 1, "invalid convergence " + k)
    number(c["convergence"]["epsilon_points"], "epsilon", 0.001, 100)
    return c, rubric, datasets


def expected_samples(ds):
    return [f"{sample['id']}:{repeat}" for sample in ds["samples"]
            for repeat in range(1, sample.get("repeats", ds.get("repeats", 1)) + 1)]


def development_dataset(datasets):
    """The framework transports opaque case payloads; it does not interpret their domain."""
    import copy
    result = {"split": "development", "repeats": 1, "samples": []}
    for split in ("validation", "test"):
        for source in datasets[split]["samples"]:
            sample = copy.deepcopy(source)
            sample.update(source_split=split, repeats=source.get("repeats", datasets[split].get("repeats", 1)))
            result["samples"].append(sample)
    return result


def usage_contract(v):
    require(isinstance(v, dict), "usage object required (unknown values must be null)")
    for k in ("input_tokens", "output_tokens", "cost_usd"):
        require(k in v, "missing usage " + k)
        if v[k] is not None:
            number(v[k], k)
            if k != "cost_usd":
                require(type(v[k]) is int, "token counts must be integers")
    return {k: v[k] for k in ("input_tokens", "output_tokens", "cost_usd")}


def simulation_contract(response, case, ds, evidence_root):
    samples = response["samples"]
    require(len(samples) == len(expected_samples(ds)) and
            {s["id"] for s in samples} == set(expected_samples(ds)), "missing/duplicate/unexpected samples")
    metrics = {m["id"] for m in case["metrics"]}
    registry = {}
    for s in samples:
        require(s["status"] in ("completed", "artifact_failure", "infra_failure"), "invalid sample status")
        require(set(s["metrics"]) == metrics, "metric coverage mismatch")
        for key, value in s["metrics"].items():
            if value is not None:
                number(value, key, -float("inf"))
        for metric in case["metrics"]:
            value = s["metrics"][metric["id"]]
            if value is not None and metric.get("minimum") is not None:
                require(value >= metric["minimum"], "metric below minimum: " + metric["id"])
            if value is not None and metric.get("maximum") is not None:
                require(value <= metric["maximum"], "metric outside physical range: " + metric["id"])
            if s["status"] == "completed" and metric.get("required_for_completed"):
                ok = value is not None and (value >= metric["target"] if metric["direction"] == "higher" else value <= metric["target"])
                require(ok, "completed sample violates required metric: " + metric["id"])
        require(s["evidence"], "sample evidence missing")
        for e in s["evidence"]:
            require(e["kind"] in ("artifact", "runtime", "code", "human", "diagnostic"), "invalid evidence kind")
            p = relative(evidence_root, e["path"])
            require(p.is_file() and p.stat().st_size > 0, "missing/empty evidence: " + e["path"])
            if e["path"] in registry:
                require(registry[e["path"]]["kind"] == e["kind"], "conflicting evidence kind")
            registry[e["path"]] = {"kind": e["kind"], "sha256": file_hash(p)}
    require(response["environment"] and isinstance(response["environment"], dict), "environment receipt required")
    require(isinstance(response["confounds"], list), "confounds must be explicit")
    require(isinstance(response["diagnostic_only"], bool), "diagnostic_only must be explicit")
    return registry


def judge_contract(response, simulation, rubric):
    samples = {s["id"]: s for s in simulation["samples"]}
    reviews = response["reviews"]
    require(len(reviews) == len(samples) and {r["sample_id"] for r in reviews} == set(samples),
            "judge must cover every sample exactly once")
    lo, hi = rubric["scale"]
    policy = rubric["evidence_policy"]
    observed_kinds = set(policy["observation_kinds"])
    scores = {}
    dimension_values = {d["id"]: [] for d in rubric["dimensions"]}
    gate_values = {g: [] for g in rubric["gates"]}
    gates_pass = True
    dims = {d["id"]: d for d in rubric["dimensions"]}
    for review in reviews:
        sample = samples[review["sample_id"]]
        evidence = {e["path"]: e["kind"] for e in sample["evidence"]}
        require(set(review["dimensions"]) == set(dims), "judge dimension coverage mismatch")
        total = 0
        for key, v in review["dimensions"].items():
            score = number(v["score"], key, lo, hi)
            refs = v["evidence"]
            require(isinstance(refs, list) and set(refs) <= set(evidence), "unknown evidence reference")
            kinds = {evidence[x] for x in refs}
            require(score <= policy["score_cap_without_observation"] or bool(kinds & observed_kinds),
                    "score exceeds case evidence cap without observation")
            require(v["reason"], "score rationale missing")
            dimension_values[key].append(score)
            total += (score - lo) / (hi - lo) * dims[key]["weight"] * 100
        require(set(review["gates"]) == set(rubric["gates"]), "gate coverage mismatch")
        for gate_id, g in review["gates"].items():
            gate_values[gate_id].append(g["status"])
            require(g["status"] in ("pass", "fail", "unknown"), "invalid gate status")
            require(isinstance(g["evidence"], list) and set(g["evidence"]) <= set(evidence), "unknown gate evidence")
            require(g["reason"], "gate rationale missing")
            if g["status"] == "pass":
                require(any(evidence[x] in observed_kinds for x in g["evidence"]),
                        "gate pass requires evidence allowed by this case")
            gates_pass &= g["status"] == "pass"
        scores[review["sample_id"]] = round(total, 6)
    issues = response["issues"]
    require(len({i["id"] for i in issues}) == len(issues), "duplicate issue ID")
    all_refs = set(simulation["evidence_registry"])
    for i in issues:
        identifier(i["id"])
        require(i["dimension"] in dims and i["severity"] in ("critical", "major", "minor"), "invalid issue")
        require(i["description"] and i["reproduce"] and i["evidence"] and set(i["evidence"]) <= all_refs,
                "issue requires reproducible evidence")
    require(response["summary"], "judge summary missing")
    eligible = gates_pass and not simulation["confounds"] and not simulation["diagnostic_only"] and all(
        s["status"] == "completed" for s in samples.values())
    return {"score": round(sum(scores.values()) / len(scores), 6), "sample_scores": scores,
            "gates_pass": gates_pass, "eligible": eligible,
            "dimension_scores": {k: sum(v) / len(v) for k, v in dimension_values.items()},
            "gate_status": {k: "fail" if "fail" in v else "unknown" if "unknown" in v else "pass"
                            for k, v in gate_values.items()}}


def plan_contract(response, judge):
    require(response["hypothesis"] and response["strategy"] and response["actions"], "empty improvement plan")
    require(isinstance(response["stop_the_line"], bool), "stop_the_line must be boolean")
    require(response["stop_the_line"] == (not judge["assessment"]["gates_pass"]),
            "failing/unknown gates require stop_the_line")
    issues = {i["id"] for i in judge["issues"]}
    addressed = set()
    for a in response["actions"]:
        require(isinstance(a["addresses"], list), "addresses must be a list")
        addressed.update(a["addresses"])
        require(a["change"] and a["validation"] and a["expected_effect"], "plan action incomplete")
        require(set(a["addresses"]) <= issues, "plan addresses unknown issue")
    require({i["id"] for i in judge["issues"] if i["severity"] == "critical"} <= addressed,
            "plan must address every critical issue")
    number(response["expected_gain_points"], "expected gain", 0, 100)
