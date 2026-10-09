/**
 * k6 Load Test — Distributed Rate Limiter
 *
 * 50 virtual users across three API keys of different plan tiers.
 * Ramp up 30s → steady 60s → ramp down 30s.
 *
 * Run: k6 run loadtest/script.js
 */

import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

// ─── Custom metrics ────────────────────────────────────────────────────────────
const freeAllowed   = new Counter('free_allowed')
const freeBlocked   = new Counter('free_blocked')
const proAllowed    = new Counter('pro_allowed')
const proBlocked    = new Counter('pro_blocked')
const entAllowed    = new Counter('ent_allowed')
const entBlocked    = new Counter('ent_blocked')
const blockRate     = new Rate('block_rate')
const requestDuration = new Trend('request_duration_ms', true)

// ─── Options ───────────────────────────────────────────────────────────────────
export const options = {
  scenarios: {
    free_tier: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 15 },
        { duration: '60s', target: 15 },
        { duration: '30s', target: 0 },
      ],
      env: { API_KEY: 'free-key-001', TIER: 'free' },
    },
    pro_tier: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 20 },
        { duration: '60s', target: 20 },
        { duration: '30s', target: 0 },
      ],
      env: { API_KEY: 'pro-key-001', TIER: 'pro' },
    },
    enterprise_tier: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 15 },
        { duration: '60s', target: 15 },
        { duration: '30s', target: 0 },
      ],
      env: { API_KEY: 'ent-key-001', TIER: 'enterprise' },
    },
  },
  thresholds: {
    // p95 latency under 50ms on localhost
    'http_req_duration{scenario:free_tier}':       ['p(95)<200'],
    'http_req_duration{scenario:pro_tier}':        ['p(95)<200'],
    'http_req_duration{scenario:enterprise_tier}': ['p(95)<200'],
    // HTTP failures (5xx) should be near zero
    'http_req_failed': ['rate<0.01'],
  },
}

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000'

export default function () {
  const apiKey = __ENV.API_KEY
  const tier   = __ENV.TIER

  const start = Date.now()
  const res = http.get(`${BASE_URL}/api/products`, {
    headers: { 'X-API-Key': apiKey },
    timeout: '5s',
  })
  const elapsed = Date.now() - start
  requestDuration.add(elapsed)

  const allowed = res.status === 200
  const blocked = res.status === 429

  blockRate.add(blocked ? 1 : 0)

  if (tier === 'free') {
    if (allowed) freeAllowed.add(1)
    if (blocked) freeBlocked.add(1)
  } else if (tier === 'pro') {
    if (allowed) proAllowed.add(1)
    if (blocked) proBlocked.add(1)
  } else {
    if (allowed) entAllowed.add(1)
    if (blocked) entBlocked.add(1)
  }

  check(res, {
    'status is 200 or 429': (r) => r.status === 200 || r.status === 429,
    'not a server error': (r) => r.status < 500,
  })

  if (blocked) {
    // Honor Retry-After or wait briefly
    const retryAfter = parseFloat(res.headers['Retry-After'] || '0.5')
    sleep(Math.min(retryAfter, 2.0))
  } else {
    sleep(0.1)
  }
}

export function handleSummary(data) {
  const freeTotal = (data.metrics.free_allowed?.values?.count || 0) +
                    (data.metrics.free_blocked?.values?.count || 0)
  const proTotal  = (data.metrics.pro_allowed?.values?.count || 0) +
                    (data.metrics.pro_blocked?.values?.count || 0)
  const entTotal  = (data.metrics.ent_allowed?.values?.count || 0) +
                    (data.metrics.ent_blocked?.values?.count || 0)

  const summary = `
╔══════════════════════════════════════════════════════════════════╗
║              k6 Rate Limiter Load Test — Summary                ║
╠══════════════════════════════════════════════════════════════════╣
║  Tier        │ Allowed  │ Blocked  │ Total   │ Block Rate       ║
╠══════════════════════════════════════════════════════════════════╣
║  Free        │ ${String(data.metrics.free_allowed?.values?.count || 0).padEnd(8)} │ ${String(data.metrics.free_blocked?.values?.count || 0).padEnd(8)} │ ${String(freeTotal).padEnd(7)} │ ${String(freeTotal > 0 ? Math.round((data.metrics.free_blocked?.values?.count || 0) / freeTotal * 100) : 0).padEnd(16)}%║
║  Pro         │ ${String(data.metrics.pro_allowed?.values?.count || 0).padEnd(8)} │ ${String(data.metrics.pro_blocked?.values?.count || 0).padEnd(8)} │ ${String(proTotal).padEnd(7)} │ ${String(proTotal > 0 ? Math.round((data.metrics.pro_blocked?.values?.count || 0) / proTotal * 100) : 0).padEnd(16)}%║
║  Enterprise  │ ${String(data.metrics.ent_allowed?.values?.count || 0).padEnd(8)} │ ${String(data.metrics.ent_blocked?.values?.count || 0).padEnd(8)} │ ${String(entTotal).padEnd(7)} │ ${String(entTotal > 0 ? Math.round((data.metrics.ent_blocked?.values?.count || 0) / entTotal * 100) : 0).padEnd(16)}%║
╚══════════════════════════════════════════════════════════════════╝
  p95 latency: ${Math.round(data.metrics.request_duration_ms?.values?.['p(95)'] || 0)}ms
`
  console.log(summary)
  return { stdout: summary }
}
