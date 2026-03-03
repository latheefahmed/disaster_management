import { useEffect, useState } from 'react'

export type AuditAction =
  | 'REQUEST'
  | 'CLAIM'
  | 'CONSUME'
  | 'RETURN'
  | 'REALLOCATE'
  | 'EXPIRE'

export type AuditEvent = {
  actor_level: 'district' | 'state' | 'national' | 'admin'
  actor_id: string
  action: AuditAction
  resource_id: string
  quantity: number
  time: number
  timestamp: string

  request_context?: {
    priority?: number
    urgency?: 'Low' | 'Medium' | 'High' | 'Critical'
    confidence?: number
    source?: string
    notes?: string
  }
}

const STORAGE_KEY = 'audit_log'

function loadLog(): AuditEvent[] {
  const raw = localStorage.getItem(STORAGE_KEY)
  return raw ? JSON.parse(raw) : []
}

function saveLog(events: AuditEvent[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(events))
}

export function useAuditLog() {
  const [events, setEvents] = useState<AuditEvent[]>([])

  useEffect(() => {
    setEvents(loadLog())
  }, [])

  function logEvent(event: AuditEvent) {
    const updated = [...events, event]
    setEvents(updated)
    saveLog(updated)
  }

  return {
    events,
    logEvent
  }
}
