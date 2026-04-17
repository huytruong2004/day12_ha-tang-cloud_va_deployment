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

### Exercise 3.1 — Render deployment

- **URL**: https://ai-agent-production-baxc.onrender.com
- **Platform**: Render (Blueprint + Docker runtime, free plan, Singapore region)
- **Source**: `render.yaml` at repo root, `rootDir: 06-lab-complete`
- **Screenshot**: `screenshots/dashboard.png`

### Deployment flow

1. Pushed repo to GitHub (`huytruong2004/day12_ha-tang-cloud_va_deployment`).
2. Added `render.yaml` at repo root (Render Blueprint auto-discovers only at root), with `rootDir: 06-lab-complete` so builds run inside the Lab 06 subdirectory.
3. Logged in via CLI: `render login` → workspace `AI Vingroup` set as default.
4. Validated blueprint: `render blueprints validate render.yaml` → `valid: true`.
5. Created the service via the Render dashboard (New + → Blueprint → connect GitHub → Apply). The CLI currently only supports `blueprints validate`, not `blueprints create` — initial service creation is web-only.
6. Rendered auto-triggered build + deploy on every push (`autoDeploy: true`).

### Bugs hit + fixes during deploy

- **`need_payment_info`** at `plan: starter` → switched to `plan: free`.
- **`ModuleNotFoundError: No module named 'uvicorn'`** — caused by `useradd -d /app` making Python's user-site lookup point at `/app/.local/...` instead of `/home/agent/.local/...` where we copied the packages. Fixed by setting `PYTHONPATH=/app:/home/agent/.local/lib/python3.11/site-packages`.
- **`'MutableHeaders' object has no attribute 'pop'`** — Starlette's `MutableHeaders` doesn't implement `.pop()`. Replaced with `if "server" in response.headers: del response.headers["server"]`.

### render.yaml vs railway.toml (Exercise 3.2 comparison)

| Aspect | `render.yaml` | `railway.toml` |
|---|---|---|
| Format | YAML | TOML |
| Discovery | Auto-read at repo root (Blueprint) | Auto-read at repo root |
| Runtime selector | `runtime: docker` (picks Dockerfile) | `builder = "NIXPACKS"` (auto-detect) or Dockerfile |
| Env vars | Inline in YAML, `generateValue: true` for secrets | Set via CLI/dashboard; TOML doesn't embed values |
| Plan | `plan: free` / `starter` | Plan selected in dashboard |
| Health check | `healthCheckPath: /health` | `healthcheckPath = "/health"` with timeout + retry policy |
| Restart policy | Implicit | Explicit (`restartPolicyType`, `restartPolicyMaxRetries`) |
| Multi-service | Yes — list of `services` (web, worker, cron, db) | One service per file |
| Auto-deploy | `autoDeploy: true` | Implicit from repo link |
| Secret handling | `sync: false` (prompted), `generateValue: true` (server-side random) | CLI-only (`railway variables set`) |

Overall: `render.yaml` is more declarative and supports full infrastructure-as-code for multi-service stacks. `railway.toml` is simpler for single-service deploys but delegates more to the dashboard/CLI for state.

---

## Part 4: API Security

### Exercise 4.1 — API Key authentication (`04-api-gateway/develop/app.py`)

- **Where is the API key checked?** In the `verify_api_key` FastAPI dependency (lines 39–54). `APIKeyHeader(name="X-API-Key")` extracts the header, and `verify_api_key` is injected into protected endpoints via `Depends(verify_api_key)`. Any endpoint that wants protection declares the dependency.
- **What happens on an invalid key?**
  - Missing header → `401 Missing API key`
  - Wrong key → `403 Invalid API key`
  - `/health` is public (platform needs unauthenticated access for liveness probes).
- **How to rotate the key?** Change the `AGENT_API_KEY` environment variable and redeploy. Because the key is read from env at startup, no code change is needed. A real rotation flow would support multiple valid keys simultaneously (old + new) during a rollover window before retiring the old one.

### Test outputs

```bash
# Without key → 401
$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"hi"}'
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Wrong key → 403
$ curl -X POST http://localhost:8000/ask -H "X-API-Key: wrong" -H "Content-Type: application/json" -d '{"question":"hi"}'
{"detail":"Invalid API key."}

# Correct key → 200
$ curl -X POST http://localhost:8000/ask -H "X-API-Key: demo-key-change-in-production" -H "Content-Type: application/json" -d '{"question":"hi"}'
{"question":"hi","answer":"..."}
```

### Exercise 4.2 — JWT authentication (`04-api-gateway/production/auth.py`)

- **Token payload** — `{sub: username, role, iat, exp}`, signed with `HS256` and `JWT_SECRET` env var. Expiry is 60 minutes.
- **Flow**:
  1. Client calls `POST /auth/token` with username+password.
  2. Server calls `authenticate_user()` → returns JWT via `create_token()`.
  3. Client sends `Authorization: Bearer <token>` on subsequent calls.
  4. `verify_token` dependency decodes + validates signature/expiry, injects `{username, role}` into the handler.
- **Why stateless?** The token itself encodes identity and role. No database lookup per request — just signature verification. Horizontally scalable.
- **Error handling** — expired → `401 Token expired`, invalid signature → `403 Invalid token`, missing header → `401 Authentication required`.

### Exercise 4.3 — Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm**: Sliding window counter. Each user has a `deque` of request timestamps; on each check we drop entries older than `window_seconds`, and reject if `len(window) >= max_requests`.
- **Limits**:
  - Regular user: `rate_limiter_user` → 10 req/minute
  - Admin: `rate_limiter_admin` → 100 req/minute
- **429 response** includes structured detail (limit, window, retry_after_seconds) plus standard headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`.
- **Admin bypass** — the endpoint inspects the JWT role and routes admin users to `rate_limiter_admin` (10× higher cap) instead of `rate_limiter_user`.
- **Production caveat**: In-memory deques don't survive restarts and don't share across replicas. For real scale, back it with Redis (`INCR` + `EXPIRE`, or sorted sets for sliding window).

### Test output (sample)

```bash
# 11th request within the minute → 429
$ for i in $(seq 1 15); do curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/ask \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"question":"test"}'; done
200
200
200
200
200
200
200
200
200
200
429
429
429
429
429
```

### Exercise 4.4 — Cost guard implementation (`04-api-gateway/production/cost_guard.py`)

**Approach**:
1. **Per-user daily budget** (`$1/day`) and **global daily budget** (`$10/day`) configured via constants.
2. Each user has a `UsageRecord` tracking `input_tokens`, `output_tokens`, `request_count`, and the calendar day (`YYYY-MM-DD`). When the day rolls over, a new record replaces the old one — automatic reset.
3. **Two-phase call** around the LLM:
   - `check_budget(user_id)` *before* the LLM call. Raises `503` if global budget exhausted, `402 Payment Required` if user budget exhausted.
   - `record_usage(user_id, input_tokens, output_tokens)` *after* the LLM call to accumulate real spend.
4. **Pricing** uses GPT-4o-mini defaults: $0.15 / 1M input tokens, $0.60 / 1M output tokens.
5. **Warning threshold** at 80% — logs a warning so operators can investigate before a hard block.

**Production-grade notes** (documented in the module):
- In-memory storage is single-instance only. Replace with Redis (`HINCRBYFLOAT` + daily-expiring keys) so multiple replicas share a single ledger.
- Estimated cost (`check_budget`) should use the same token count as the provider returns; track drift.
- Add an audit trail (append-only log) for finance/compliance.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 — Health and readiness checks

Two endpoints with different contracts:

- **`/health` (liveness probe)** — "Is the process alive?" Returns `200` while the process runs. The orchestrator (Render/Railway/Kubernetes) restarts the container on non-2xx.
- **`/ready` (readiness probe)** — "Is the process ready to serve traffic?" Returns `503` until warm (connections established, caches preloaded); the load balancer only routes to instances that return `200`.

The distinction matters: an instance can be *alive but not ready* during startup or during a temporary Redis outage. If you used the same endpoint for both, the platform would kill a recoverable instance instead of just pulling it from the LB.

In `06-lab-complete/app/main.py` both probes are implemented: `health()` always returns uptime + version, while `ready()` raises `503` until the lifespan startup sets `_is_ready = True`.

### Exercise 5.2 — Graceful shutdown

Two layers:

1. **`signal.signal(signal.SIGTERM, handle_sigterm)`** — registers a handler at startup. When the platform sends SIGTERM (standard shutdown signal), the handler logs the event; uvicorn then stops accepting new connections but lets in-flight requests finish.
2. **`lifespan` async context** (`@asynccontextmanager`) — the code after `yield` runs on shutdown: flips `_is_ready = False` (so `/ready` returns 503 immediately, pulling the instance from the LB), then logs a clean shutdown event. In Lab 06 `uvicorn.run(..., timeout_graceful_shutdown=30)` gives in-flight requests up to 30 seconds before force-kill.

Without this, the container dies mid-request → dropped responses → client sees a 502 from the load balancer.

### Exercise 5.3 — Stateless design

The problem with in-memory state across replicas:

```
Replica 1: user A → request 1 → conversation_history[A] = [...]
Replica 2: user A → request 2 → conversation_history[A] is empty (different process)
```

Fix: push all shared state into an external store (Redis in this lab). `05-scaling-reliability/production/app.py` does this:

- `save_session(session_id, data, ttl=3600)` → `SETEX session:<id>` with JSON payload.
- `load_session(session_id)` → `GET session:<id>`.
- `append_to_history` mutates the history in Redis, capped at 20 messages to prevent unbounded growth.

TTL on the key gives automatic cleanup of stale sessions — no background sweeper needed.

Any replica can now serve any request for any user. Horizontal scaling just works.

### Exercise 5.4 — Load balancing (`05-scaling-reliability/production/docker-compose.yml`)

The compose stack runs 3 replicas of the agent, 1 Redis, and 1 Nginx:

- **Nginx** (`nginx:alpine`) binds host `:8080` → internal `:80`, reads `nginx.conf`, and load-balances across the 3 agent instances on the `agent_net` bridge network.
- **Agent** has `deploy.replicas: 3`, CPU/memory limits (`0.5 CPU`, `256 MB`), and a container-level healthcheck — Nginx pulls an instance from the pool when it fails.
- **Redis** has its own healthcheck; agent depends on `redis: service_healthy` so agents only start after Redis is ready.
- Agents are **not** published on the host — only reachable via Nginx. This is the correct topology: clients hit the LB, never the backend directly.

Scaling command: `docker compose up --scale agent=3`. In production, swap `deploy.replicas: 3` for your orchestrator's autoscaler (Kubernetes HPA, Render autoscale, etc.).

### Exercise 5.5 — Stateless test (`test_stateless.py`)

The script validates the stateless property:

1. Create a session, send a few messages → populates `history` in Redis.
2. Kill a random agent instance (`docker kill <container>`).
3. Send another message in the same session → check that `history` still contains the earlier messages.

If state lived in memory, step 3 would return an empty history. Because it lives in Redis, any surviving instance reads the same session. This is the definition of stateless-correct.

### Summary table of Part 5 patterns

| Pattern | Implementation | Why it matters |
|---|---|---|
| Liveness probe | `/health` returns uptime | Platform restarts crashed processes |
| Readiness probe | `/ready` returns 503 until warm | LB avoids cold/unavailable instances |
| Graceful shutdown | SIGTERM handler + lifespan teardown | No dropped requests during deploy |
| Stateless | Redis session store, no in-memory dicts | Horizontal scaling + replica failover |
| Load balancing | Nginx in front of 3 replicas | Traffic distribution + high availability |
| Resource limits | `cpus: 0.5`, `memory: 256M` | Noisy neighbors can't take down the host |
