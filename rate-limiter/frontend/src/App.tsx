import React, { useState } from 'react'
import StatCard from './components/StatCard'
import LiveChart from './components/LiveChart'
import ClientTable from './components/ClientTable'
import { useStatsStream } from './hooks/useStatsStream'

interface LogEntry {
  id: number
  status: number
  allowed: boolean
  apiKey: string
  retryAfter?: number
  ts: string
}

let logId = 0

const API_KEYS = [
  { value: 'free-key-001', label: 'free-key-001 (Free tier)' },
  { value: 'pro-key-001',  label: 'pro-key-001 (Pro tier)' },
  { value: 'ent-key-001',  label: 'ent-key-001 (Enterprise tier)' },
  { value: 'unknown-key',  label: 'unknown-key (Defaults to Free)' },
]

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toString()
}

export default function App() {
  const { snapshot, history, connectionState } = useStatsStream('/stream/stats')
  const [selectedKey, setSelectedKey] = useState(API_KEYS[0].value)
  const [sending, setSending] = useState(false)
  const [log, setLog] = useState<LogEntry[]>([])
  const [burstCount, setBurstCount] = useState(5)

  const totals = snapshot?.totals ?? { requests: 0, allowed: 0, blocked: 0, redis_errors: 0, block_rate: 0 }
  const clients = snapshot?.clients ?? []

  async function sendRequests() {
    setSending(true)
    const count = burstCount
    for (let i = 0; i < count; i++) {
      try {
        const res = await fetch('/api/products', {
          headers: { 'X-API-Key': selectedKey },
        })
        const retryAfter = res.headers.get('Retry-After')
        const entry: LogEntry = {
          id: ++logId,
          status: res.status,
          allowed: res.status === 200,
          apiKey: selectedKey,
          retryAfter: retryAfter ? parseFloat(retryAfter) : undefined,
          ts: new Date().toLocaleTimeString(),
        }
        setLog(prev => [entry, ...prev].slice(0, 50))
      } catch (err) {
        const entry: LogEntry = {
          id: ++logId,
          status: 0,
          allowed: false,
          apiKey: selectedKey,
          ts: new Date().toLocaleTimeString(),
        }
        setLog(prev => [entry, ...prev].slice(0, 50))
      }
      // Small delay between requests for visibility
      if (i < count - 1) await new Promise(r => setTimeout(r, 80))
    }
    setSending(false)
  }

  return (
    <div className="app">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">🛡️</div>
          <div>
            <div className="header-title">Rate Limiter Dashboard</div>
            <div className="header-subtitle">Distributed Redis-backed · Token Bucket + Sliding Window</div>
          </div>
        </div>
        <div className="connection-badge">
          <div className={`connection-dot ${connectionState === 'error' ? 'error' : ''}`} />
          <span style={{ color: connectionState === 'connected' ? '#10b981' : connectionState === 'error' ? '#ef4444' : '#f59e0b' }}>
            {connectionState === 'connected' ? 'Live' : connectionState === 'error' ? 'Reconnecting…' : 'Connecting…'}
          </span>
        </div>
      </header>

      {/* ── Stat Cards ─────────────────────────────────────────── */}
      <div className="stat-cards">
        <StatCard
          icon="📈"
          label="Total Requests"
          value={formatNumber(totals.requests)}
          sub="since server start"
          accentColor="linear-gradient(90deg, #00d4ff, #0099cc)"
          iconBg="rgba(0, 212, 255, 0.12)"
        />
        <StatCard
          icon="✅"
          label="Allowed"
          value={formatNumber(totals.allowed)}
          sub={`${totals.requests > 0 ? Math.round(totals.allowed / totals.requests * 100) : 0}% of requests`}
          accentColor="linear-gradient(90deg, #10b981, #059669)"
          iconBg="rgba(16, 185, 129, 0.12)"
        />
        <StatCard
          icon="🚫"
          label="Blocked"
          value={formatNumber(totals.blocked)}
          sub={`${totals.block_rate}% block rate`}
          accentColor="linear-gradient(90deg, #ef4444, #dc2626)"
          iconBg="rgba(239, 68, 68, 0.12)"
        />
        <StatCard
          icon="⚡"
          label="Block Rate"
          value={`${totals.block_rate}%`}
          sub={totals.redis_errors > 0 ? `⚠️ ${totals.redis_errors} Redis errors` : 'All systems nominal'}
          accentColor={totals.block_rate > 30 ? 'linear-gradient(90deg, #ef4444, #dc2626)' : 'linear-gradient(90deg, #f59e0b, #d97706)'}
          iconBg={totals.block_rate > 30 ? 'rgba(239, 68, 68, 0.12)' : 'rgba(245, 158, 11, 0.12)'}
        />
      </div>

      {/* ── Live Chart ─────────────────────────────────────────── */}
      <div className="glass-panel">
        <div className="panel-header">
          <div className="panel-title">
            📊 Live Traffic (per second)
          </div>
          <div className="panel-badge">Last 2 minutes</div>
        </div>
        <div className="panel-body">
          <LiveChart history={history} />
        </div>
      </div>

      {/* ── Bottom two-column ──────────────────────────────────── */}
      <div className="two-col">
        {/* Client Table */}
        <div className="glass-panel">
          <div className="panel-header">
            <div className="panel-title">
              👥 Client Activity
            </div>
            <div className="panel-badge">{clients.length} active</div>
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            <ClientTable clients={clients} />
          </div>
        </div>

        {/* Test Fire Panel */}
        <div className="glass-panel">
          <div className="panel-header">
            <div className="panel-title">🔫 Fire Test Requests</div>
          </div>
          <div className="panel-body">
            <div className="test-form">
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label" htmlFor="api-key-select">API Key</label>
                  <select
                    id="api-key-select"
                    className="form-select"
                    value={selectedKey}
                    onChange={e => setSelectedKey(e.target.value)}
                  >
                    {API_KEYS.map(k => (
                      <option key={k.value} value={k.value}>{k.label}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group" style={{ maxWidth: 120 }}>
                  <label className="form-label" htmlFor="burst-count">Count</label>
                  <input
                    id="burst-count"
                    type="number"
                    className="form-input"
                    min={1}
                    max={100}
                    value={burstCount}
                    onChange={e => setBurstCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))}
                  />
                </div>
              </div>
              <button
                id="fire-requests-btn"
                className="btn btn-primary"
                onClick={sendRequests}
                disabled={sending}
              >
                {sending ? <><span className="spinner" /> Sending…</> : '🚀 Send Requests'}
              </button>

              {/* Request Log */}
              {log.length > 0 && (
                <div>
                  <div className="form-label" style={{ marginBottom: 8 }}>Request Log</div>
                  <div className="request-log">
                    {log.map(entry => (
                      <div key={entry.id} className={`log-entry ${entry.allowed ? 'allowed' : 'blocked'}`}>
                        <span className="log-status">{entry.status || 'ERR'}</span>
                        <span className="log-message">
                          {entry.allowed
                            ? '/api/products → OK'
                            : `/api/products → Rate Limited${entry.retryAfter ? ` (retry in ${entry.retryAfter.toFixed(1)}s)` : ''}`}
                        </span>
                        <span className="log-time">{entry.ts}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
