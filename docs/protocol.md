# Case authoring and reproducibility

The runner separates a reusable four-stage protocol from game-specific measurement. Copy the relay-vault package to start another case, choose a unique ID, and replace its rules, reference, routes and collector. Invoke `python3 tools/rsi.py validate-case PATH` before generating a run.

## Portable package

| File or field | Contract |
|---|---|
| case.json | Schema version 1; stable ID, title and relative paths to the files below |
| GOAL.md and PROMPT.md | Observable rules, permitted reference material, controls and delivery constraints |
| artifact | Required files, playable entry point, byte limit and extra-file policy |
| environment.json | Runtime requirements and optional preflight argv returning named Boolean checks |
| rubric.json | Numeric scale, dimensions with weights totaling 1, endpoint anchors, gates and allowed evidence kinds |
| datasets/validation.json and datasets/test.json | Named split, repeats, unique sample IDs and case-defined payloads |
| simulation | Instructions, a case-local entry point and optional collector argument vector and timeout |
| metrics | Named units, allowed ranges, direction and optional thresholds for a completed sample |
| convergence | Minimum rounds and samples, distinct strategies, patience and score tolerance for an observed plateau |

Both public suites contribute to every round. Payloads are opaque to the runner. The collector receives a request JSON path and a response JSON path. Its response contains the request ID, one result per sample and repeat, environment, explicit confounds and diagnostic status. Save evidence under the assigned evidence directory and reference relative paths. A rejected move is a game observation. A missing Node executable is an infrastructure failure and cannot supply a passing review.

## Measurement in Relay Vault

The collector starts both game modules in fresh processes per route. Every trace includes the initial state and the state after each action. Movement receives 55% of the score and compares x, y and phase. Resources receive 45% and compare power and the ordered list of collected relays. Each dimension is the percentage of matching checkpoints within the route. The final normalized score averages weighted route scores equally. The gate requires all five fields to agree at every checkpoint. Rendering, latency and enjoyment are outside this rubric.

The reference, driver and schedules have no random inputs, wall-clock timers or network calls. Fresh runs with the same package and scripted driver reproduce state traces, artifact hashes and scores. Session IDs, absolute handoff paths, timestamps and elapsed time are specific to each execution. Record Python and Node versions when sharing results.

## Integrity, selection and stops

Init freezes the case and identity and records the engine version hash. Every accepted stage binds the response to the current request. Accepted records, artifact files and referenced evidence have hashes checked on subsequent operations. Within a run the best candidate is selected by eligibility, measurement validity, then score; equal results keep the earlier round. Fresh workspaces may therefore descend from an earlier best round. A warm start explicitly records its initial artifact.

A plateau requires distinct artifacts, eligible and comparable measurements, several strategies and bounded paired score differences. A run can also stop for its configured wall-clock or round budget. A pending round stop still records the final plan. The demo deliberately uses a budget of three rounds.

Experiments store absolute paths in handoffs and environment receipts. Use a fresh init to reproduce on a new machine. Use the static gallery and accepted traces to inspect a completed experiment. For a comparison across agents, hold the case hash, reference, routes, environment, budgets and initial artifact constant and report which evidence each reviewer saw.
