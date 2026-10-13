Follow @AGENTS.md. Use the `motionworkflow` skill for generation requests.

- Run tests with `.venv/bin/python -m unittest discover -s tests` (offline, free).
- Keep `motionworkflow/models.json` the single source of model IDs and prices; don't hardcode endpoints in code.
- Any new paid call must go through `workflows.common.generate()` so it is budget-checked, logged and resumable.
