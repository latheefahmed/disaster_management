import { useEffect, useMemo, useState } from 'react'
import Section from '../shared/Section'
import StatCard from '../shared/StatCard'
import EmptyState from '../shared/EmptyState'

import { BACKEND_PATHS } from '../../data/backendPaths'
import { useAuth } from '../../auth/AuthContext'
import { downloadCsv } from '../../utils/csv'

type DistrictRequest = {
  id: number
  run_id?: number
  state_code: string
  district_code: string
  resource_id: string
  quantity: number
  time: number
  priority?: number
  urgency?: number
  confidence?: number
  source?: string
  status: string
}

type ResourceMeta = {
  resource_id: string
  resource_name: string
}

export default function StateRequests() {
  const { stateCode, token } = useAuth()

  const [requests, setRequests] = useState<DistrictRequest[]>([])
  const [resources, setResources] = useState<ResourceMeta[]>([])
  const [loadError, setLoadError] = useState('')
  const [busyRequest, setBusyRequest] = useState<number | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>('')
  const [districtFilter, setDistrictFilter] = useState('')
  const [resourceFilter, setResourceFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  async function authFetch<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, {
      ...(init || {}),
      headers: {
        ...(init?.headers || {}),
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    })

    if (!res.ok) {
      throw new Error(`Request failed: ${res.status}`)
    }

    return await res.json()
  }

  /* ---------------- LOAD DATA ---------------- */

  useEffect(() => {
    if (!stateCode || !token) return

    async function load() {
      try {
        const settled = await Promise.allSettled([
          authFetch<DistrictRequest[]>(BACKEND_PATHS.stateRequests),
          authFetch<ResourceMeta[]>(BACKEND_PATHS.resourceCatalog)
        ])

        const reqRows = settled[0].status === 'fulfilled' ? settled[0].value : []
        const resourceRows = settled[1].status === 'fulfilled' ? settled[1].value : []

        setRequests(Array.isArray(reqRows) ? reqRows : [])
        setResources(Array.isArray(resourceRows) ? resourceRows : [])
        setLoadError('')
        setLastUpdatedAt(new Date().toLocaleTimeString())
      } catch (error) {
        setRequests([])
        setLoadError(error instanceof Error ? error.message : 'Failed to load state request data')
      }
    }

    load()
    const id = setInterval(load, 3000)
    return () => clearInterval(id)
  }, [stateCode, token])

  /* ---------------- DERIVED ---------------- */

  const stateRequests = useMemo(
    () => requests.filter(r => String(r.state_code) === String(stateCode)),
    [requests, stateCode]
  )

  const filteredRequests = useMemo(() => {
    const districtNeedle = districtFilter.trim().toLowerCase()
    const resourceNeedle = resourceFilter.trim().toLowerCase()

    return stateRequests.filter(r => {
      const districtMatch = !districtNeedle || String(r.district_code).toLowerCase().includes(districtNeedle)
      const resourceMatch = !resourceNeedle || String(r.resource_id).toLowerCase().includes(resourceNeedle)
      const statusMatch = statusFilter === 'all' || String(r.status) === statusFilter
      return districtMatch && resourceMatch && statusMatch
    })
  }, [stateRequests, districtFilter, resourceFilter, statusFilter])

  const groupedSummary = useMemo(() => {
    const grouped = new Map<string, { district_code: string; resource_id: string; status: string; total_quantity: number; row_count: number }>()
    for (const row of filteredRequests) {
      const key = `${row.district_code}_${row.resource_id}_${row.status}`
      const curr = grouped.get(key)
      if (curr) {
        curr.total_quantity += Number(row.quantity || 0)
        curr.row_count += 1
      } else {
        grouped.set(key, {
          district_code: String(row.district_code),
          resource_id: String(row.resource_id),
          status: String(row.status),
          total_quantity: Number(row.quantity || 0),
          row_count: 1,
        })
      }
    }
    return Array.from(grouped.values())
  }, [filteredRequests])

  const resourceNameMap = useMemo(() => {
    const out: Record<string, string> = {}
    for (const r of resources) out[r.resource_id] = r.resource_name
    return out
  }, [resources])

  async function escalate(requestId: number) {
    if (!token) return
    setBusyRequest(requestId)
    try {
      await authFetch(
        `${BACKEND_PATHS.stateEscalations}/${requestId}`,
        {
          method: 'POST',
          body: JSON.stringify({ reason: 'State escalation from dashboard' })
        }
      )

      const reqRows = await authFetch<DistrictRequest[]>(BACKEND_PATHS.stateEscalations)
      setRequests(Array.isArray(reqRows) ? reqRows : [])
      setLastUpdatedAt(new Date().toLocaleTimeString())
    } finally {
      setBusyRequest(null)
    }
  }

  /* ---------------- UI ---------------- */

  return (
    <div>
      <Section title={`State Requests & Rebalancing (State ${stateCode})`}>
        <div className="grid grid-cols-3 gap-4 mb-6">
          <StatCard
            label="Active District Requests"
            value={stateRequests.length.toString()}
          />
          <StatCard
            label="Escalation Candidates"
            value={stateRequests.filter(r => r.status !== 'escalated_national').length.toString()}
          />
          <StatCard
            label="Already Escalated"
            value={
              stateRequests.filter(r => r.status === 'escalated_national').length.toString()
            }
          />
        </div>
        <div className="text-xs text-slate-500">Last refresh: {lastUpdatedAt || '—'}</div>

        {loadError && (
          <div className="mt-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-sm text-red-700">{loadError}</div>
        )}

        <div className="mt-3 grid grid-cols-1 md:grid-cols-4 gap-2 text-sm">
          <input
            value={districtFilter}
            onChange={e => setDistrictFilter(e.target.value)}
            placeholder="Filter district"
            className="border rounded px-2 py-1"
          />
          <input
            value={resourceFilter}
            onChange={e => setResourceFilter(e.target.value)}
            placeholder="Filter resource"
            className="border rounded px-2 py-1"
          />
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="border rounded px-2 py-1"
          >
            <option value="all">All statuses</option>
            <option value="pending">pending</option>
            <option value="allocated">allocated</option>
            <option value="partial">partial</option>
            <option value="unmet">unmet</option>
            <option value="escalated_national">escalated_national</option>
          </select>
          <button
            className="px-3 py-1 rounded border"
            onClick={() => {
              setDistrictFilter('')
              setResourceFilter('')
              setStatusFilter('all')
            }}
          >
            Clear
          </button>
        </div>
      </Section>

      <Section title="Grouped Request Summary">
        {groupedSummary.length > 0 && (
          <div className="mb-2 flex gap-2">
            <button
              className="px-3 py-1 rounded border text-sm"
              onClick={() => downloadCsv(`state_${stateCode}_request_grouped_summary.csv`, groupedSummary)}
            >
              Export Grouped CSV
            </button>
            <button
              className="px-3 py-1 rounded border text-sm"
              onClick={() => downloadCsv(`state_${stateCode}_request_details.csv`, filteredRequests)}
            >
              Export Details CSV
            </button>
          </div>
        )}

        {groupedSummary.length === 0 && (
          <EmptyState message="No grouped rows for current filters." />
        )}

        {groupedSummary.length > 0 && (
          <div className="overflow-x-auto border rounded mb-4">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">District</th>
                  <th className="p-2">Resource</th>
                  <th className="p-2">Status</th>
                  <th className="p-2">Rows</th>
                  <th className="p-2">Quantity (sum)</th>
                </tr>
              </thead>
              <tbody>
                {groupedSummary.map((row, idx) => (
                  <tr key={`${row.district_code}_${row.resource_id}_${row.status}_${idx}`} className="border-t">
                    <td className="p-2">{row.district_code}</td>
                    <td className="p-2">{resourceNameMap[row.resource_id] || row.resource_id}</td>
                    <td className="p-2">{row.status}</td>
                    <td className="p-2">{row.row_count}</td>
                    <td className="p-2">{row.total_quantity.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="District Requests">
        {filteredRequests.length === 0 && (
          <EmptyState message="No pending district requests." />
        )}

        {filteredRequests.map(r => (
          <div
            key={r.id}
            className="border rounded-lg p-4 mb-3 bg-white"
          >
            <div className="font-semibold">
              {resourceNameMap[r.resource_id] || r.resource_id}
            </div>
            <div className="text-sm">District: {r.district_code}</div>
            <div className="text-sm">Qty: {r.quantity} | Time: {r.time}</div>
            <div className="text-xs text-slate-600">Run ID: {r.run_id ?? '—'}</div>
            <div className="text-xs text-slate-600">
              Priority {r.priority ?? 1} | Urgency {r.urgency ?? 1} | Confidence {r.confidence ?? 1} | Source {r.source ?? 'human'}
            </div>
            <div className="text-xs mt-1">Status: <b>{r.status}</b></div>

            {r.status !== 'escalated_national' && (
              <button
                className="mt-2 px-3 py-1 bg-amber-600 text-white rounded"
                disabled={busyRequest === r.id}
                onClick={() => escalate(r.id)}
              >
                {busyRequest === r.id ? 'Escalating...' : 'Escalate to National'}
              </button>
            )}
          </div>
        ))}
      </Section>
    </div>
  )
}
