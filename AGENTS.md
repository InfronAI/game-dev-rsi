# Running a game-development session

Use the identity and tools available to the current developer. The scripted demo is an instructional baseline. Start a separate session for actual model output. Run commands from the project root.

1. Read the selected case's goal, prompt, rubric, environment and both datasets. Run `python3 tools/rsi.py doctor --case cases/relay-vault`.
2. Initialize with your actual identity and a new run ID. Set EXP to the experiment path printed by the CLI. If resuming your own session, run `python3 tools/rsi.py status --experiment "$EXP"` first.
3. Run `python3 tools/rsi.py next --experiment "$EXP"`. Open the JSON at `request`. Each response must echo its `request_id`. Use the paths in that request.
4. **Generation:** edit only `workspace`, follow the preceding plan, and return a summary and changes. Example: `{"request_id":"...","summary":"Reject entry until both relays are collected.","changes":["Corrected the locked-exit condition."]}`. Disclose copied code or inherited work.
5. **Simulation:** run `python3 tools/rsi.py simulate --experiment "$EXP"`, read the returned response and inspect the referenced evidence. For the bundled case, open the HTML state replay and inspect the JSON checkpoints at the first divergence. Submit the collected response after inspection. Collection alone does not advance the stage.
6. **Judge:** cover every sample and rubric dimension. Include evidence paths exactly as registered on that sample. Mark unobserved behavior as unknown where the contract permits it. A review has `sample_id`, `dimensions` mapping each ID to `{score, evidence, reason}`, and `gates` mapping each ID to `{status, evidence, reason}`. Return `reviews`, `issues` and a one-sentence `summary`. Each issue needs `id`, `severity`, `dimension`, `description`, `reproduce` and `evidence`. Severity is critical, major or minor. See the runnable producer in examples/demo.py.
7. **Plan:** return `hypothesis`, `strategy`, `stop_the_line`, `expected_gain_points` and `actions`. Each action contains `addresses` (issue IDs), `change`, `expected_effect` and `validation`. Set stop_the_line when any gate fails or is unknown. Address every critical issue.
8. After each stage, submit with `python3 tools/rsi.py submit --experiment "$EXP" --response "$RESPONSE"`. Continue with `next` until the engine records a stop or blocker. Optional usage is an object with input_tokens, output_tokens and cost_usd; use null for unknown values.
9. If required observations cannot be collected, use `block --experiment "$EXP" --reason "..."`. Fix the environment and use `resume` on the same run. Preserve old attempts. Generate the report and gallery with `report --experiment "$EXP"` and `showcase`.

Final delivery should identify the first, best and latest artifacts; the tested routes; one concrete improvement or regression; the stop reason; and the limits of the observations. Independent evaluation requires separately held-out cases or reviewers.
