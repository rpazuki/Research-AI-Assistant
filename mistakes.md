# mistakes.md — Recurring Mistakes Log

Patterns discovered during implementation, review, and debugging.
**Rule:** Updated after every 5 user requests per session or after a significant bug is found.
Agent must consult this file before writing tests or async code.

---

## 2026-05-16 — Python environment mismatch during validation

### Incident
The configured Python environment selected by tooling was `.venv-1` (Python 3.13). Running backend tests there failed because `pytest` was missing, and installing backend dev dependencies failed due `torch>=2.2.0` wheel incompatibility for that interpreter/platform combination.

### Impact
Validation was temporarily blocked until tests were switched to the repository's existing backend environment (`backend/.venv`, Python 3.12), where dependencies are compatible.

### Root cause
Environment auto-selection preferred a newer local virtualenv not aligned with project constraints and existing dependency lock expectations.

### Prevention
- Verify interpreter path and version before backend test execution.
- Prefer the repository-scoped backend virtualenv for this project (`backend/.venv/bin/python`) unless dependency constraints are explicitly updated for another interpreter.
- Add an explicit environment note in onboarding/test commands to avoid accidental Python 3.13 selection for backend validation.

---

## 2026-05-16 — Async generator used as async context manager (test_e2e.py)

**Mistake:** `async def f(): yield ...` then `async with f() as x:` without `@asynccontextmanager`.  
**Error:** `TypeError: 'async_generator' object does not support the asynchronous context manager protocol`  
**Fix:** Add `@contextlib.asynccontextmanager` decorator.  
**Prevention:** Any async generator used with `async with` must carry `@asynccontextmanager`.

---

## 2026-05-16 — Sync lambda monkeypatching an awaited async function

**Mistake:** `monkeypatch.setattr("mod.async_fn", lambda *a: value)` when the caller does `await async_fn(...)`.  
**Error:** `TypeError: object bool can't be used in 'await' expression`  
**Fix:** Use `async def fake(*a): return value` instead of a lambda.  
**Prevention:** Every monkeypatched callable that is `await`-ed must be `async def`.

---

## 2026-05-16 — JWT dependency override scope leakage

**Mistake:** Setting `app.dependency_overrides` in a test without clearing in a `finally` block.  
**Error:** Intermittent failures depending on test execution order (flaky tests).  
**Fix:** Always `app.dependency_overrides.clear()` in `finally` or fixture teardown.  
**Prevention:** Tests that directly mutate `app.dependency_overrides` need explicit `finally` cleanup.

---

## Standing rules (architecture-level)

- **IVFFlat index:** Never create in Alembic migrations. Create after first ingestion only.
- **Embedding dimensions:** Never mix 768-dim and 384-dim in the same vector column.
- **Blocking in async:** Always use `asyncio.to_thread` for CPU-bound calls inside `async def`.
- **transformers version:** Pin `transformers<4.52` to stay compatible with `torch 2.2.x`.
- **Lazy ORM load:** Never call `model_validate(orm_obj)` when relationships may be unloaded.
