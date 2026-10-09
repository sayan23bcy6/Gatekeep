import React from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, Area, AreaChart
} from 'recharts'
import type { TimePoint } from '../hooks/useStatsStream'

interface LiveChartProps {
  history: TimePoint[]
}

const formatTime = (ts: number) => {
  const d = new Date(ts * 1000)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        background: 'rgba(10, 22, 40, 0.95)',
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: '10px',
        padding: '12px 16px',
        fontSize: '13px',
      }}>
        <p style={{ color: '#8ba4c4', marginBottom: '8px', fontSize: '11px' }}>{formatTime(label)}</p>
        {payload.map((p: any) => (
          <p key={p.name} style={{ color: p.color, fontWeight: 600 }}>
            {p.name}: {p.value}
          </p>
        ))}
      </div>
    )
  }
  return null
}

const LiveChart: React.FC<LiveChartProps> = ({ history }) => {
  const data = history.map(p => ({
    ts: p.ts,
    Allowed: p.allowed,
    Blocked: p.blocked,
  }))

  if (data.length === 0) {
    return (
      <div className="chart-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="empty-state">
          <div style={{ fontSize: '32px', marginBottom: '8px' }}>📊</div>
          <p>Waiting for data stream…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="chart-container">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
          <defs>
            <linearGradient id="gradAllowed" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#00d4ff" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#00d4ff" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradBlocked" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#ef4444" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
          <XAxis
            dataKey="ts"
            tickFormatter={formatTime}
            tick={{ fill: '#4a6080', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: '#4a6080', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            formatter={(value) => (
              <span style={{ color: '#8ba4c4', fontSize: '12px', fontWeight: 500 }}>{value}/sec</span>
            )}
          />
          <Area
            type="monotone"
            dataKey="Allowed"
            stroke="#00d4ff"
            strokeWidth={2}
            fill="url(#gradAllowed)"
            dot={false}
            activeDot={{ r: 4, fill: '#00d4ff' }}
          />
          <Area
            type="monotone"
            dataKey="Blocked"
            stroke="#ef4444"
            strokeWidth={2}
            fill="url(#gradBlocked)"
            dot={false}
            activeDot={{ r: 4, fill: '#ef4444' }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export default LiveChart
