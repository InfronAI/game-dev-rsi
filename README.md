# Game Dev RSI

Build a game, play it against a reference, review the differences, and test a repair. Game Dev RSI keeps a playable artifact and replay evidence for every round so another developer can inspect the exact input where two versions diverge.

Extracted from the Qwen4-Max game-development experiments, this MIT-licensed toolkit includes the portable session engine and an original browser puzzle, **Relay Vault**. The bundled demo runs offline without API keys or package installation. A coding agent or a human can drive the same four-stage protocol with their own implementation.

## Run the experiment

From the repository root, use Python 3.9+ and Node.js 22+ on your PATH:

```sh
python3 tools/rsi.py doctor --case cases/relay-vault
python3 examples/demo.py
python3 tools/rsi.py showcase
python3 -m http.server 8000 --bind 127.0.0.1
```

Open the [experiment gallery](http://127.0.0.1:8000/showcase/) or [play the reference game](http://127.0.0.1:8000/cases/relay-vault/assets/reference/). In the gallery, launch the first, best or latest game. Click a route in the evidence column and scrub through the recorded reference and candidate states.

The demo seeds two known defects into a copy of the reference. Its scripted developer reads the previous round's plan, applies the selected change, then submits the result through the same CLI as a real agent. No model is invoked. The identity in the run is `scripted-demo / none`.

| Round | Change | Expected rubric score | All routes match |
|---|---|---:|---|
| 1 | The exit opens early and blocked movement spends power. | 83.452381 | No |
| 2 | Require both relays to unlock the exit. | 89.071429 | No |
| 3 | Preserve power on blocked moves. | 100.000000 | Yes |

**How to read a failure:** open the first round's `wall-bump` replay and move the slider to step 1. Both rovers stay in place after an upward input. The reference retains 12 power while the candidate drops to 11. Replay the same step in round 3 to see the fix. The gallery's maps reconstruct the recorded states on the reference board. Browser tests separately exercise the actual game controls and DOM.

Exact expected scores and artifact SHA-256 fingerprints are recorded in [the demo baseline](docs/demo-baseline.json) and checked by the workflow test.

The default demo stops at its three-round budget after saving the last plan. Use a fresh run ID for another trial:

```sh
python3 examples/demo.py --run-id repeat
python3 examples/demo.py --resume experiments/scripted-demo/none/relay-vault/demo
```

## Use your own coding agent

Open this checkout in your coding agent and give it [AGENTS.md](AGENTS.md). Supply the real agent and model names when initializing a session. A cold start creates an empty workspace. The reference and all seven development routes are visible. For an independent recreation, describe what reference materials the developer accessed.

```sh
python3 tools/rsi.py init --case cases/relay-vault --agent my-agent --model my-model --run-id trial --max-rounds 8
```

The command prints the experiment directory. Run `next` there, implement in the designated workspace, submit the response and continue the cycle. The [agent guide](AGENTS.md) includes commands and response formats. The toolkit accepts model output through files; the model provider and any API billing remain with the developer's chosen client.

| Stage | Developer action | Recorded result |
|---|---|---|
| Generate | Implement or repair the game in the current workspace. | Frozen artifact, file hashes and change description |
| Simulate | Replay the reference and candidate with identical inputs. | Per-step state pairs, metrics, environment and evidence hashes |
| Judge | Read the traces and apply the case rubric. | Evidence-backed scores, failed gates and reproducible issues |
| Plan | Select a repair with a testable prediction. | Actions tied to issues and a validation plan for the next round |

An accepted plan starts the next workspace from the best available artifact. The engine tracks identity, elapsed wall time, stage attempts, artifact integrity, stop reasons and optional usage. A changed artifact or stale request ID causes verification to fail. See [case authoring and reproducibility](docs/protocol.md) for the input contracts and stopping rules.

## Verify the checkout

```sh
node --test tests/rules.test.mjs
python3 -m unittest discover -s tests -v
```

For browser verification, install Chrome or Chromium and set `CHROME_BIN` to its executable. After the demo:

```sh
python3 tests/browser_smoke.py \
  --game experiments/scripted-demo/none/relay-vault/demo/rounds/round-0003/artifact/index.html \
  --replay experiments/scripted-demo/none/relay-vault/demo/rounds/round-0001/evidence/attempt-001/wall-bump-1.html
```

The smoke test creates a disposable browser profile, serves the checkout on a temporary loopback port, wins the game through keyboard inputs, resets it, collects a relay with a button and advances a recorded replay to its last checkpoint. The rules and workflow tests run without a browser.

## Project layout

| Path | Contents |
|---|---|
| `tools/rsi.py`, `tools/rsi_engine/` | CLI, session engine, validation and gallery |
| `cases/relay-vault/` | Original game, specification, rubric, routes and local replay collector |
| `examples/demo.py` | Reproducible three-round scripted developer |
| `tests/` | Rule, workflow, integrity and browser checks |
| `experiments/`, `showcase/` | Locally generated runs and gallery; excluded from version control |

The example measures state parity on seven public routes. A perfect result covers those checks. Visual fidelity, novel player inputs and generalization require additional evidence. Execute trusted case collectors and game code in an environment appropriate to their origin.

## License

[MIT License](LICENSE), copyright 2026 InfronAI. The game, interface and case materials in this distribution ship with the project; the example loads no external game assets.
