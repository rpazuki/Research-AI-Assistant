# `scripts/` — production operations

Five scripts for the deployment VM. All of them default to
`docker-compose.prod.yml`; prefix with `COMPOSE_FILE=docker-compose.yml` to
rehearse any of them against the dev stack on a laptop.

Run them from anywhere — each one relocates to the repository root itself.

| Script | Purpose |
|---|---|
| `deploy.sh` | pull from GitHub, rebuild only what changed, verify, roll back on failure |
| `restart.sh` | bounce services without touching git |
| `status.sh` | one screen: deployed commit, container states, health, resources |
| `logs.sh` | live unified log view across all containers |
| `collect-logs.sh` | one redacted `.tar.gz` to attach to a bug report |

`lib/common.sh` and `lib/redact.sh` are sourced, not run.

---

## Updating the deployed version

```bash
cd /opt/rlalab
scripts/deploy.sh                  # the normal case
```

What it does, in order:

1. Refuses to start if a deploy is already running, if `.env` is missing, or if
   the working tree has uncommitted tracked changes (a rollback would eat them).
2. `git fetch` + `git merge --ff-only origin/<branch>`. Never a merge commit — a
   diverged production checkout is an operator decision, not a script's.
3. Maps the changed paths to services:
   `backend/**` or `pipelines/**` → backend + both workers;
   `frontend/**` → frontend; `docker-compose.prod.yml`, `.env.server`,
   `nginx/**` → everything. Nothing relevant changed → nothing is rebuilt.
4. Builds those images and `up -d`s only those services. Alembic migrations run
   inside the backend container at start, as they already do.
5. Waits for each service to answer (`/health` on the backend, `/login` on the
   frontend, `pg_isready` on the database) and warns on restart loops.
6. On failure: prints the last 60 lines per service, resets the checkout to the
   previous commit and rebuilds. **Migrations are not reversed** — the script
   says so loudly when it happens.
7. Appends one tab-separated audit line to `ops/deploy.log`.

```bash
scripts/deploy.sh --dry-run        # show the plan, change nothing
scripts/deploy.sh -y               # no prompt (cron / CI)
scripts/deploy.sh -s frontend      # this service only
scripts/deploy.sh --all --force    # rebuild everything at the current commit
scripts/deploy.sh --no-pull        # rebuild from the working tree as-is
scripts/deploy.sh --prune          # drop dangling images afterwards
```

Restarting without deploying:

```bash
scripts/restart.sh backend                 # bounce the process
scripts/restart.sh --recreate backend       # after editing .env or .env.server —
                                            # a plain restart keeps the old
                                            # environment, which is fixed when
                                            # the container is created
scripts/restart.sh --stop ingestion-worker
```

---

## When a lab member reports a problem

```bash
scripts/collect-logs.sh --since 6h --note "chat returns 500 for <user>, ~09:40 UTC"
```

Writes `ops/rlalab-support-<host>-<UTC>.tar.gz` — send that one file. It holds
every container's log over the window merged into `logs/all.log` in timestamp
order, plus the deployed commit, container states and restart counts, resource
usage, recent deploys, behaviour-affecting settings, and database counters.

Secrets are stripped on the way out and the finished bundle is grepped for the
literal values in `.env`; if one survived, the bundle is discarded rather than
written. Chat content, document text and `.env` values are never included.
Email addresses are pseudonymised (`ro***@imperial.ac.uk`) so the same person
stays traceable across lines without the mailbox being readable.

Common variants:

```bash
scripts/collect-logs.sh --since 30m -s backend -s frontend
scripts/collect-logs.sh --since 2026-08-07T09:00:00 --tail 50000
scripts/collect-logs.sh --keep-emails          # you need the actual addresses
```

Watching a problem live instead:

```bash
scripts/logs.sh -f                  # everything, timestamped
scripts/logs.sh -f backend --errors # errors, tracebacks and HTTP 5xx only
scripts/logs.sh -f --redact         # safe to screen-share
```

---

## Notes

- Docker log rotation is configured in `docker-compose.prod.yml`
  (`x-logging`, 20 MB × 5 per service). Without it the default json-file driver
  grows without bound and eventually fills the VM disk.
- `ops/` is gitignored: audit log, bundles, and the deploy lock live there.
- If a deploy dies hard, the lock survives. Clear it with
  `rmdir ops/deploy.lock`.
- Add any new secret in `.env` to `REDACT_KEYS` in `lib/redact.sh`, or it will
  not be removed from bundles by name.

Full deployment context: [run_and_deploy.md](../run_and_deploy.md).
Logging design and what to do when a bundle is not enough:
[docs/operations-logging.md](../docs/operations-logging.md).
