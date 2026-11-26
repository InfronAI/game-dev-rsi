"""Publish static, local-first views of the frozen artifacts and their evidence."""
import html
import os
from pathlib import Path
from urllib.parse import quote

from .contracts import read
from .engine import Runner, write


def rel_link(base, file):
    return quote(os.path.relpath(Path(file).resolve(), Path(base).resolve()).replace(os.sep, "/"))


def render_run(r):
    history = r.s["history"]
    entry = r.case["artifact"].get("entrypoint", r.case["artifact"]["required_files"][0])
    submitted = [i for i in range(1, r.s["round"] + 1)
                 if f"rounds/round-{i:04d}/generation.json" in r.s["sealed"]]
    works = {}
    for name, n in (("first", min(submitted, default=None)), ("best", r.s["best_round"]),
                    ("latest", max(submitted, default=None))):
        works[name] = rel_link(r.exp, r.round_dir(n) / "artifact" / entry) if n else None
    summary = {"case": r.case["id"], "title": r.case["title"], "run_id": r.s["run_id"],
               "case_hash": r.s["case_hash"], "runner_hash": r.s["runner_hash"], "identity": r.identity,
               "status": r.s["status"], "stop_reason": r.s["stop_reason"], "best_round": r.s["best_round"],
               "review_mode": "owner_self_review", "origin": r.s["origin"], "works": works, "curve": history}
    write(r.exp / "summary.json", summary)
    lines = ["# " + r.case["title"], "", " | ".join(f"[Play {name}]({path})" for name, path in works.items() if path),
             "", f"Status: {r.s['status']}. Stop reason: {r.s['stop_reason'] or 'none'}.", "",
             "| Round | Score / 100 | All gates pass | Accepted records |", "|---|---:|---|---|"]
    for item in history:
        n = item["round"]
        rd = r.round_dir(n)
        records = [f"[{k}]({rel_link(r.exp, rd / (k+'.json'))})" for k in
                   ("generation", "simulation", "judge", "planning") if (rd / (k+".json")).is_file()]
        lines.append(f"| [{n}]({rel_link(r.exp, rd/'artifact'/entry)}) | {item['score']:.2f} | "
                     f"{item['gates_pass']} | {' / '.join(records)} |")
    lines += ["", "Scores describe this case and its observed routes. Both public suites guide development.",
              "", "[Structured history](summary.json) | [Current handoff](NEXT.md)"]
    (r.exp / "SHOWCASE.md").write_text("\n".join(lines) + "\n", encoding="utf8")


def build_gallery(experiments, destination):
    destination.mkdir(parents=True, exist_ok=True)
    cards, errors = [], []
    for state in sorted(experiments.glob("*/*/*/*/state.json")):
        try:
            run = Runner(state.parent, read_only=True)
            render_run(run)
            summary = read(run.exp / "summary.json")
            rounds = []
            for h in summary["curve"]:
                rd = run.round_dir(h["round"])
                sim = read(rd / "simulation.json")
                evidence = [dict(sample=s["id"], href=rel_link(destination, rd/"evidence"/next((e["path"] for e in s["evidence"] if e["path"].endswith(".html")), s["evidence"][0]["path"])))
                            for s in sim["samples"]]
                rounds.append(dict(number=h["round"], score=h["score"], gates=h["gates_pass"],
                                   judge=rel_link(destination, rd/"judge.json"), evidence=evidence))
            cards.append(dict(title=summary["title"], owner=summary["identity"]["agent"], model=summary["identity"]["model"],
                              name=summary["run_id"], status=summary["status"], rounds=rounds,
                              works={k:rel_link(destination, run.exp)+"/"+v for k,v in summary["works"].items() if v}))
        except (OSError, ValueError, KeyError) as exc:
            errors.append({"run": str(state.parent), "error": str(exc)})
    write(destination / "catalog.json", {"runs": cards, "errors": errors})
    esc = html.escape
    body = []
    for card in cards:
        body += [f'<section><h2>{esc(card["title"])}</h2><p>{esc(card["owner"])} / {esc(card["model"])}'
                 f' &middot; {esc(card["name"])} &middot; {esc(card["status"])}</p>',
                 " &nbsp; ".join(f'<a href="{v}">Play {k}</a>' for k,v in card["works"].items()),
                 "<table><tr><th>Round</th><th>Score</th><th>Gate</th><th>Replay evidence</th></tr>"]
        for rd in card["rounds"]:
            links = " ".join(f'<a href="{e["href"]}">{esc(e["sample"])}</a>' for e in rd["evidence"])
            body.append(f'<tr><td><a href="{rd["judge"]}">{rd["number"]}</a></td><td>{rd["score"]:.2f}</td>'
                        f'<td>{"Pass" if rd["gates"] else "Fail"}</td><td>{links}</td></tr>')
        body.append("</table></section>")
    for error in errors:
        body.append("<p>Unavailable session: " + esc(error["error"]) + "</p>")
    if not cards and not errors:
        body.append("<p>No recorded sessions yet. Run the demo to create one.</p>")
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Game Dev RSI | Runs</title><style>body{font:16px/1.6 system-ui;color:#1b3042;background:#f3f6fb;margin:4vw}
h1,h2{font-family:Georgia,serif}section{background:white;padding:20px;overflow:auto;margin:20px 0}
a{color:#004ab9}table{border-collapse:collapse;margin-top:18px}td,th{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #dce6f1}
td a{display:inline-block;margin-right:8px}</style><main><h1>Game Dev RSI experiments</h1>"""
    (destination / "index.html").write_text(page + "".join(body) + "</main></html>", encoding="utf8")
    return {"runs": len(cards), "errors": errors, "gallery": str(destination / "index.html")}
