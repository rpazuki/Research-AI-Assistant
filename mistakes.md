# mistakes.md

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
