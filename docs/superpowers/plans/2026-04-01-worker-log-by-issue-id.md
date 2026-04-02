# Fix worker log lookup by issue_id

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `get_worker_log` so it accepts an `issue_id` and resolves it to the latest session's tracking_id, instead of requiring the caller to know the internal tracking_id UUID.

**Architecture:** Add a `get_session_log_by_issue` method to `Orchestrator` that looks up the latest session for an issue_id in the session manifest, then delegates to the existing `get_session_log`. Update the HTTP endpoint URL from `/logs/{tracking_id}` to `/logs/{issue_id}`, and update `RunManager.get_worker_log` to use the new method. The `DaemonClient` URL already uses `issue_id` in the path so it needs no change.

**Tech Stack:** Python, Starlette, aiohttp

---

### Task 1: Add issue_id→tracking_id resolution and fix the full chain

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py` (add `get_session_log_by_issue`)
- Modify: `src/orca/daemon/manager.py` (update `get_worker_log` to use issue_id)
- Modify: `src/orca/daemon/http_api.py` (change URL param from `tracking_id` to `issue_id`)

- [ ] **Step 1: Add `get_session_log_by_issue` to Orchestrator**

In `src/orca/orchestrator/orchestrator.py`, add this method right after the existing `get_session_log` method (after line 149):

```python
def get_session_log_by_issue(self, issue_id: str, tail: int = 100) -> str:
    """Read session log for the latest session of the given issue_id.

    Looks up the issue's most recent session in the manifest, then
    delegates to ``get_session_log`` with the session's tracking_id.
    Returns empty string if no session is found.
    """
    if self._session_sync is None:
        return ""
    entries = self._session_sync.manifest.read()
    # Find the latest session for this issue_id (last in the list)
    tracking_id = ""
    for entry in entries:
        if entry.get("issue_id") == issue_id:
            tracking_id = entry.get("session_id", "")
    if not tracking_id:
        return ""
    return self.get_session_log(tracking_id, tail)
```

- [ ] **Step 2: Update `RunManager.get_worker_log` to use issue_id**

In `src/orca/daemon/manager.py`, change the `get_worker_log` method (line 518-523) from:

```python
def get_worker_log(self, run_id: str, tracking_id: str, tail: int = 100) -> str:
    """Get worker log content for a tracking ID in the given run."""
    run_info = self._runs.get(run_id)
    if run_info is None or run_info.orchestrator is None:
        return ""
    return run_info.orchestrator.get_session_log(tracking_id, tail)
```

to:

```python
def get_worker_log(self, run_id: str, issue_id: str, tail: int = 100) -> str:
    """Get worker log content for the latest session of the given issue."""
    run_info = self._runs.get(run_id)
    if run_info is None or run_info.orchestrator is None:
        return ""
    return run_info.orchestrator.get_session_log_by_issue(issue_id, tail)
```

- [ ] **Step 3: Update HTTP endpoint URL param**

In `src/orca/daemon/http_api.py`, change the `_get_worker_log` handler (line 100-106) from:

```python
async def _get_worker_log(request: Request) -> PlainTextResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    tracking_id: str = request.path_params["tracking_id"]
    tail = int(request.query_params.get("tail", "100"))
    text = manager.get_worker_log(run_id, tracking_id, tail)
    return PlainTextResponse(text)
```

to:

```python
async def _get_worker_log(request: Request) -> PlainTextResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]
    tail = int(request.query_params.get("tail", "100"))
    text = manager.get_worker_log(run_id, issue_id, tail)
    return PlainTextResponse(text)
```

Also find the route registration for this endpoint and change the URL pattern from `/api/runs/{run_id}/logs/{tracking_id}` to `/api/runs/{run_id}/logs/{issue_id}`.

- [ ] **Step 4: Update DaemonClient URL path**

In `src/orca/daemon/client.py`, the `get_worker_log` method already uses `issue_id` in its signature. Check the URL it builds — it should be `/api/runs/{run_id}/logs/{issue_id}?tail={tail}`. This should already be correct, but verify.

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py src/orca/daemon/manager.py src/orca/daemon/http_api.py
git commit -m "fix(daemon): resolve worker log by issue_id instead of tracking_id"
```
