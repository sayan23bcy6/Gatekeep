import React from 'react'
import type { ClientStat } from '../hooks/useStatsStream'

interface ClientTableProps {
  clients: ClientStat[]
}

const PLAN_MAP: Record<string, string> = {
  'free-key-001': 'free',
  'pro-key-001': 'pro',
  'ent-key-001': 'enterprise',
}

function getPlan(clientId: string): string {
  return PLAN_MAP[clientId] ?? 'free'
}

function formatTime(ts: number): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleTimeString()
}

const ClientTable: React.FC<ClientTableProps> = ({ clients }) => {
  if (clients.length === 0) {
    return (
      <div className="empty-state">
        <div style={{ fontSize: '32px', marginBottom: '8px' }}>🔍</div>
        <p>No client activity yet. Send some requests!</p>
      </div>
    )
  }

  const sorted = [...clients].sort((a, b) => b.allowed + b.blocked - (a.allowed + a.blocked))

  return (
    <table className="client-table">
      <thead>
        <tr>
          <th>Client</th>
          <th>Plan</th>
          <th>Allowed</th>
          <th>Blocked</th>
          <th>Block Rate</th>
          <th>Last Seen</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(client => {
          const total = client.allowed + client.blocked
          const blockRate = total > 0 ? Math.round(client.blocked / total * 100) : 0
          const isThrottled = client.blocked > 0 && blockRate > 10
          const plan = getPlan(client.client_id)

          return (
            <tr key={client.client_id}>
              <td>
                <span className="client-id">{client.client_id}</span>
              </td>
              <td>
                <span className={`plan-badge ${plan}`}>{plan}</span>
              </td>
              <td style={{ color: '#10b981', fontWeight: 600 }}>
                {client.allowed.toLocaleString()}
              </td>
              <td style={{ color: client.blocked > 0 ? '#ef4444' : 'var(--text-muted)', fontWeight: client.blocked > 0 ? 600 : 400 }}>
                {client.blocked.toLocaleString()}
              </td>
              <td style={{ color: blockRate > 20 ? '#ef4444' : blockRate > 5 ? '#f59e0b' : 'var(--text-muted)' }}>
                {blockRate}%
              </td>
              <td>{formatTime(client.last_seen)}</td>
              <td>
                <span className={`status-badge ${isThrottled ? 'throttled' : 'ok'}`}>
                  <span className="status-dot" />
                  {isThrottled ? 'Throttled' : 'OK'}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default ClientTable
