# Day 12 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `develop/app.py`

1. **Hardcoded secrets** — `OPENAI_API_KEY` and `DATABASE_URL` are embedded directly in source. Anyone with repo access sees them, and pushing to GitHub leaks them instantly.
2. **No config management** — `DEBUG=True`, `MAX_TOKENS=500` are hardcoded constants. To change them you must edit code and redeploy, instead of reading from environment variables.
3. **`print()` instead of structured logging** — no log levels, no timestamps, no JSON. `print(OPENAI_API_KEY)` also leaks the secret to stdout.
4. **No health check endpoint** — the platform cannot detect a crashed process, so it cannot auto-restart the container or pull the instance out of the load balancer.
5. **Hardcoded `host="localhost"` and `port=8000`** — `localhost` refuses external connections inside a container, and cloud platforms (Railway/Render) inject `PORT` via env var, so a fixed port breaks deploy.
6. **`reload=True` in production** — uvicorn reload is a dev-only feature: it watches files, doubles memory usage, and is unsafe under load.
7. **No graceful shutdown / SIGTERM handler** — when the platform sends SIGTERM, in-flight requests are killed mid-response.
8. **No input validation** — `/ask` accepts `question: str` with no length limit or schema validation, opening the door to abuse and 500 errors.

### Exercise 1.3: Comparison table

| Feature | Develop | Production | Why it matters |
|---|---|---|---|
| Config | Hardcoded constants (`OPENAI_API_KEY`, `DEBUG`, port) | `config.py` via env vars (`settings.port`, `settings.debug`) | Same image deploys to any env; secrets never in git |
| Host binding | `localhost` | `0.0.0.0` (from settings) | `localhost` blocks container/external traffic |
| Port | Hardcoded `8000` | `settings.port` from `PORT` env var | Cloud platforms inject `PORT`; fixed port fails deploy |
| Logging | `print()`, leaks secrets | Structured JSON via `logging`, log levels, no secrets | Parseable by Datadog/Loki; safe for audit |
| Health check | None | `/health` (liveness) + `/ready` (readiness) | Platform restarts crashed containers; LB pulls unready instances |
| Metrics | None | `/metrics` endpoint | Prometheus can scrape uptime/version |
| Lifecycle | None | `lifespan` context (startup/shutdown hooks) | Warms connections on boot, closes cleanly |
| Shutdown | Abrupt kill | SIGTERM handler + lifespan shutdown | In-flight requests finish; no dropped responses |
| CORS | None | `CORSMiddleware` with allowlist | Prevents unauthorized browser origins |
| Reload | `reload=True` always | `reload=settings.debug` only | Prod never reloads; saves memory, stable |
| Input validation | None | `HTTPException(422)` when `question` missing | Clear error, no 500s |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (from `02-docker/develop/Dockerfile`)

1. **Base image**: `python:3.11` — the full Python distribution (~1 GB), not the slim variant.
2. **Working directory**: `/app` (set via `WORKDIR /app`).
3. **Why `COPY requirements.txt` first?** Docker caches image layers. If you copy all source code first, any code change busts the cache and forces `pip install` to re-run. By copying only `requirements.txt` first, the expensive `pip install` layer is cached and only rebuilt when dependencies actually change — subsequent code-only changes rebuild in seconds.
4. **CMD vs ENTRYPOINT**:
   - `CMD` sets the default command; it can be fully overridden by passing arguments to `docker run image <cmd>`.
   - `ENTRYPOINT` defines the *executable* that always runs; `CMD` then supplies default arguments to it. Overriding `ENTRYPOINT` requires `--entrypoint`.
   - Pattern: use `ENTRYPOINT ["python"]` + `CMD ["app.py"]` to build a "python script runner" image; use `CMD` alone when you want callers to fully replace the command.

### Exercise 2.3: Multi-stage build

**Stage 1 (builder)** — uses `python:3.11-slim`, installs build tools (`gcc`, `libpq-dev`), and runs `pip install --user` to compile and install dependencies into `/root/.local`. This stage has all the compilers needed for native packages (numpy, psycopg2, etc.).

**Stage 2 (runtime)** — fresh `python:3.11-slim` base. Copies only the installed site-packages from the builder (`COPY --from=builder /root/.local`), plus source code. Creates a non-root `appuser`, switches to it, adds a HEALTHCHECK, and runs uvicorn with 2 workers.

**Why the final image is smaller**:
- No `gcc`, `libpq-dev`, or apt cache (those stay in the builder stage, which is discarded).
- `python:3.11-slim` base (~120 MB) vs `python:3.11` full (~1 GB).
- No pip build cache, no `.whl` files.
- Only runtime artifacts are copied across.

### Exercise 2.3: Image size comparison

_TODO — run after Docker Desktop is started:_

```bash
docker build -f 02-docker/develop/Dockerfile -t agent-develop .
docker build -f 02-docker/production/Dockerfile -t agent-production .
docker images | grep agent-
```

- Develop: _TODO_ MB
- Production: _TODO_ MB
- Difference: _TODO_ %

---

## Part 3: Cloud Deployment

_TODO_

---

## Part 4: API Security

_TODO_

---

## Part 5: Scaling & Reliability

_TODO_
