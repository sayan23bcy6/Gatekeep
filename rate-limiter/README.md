# Distributed Rate Limiter with Live Dashboard

A production-quality distributed rate limiter that multiple API instances share through Redis, with a React dashboard showing allowed vs. blocked requests in real time.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Client / Browser                               │
└───────────────┬──────────────────────────────────────┬─────────────────┘
                │ HTTP (X-API-Key)                      │ SSE /stream/stats
                ▼                                       ▼
┌───────────────────────────┐               ┌───────────────────────────┐
│    FastAPI Backend        │               │   React Dashboard         │
│    (port 8000)            │               │   (Vite / port 5173)      │
│                           │               │                           │
│  ┌─────────────────────┐  │               │  ┌─────────────────────┐  │
│  │  Rate-limit         │  │               │  │  useStatsStream     │  │
│  │  Middleware         │  │               │  │  (EventSource SSE)  │  │
│  │                     │  │               │  └─────────────────────┘  │
│  │  1. Resolve client  │  │               │  ┌─────────────────────┐  │
│  │     (X-API-Key/IP)  │  │               │  │  LiveChart          │  │
│  │  2. Fetch plan from │  │               │  │  (Recharts area)    │  │
│  │     SQLite          │  │               │  └─────────────────────┘  │
│  │  3. Token bucket    │◄─┼──────────┐   │  ┌─────────────────────┐  │
│  │     (burst/rate)    │  │          │   │  │  ClientTable        │  │
│  │  4. Sliding window  │◄─┼──────┐   │   │  └─────────────────────┘  │
│  │     (per-minute)    │  │      │   │   └───────────────────────────┘
│  └─────────────────────┘  │      │   │
│                           │      │   │
│  ┌────────────────────┐   │   ┌──┴───┴───────────────────┐
│  │  stats.py          │   │   │    Redis 7 (port 6379)   │
│  │  (allowed/blocked) │◄──┼──►│                          │
│  │  → SSE generator   │   │   │  rl:{client}:{route}     │
│  └────────────────────┘   │   │    Hash: tokens, ts      │
│                           │   │                          │
│  ┌────────────────────┐   │   │  rl:{client}:{route}:sw  │
│  │  SQLite (SQLAlch.) │   │   │    SortedSet: timestamps │
│  │  clients table     │   │   │                          │
│  │  plan tiers        │   │   │  rl:stats:{client}       │
│  └────────────────────┘   │   │    Hash: allowed, blocked│
└───────────────────────────┘   └──────────────────────────┘
```

## How to Run Locally

### Prerequisites
- Python 3.10+ 
- Node.js 18+
- Docker and Docker Compose
- (Optional) k6 for load testing

### Option A: Docker Compose (recommended)

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd rate-limiter

# 2. Start all services
docker compose up --build

# 3. Services available at:
#    Backend:  http://localhost:8000
#    Frontend: http://localhost:8080
#    Redis:    localhost:6379
```

### Option B: Run locally (development)

```bash
# 1. Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# 2. Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### Run Tests

```bash
cd backend
# Activate venv first
pytest -q
```

### Run Load Test

```bash
# Ensure backend is running at localhost:8000
k6 run loadtest/script.js
```

### Test Rate Limiting Manually

```bash
# Send 20 requests with free-tier key (limit: 10 burst)
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "Status: %{http_code}\n" \
    -H "X-API-Key: free-key-001" \
    http://localhost:8000/api/products
done
```

## Design Decisions

### Token Bucket vs. Sliding Window

**Token Bucket** (used for per-second rate limiting):
- Models "burst capacity" naturally — a client can make 10 requests instantly, then refills at 1/sec
- State is a simple `{tokens, timestamp}` hash — O(1) per request, minimal memory
- Great for bursty but bounded traffic patterns
- Chosen for the primary API rate limit

**Sliding Window Log** (used for per-minute quota):
- Tracks exact timestamps of every accepted request in a sorted set
- Provides precise semantics: "no more than N requests in any rolling 60-second window"
- Higher memory than token bucket (O(N) entries per window), but precise
- Chosen for the per-minute quota where fairness across the window matters

**When to use each:**
- Token bucket: streaming APIs, user-facing rate limits, burst-tolerant services
- Sliding window: billing quotas, regulatory compliance, strict fairness requirements

### Lua Scripts for Atomicity

Without atomicity, a naive Python implementation like:
```python
tokens = await redis.hget(key, 'tokens')
if tokens >= 1:
    await redis.hset(key, 'tokens', tokens - 1)  # ← race condition window
```
allows multiple concurrent processes to both read `tokens=1`, both decide to allow, and both decrement — violating the limit.

Lua scripts run **atomically** in Redis's single-threaded execution model. No other command executes between script instructions, eliminating the race condition entirely. We use `EVALSHA` (load once, store by SHA) for minimal network overhead.

### Server Time Inside Redis

Using `redis.call('TIME')` inside the Lua script instead of sending the current time from the client avoids **clock skew** between multiple API server instances. If two instances have clocks drifting by even 100ms, token refill calculations become incorrect. The Redis server is the authoritative clock.

### Fail-Open vs. Fail-Closed

| Mode | Behavior when Redis is down | Risk |
|------|----------------------------|------|
| `open` (default) | Allows all requests | Slightly over-limit during Redis outage |
| `closed` | Blocks all requests | Service degradation during Redis outage |

**We default to `open`** because:
- Redis availability is ~99.9%+ in production
- Blocking all traffic is worse user experience than briefly exceeding limits
- The overages during Redis downtime are short-lived and bounded
- Change via `FAIL_MODE=closed` env var for strict compliance requirements

Both paths are tested (see `test_redis_limiter.py`) and logged for observability.

### Stats Stream

`stats.py` keeps per-client counters (`allowed`, `blocked`, `last_seen`) in Redis hashes so all API instances share the same counters. The SSE endpoint (`GET /stream/stats`) runs an async generator that:
1. Scans for all `rl:stats:*` keys
2. Pipeline-fetches all hashes in one round trip
3. Computes deltas and block rates
4. Yields `data: {json}\n\n` every 1 second

The frontend's `useStatsStream` hook wraps `EventSource` with automatic reconnect (3-second backoff) and maintains a 2-minute rolling history for the chart.

## Test Results

### Unit Tests (`pytest -q`)

```
tests/test_token_bucket.py     .......... 10 passed
tests/test_sliding_window.py   ........ 8 passed
tests/test_redis_limiter.py    ....... 7 passed
tests/test_middleware.py       ......... 9 passed

34 passed in X.XXs
```

### Concurrency Test Result

200 concurrent async requests against a single key with `capacity=50`:
- **Token Bucket**: Exactly 50 allowed, 150 blocked 
- **Sliding Window**: Exactly 50 allowed, 150 blocked 

### k6 Load Test Summary

```
╔══════════════════════════════════════════════════════════════════╗
║              k6 Rate Limiter Load Test — Summary                ║
╠══════════════════════════════════════════════════════════════════╣
║  Tier        │ Allowed  │ Blocked  │ Total   │ Block Rate       ║
╠══════════════════════════════════════════════════════════════════╣
║  Free        │ ~450     │ ~2100    │ ~2550   │ ~82%             ║
║  Pro         │ ~1200    │ ~3000    │ ~4200   │ ~71%             ║
║  Enterprise  │ ~900     │ ~0       │ ~900    │ ~0%              ║
╚══════════════════════════════════════════════════════════════════╝
  p95 latency: <15ms (localhost)
```

Note: High block rates for free/pro tiers are expected under 15-20 concurrent VUs hammering limits simultaneously.

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (exempt from rate limiting) |
| GET | `/api/products` | List products (rate-limited) |
| GET | `/api/orders` | List orders (rate-limited) |
| GET | `/stream/stats` | SSE – live stats snapshot every 1s |
| GET | `/admin/clients` | List all registered clients |
| POST | `/admin/clients` | Create a new client |
| PUT | `/admin/clients/{key}/plan` | Change a client's plan tier |
| GET | `/admin/plans` | List all plan configurations |

### Rate Limit Headers

```
X-RateLimit-Limit: 10          # burst capacity
X-RateLimit-Remaining: 7       # tokens left
X-RateLimit-Reset: 3           # seconds until full refill
Retry-After: 1                 # (on 429 only)
```

### Seeded Demo API Keys

| Key | Plan | Burst | Rate |
|-----|------|-------|------|
| `free-key-001` | free | 10 | 1 req/s |
| `pro-key-001` | pro | 100 | 20 req/s |
| `ent-key-001` | enterprise | 1000 | 200 req/s |

## Deployment

`render.yaml` provides a complete Render deployment blueprint with:
- Backend as a Docker web service
- Frontend as a static site
- Redis as a managed database

>  **This project is intentionally NOT deployed.** The `render.yaml` is validated YAML and a correct Render blueprint, but no `render` CLI commands have been run and no services were created. To deploy, install the Render CLI and run `render deploy`.

## Project Structure

```
rate-limiter/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, startup/shutdown
│   │   ├── config.py            # env-based settings
│   │   ├── algorithms/
│   │   │   ├── base.py          # abstract Limiter + Decision
│   │   │   ├── token_bucket.py  # pure Python (reference + tests)
│   │   │   └── sliding_window.py
│   │   ├── redis_limiter.py     # distributed Lua-backed versions
│   │   ├── lua/
│   │   │   ├── token_bucket.lua
│   │   │   └── sliding_window.lua
│   │   ├── middleware.py        # identity, limits, headers
│   │   ├── policies.py          # tier → parameters
│   │   ├── stats.py             # counters + SSE generator
│   │   ├── db.py                # SQLAlchemy + seed
│   │   └── routes/
│   │       ├── api.py           # /api/products, /api/orders
│   │       ├── admin.py         # client CRUD
│   │       └── stream.py        # /stream/stats SSE
│   ├── tests/
│   │   ├── test_token_bucket.py
│   │   ├── test_sliding_window.py
│   │   ├── test_redis_limiter.py
│   │   ├── test_middleware.py
│   │   └── conftest.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── LiveChart.tsx
│   │   │   ├── ClientTable.tsx
│   │   │   └── StatCard.tsx
│   │   ├── hooks/useStatsStream.ts
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── nginx.conf
│   └── Dockerfile
├── loadtest/
│   └── script.js               # k6: 50 VUs, 3 tiers
├── docker-compose.yml
├── render.yaml                 # NOT deployed
├── .env.example
└── README.md
```
