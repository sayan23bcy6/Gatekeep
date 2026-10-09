import { useState, useEffect, useRef, useCallback } from 'react'

export interface ClientStat {
  client_id: string
  allowed: number
  blocked: number
  last_seen: number
}

export interface Totals {
  requests: number
  allowed: number
  blocked: number
  redis_errors: number
  block_rate: number
}

export interface StatsSnapshot {
  totals: Totals
  clients: ClientStat[]
  ts: number
}

export type ConnectionState = 'connecting' | 'connected' | 'error'

const MAX_HISTORY = 120  // 2 minutes of 1-second ticks

export interface TimePoint {
  ts: number
  allowed: number
  blocked: number
}

export function useStatsStream(url: string = '/stream/stats') {
  const [snapshot, setSnapshot] = useState<StatsSnapshot | null>(null)
  const [history, setHistory] = useState<TimePoint[]>([])
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting')
  const esRef = useRef<EventSource | null>(null)
  const prevTotalsRef = useRef<Totals | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
    }
    setConnectionState('connecting')
    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => setConnectionState('connected')

    es.onmessage = (event) => {
      try {
        const data: StatsSnapshot = JSON.parse(event.data)
        setSnapshot(data)
        setConnectionState('connected')

        // Calculate per-second delta for the chart
        const prev = prevTotalsRef.current
        const deltaAllowed = prev ? Math.max(0, data.totals.allowed - prev.allowed) : 0
        const deltaBlocked = prev ? Math.max(0, data.totals.blocked - prev.blocked) : 0
        prevTotalsRef.current = data.totals

        setHistory(h => {
          const next = [...h, { ts: data.ts, allowed: deltaAllowed, blocked: deltaBlocked }]
          return next.length > MAX_HISTORY ? next.slice(next.length - MAX_HISTORY) : next
        })
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      setConnectionState('error')
      es.close()
      esRef.current = null
      // Reconnect after 3 seconds
      reconnectTimer.current = setTimeout(connect, 3000)
    }
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      esRef.current?.close()
      clearTimeout(reconnectTimer.current)
    }
  }, [connect])

  return { snapshot, history, connectionState }
}
