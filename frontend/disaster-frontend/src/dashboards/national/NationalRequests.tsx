import { useEffect, useMemo, useState } from 'react'
import Section from '../shared/Section'
import StatCard from '../shared/StatCard'
import EmptyState from '../shared/EmptyState'

import { BACKEND_PATHS } from '../../data/backendPaths'
import { useAuth } from '../../auth/AuthContext'
import { downloadCsv } from '../../utils/csv'

type EscalationRequest = {
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

export default function NationalRequests() {
  const { token } = useAuth()

  const [escalations, setEscalations] = useState<EscalationRequest[]>([])
  const [nationalStock, setNationalStock] = useState<Record<string, number>>({})
  const [globalPoolTotal, setGlobalPoolTotal] = useState<number>(0)
  const [resources, setResources] = useState<ResourceMeta[]>([])
  const [loadError, setLoadError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>('')
  const [stateFilter, setStateFilter] = useState('')
  const [districtFilter, setDistrictFilter] = useState('')
  const [resourceFilter, setResourceFilter] = useState('')

  async function authFetch<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, {
      ...(init || {}),
      headers: {
        ...(init?.headers || {}),
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    })

    if (!res.ok) throw new Error(`Request failed: ${res.status}`)
    return await res.json()
  }

  /* ---------------- LOAD DATA ---------------- */

  useEffect(() => {
    if (!token) return

    async function load() {
      try {
        const settled = await Promise.allSettled([
          authFetch<EscalationRequest[]>(BACKEND_PATHS.nationalEscalations),
          authFetch<{ resource_id: string; quantity: number }[]>(`${BACKEND_PATHS.nationalAllocations}/stock`),
          authFetch<ResourceMeta[]>(BACKEND_PATHS.resourceCatalog),
          authFetch<{ total_quantity: number; rows: Array<{ resource_id: string; time: number; quantity: number }> }>(BACKEND_PATHS.nationalPool),
        ])

        const escRows = settled[0].status === 'fulfilled' ? settled[0].value : []
        const stockRows = settled[1].status === 'fulfilled' ? settled[1].value : []
        const resourceRows = settled[2].status === 'fulfilled' ? settled[2].value : []
        const poolData = settled[3].status === 'fulfilled' ? settled[3].value : { total_quantity: 0, rows: [] }

        setEscalations(Array.isArray(escRows) ? escRows : [])
        setResources(Array.isArray(resourceRows) ? resourceRows : [])

        const map: Record<string, number> = {}
        for (const row of stockRows || []) {
          map[row.resource_id] = row.quantity
        }
        setNationalStock(map)
        setGlobalPoolTotal(Number(poolData?.total_quantity || 0))
        setLoadError('')
        setLastUpdatedAt(new Date().toLocaleTimeString())
      } catch (error) {
        setEscalations([])
        setLoadError(error instanceof Error ? error.message : 'Failed to load national request data')
      }
    }

    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [token])

  /* ---------------- DERIVED ---------------- */

  const escalationRequests = useMemo(
    () => escalations.filter(r => r.status === 'escalated_national'),
    [escalations]
  )

  const filteredEscalations = useMemo(() => {
    const stateNeedle = stateFilter.trim().toLowerCase()
    const districtNeedle = districtFilter.trim().toLowerCase()
    const resourceNeedle = resourceFilter.trim().toLowerCase()
    return escalationRequests.filter(r => {
      const stateMatch = !stateNeedle || String(r.state_code).toLowerCase().includes(stateNeedle)
      const districtMatch = !districtNeedle || String(r.district_code).toLowerCase().includes(districtNeedle)
      const resourceMatch = !resourceNeedle || String(r.resource_id).toLowerCase().includes(resourceNeedle)
      return stateMatch && districtMatch && resourceMatch
    })
  }, [escalationRequests, stateFilter, districtFilter, resourceFilter])

  const groupedSummary = useMemo(() => {
    const grouped = new Map<string, { state_code: string; district_code: string; resource_id: string; row_count: number; quantity: number }>()
    for (const row of filteredEscalations) {
      const key = `${row.state_code}_${row.district_code}_${row.resource_id}`
      const curr = grouped.get(key)
      if (curr) {
        curr.row_count += 1
        curr.quantity += Number(row.quantity || 0)
      } else {
        grouped.set(key, {
          state_code: String(row.state_code),
          district_code: String(row.district_code),
          resource_id: String(row.resource_id),
          row_count: 1,
          quantity: Number(row.quantity || 0),
        })
      }
    }
    return Array.from(grouped.values())
  }, [filteredEscalations])

  const resourceNameMap = useMemo(() => {
    const out: Record<string, string> = {}
    for (const row of resources) out[row.resource_id] = row.resource_name
    return out
  }, [resources])

  async function resolve(requestId: number, decision: 'allocated' | 'partial' | 'unmet') {
    if (!token) return
    setBusyId(requestId)
    try {
      const row = escalations.find(r => r.id === requestId)
      if (row && (decision === 'allocated' || decision === 'partial')) {
        const qty = decision === 'allocated' ? Number(row.quantity) : Number(row.quantity) / 2
        if (qty > 0) {
          await authFetch(
            BACKEND_PATHS.nationalPoolAllocate,
            {
              method: 'POST',
              body: JSON.stringify({
                state_code: row.state_code,
                resource_id: row.resource_id,
                time: row.time,
                quantity: qty,
                target_district: row.district_code,
                note: `national escalation resolution ${decision}`
              })
            }
          )
        }
      }

      await authFetch(
        `${BACKEND_PATHS.nationalEscalations}/${requestId}/resolve`,
        {
          method: 'POST',
          body: JSON.stringify({ decision, note: `Resolved from national dashboard as ${decision}` })
        }
      )

      const rows = await authFetch<EscalationRequest[]>(BACKEND_PATHS.nationalEscalations)
      setEscalations(Array.isArray(rows) ? rows : [])
      setLastUpdatedAt(new Date().toLocaleTimeString())
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <Section title="National Escalation & Reserve Allocation">
        <div className="grid grid-cols-3 gap-4 mb-6">
          <StatCard
            label="Escalated Requests"
            value={escalationRequests.length.toString()}
          />
          <StatCard
            label="Resources in National Reserve"
            value={Object.keys(nationalStock).length.toString()}
          />
          <StatCard
            label="Global Pool Quantity"
            value={globalPoolTotal.toFixed(2)}
          />
        </div>
        <div className="text-xs text-slate-500">Last refresh: {lastUpdatedAt || '—'}</div>

        {loadError && (
          <div className="mt-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-sm text-red-700">{loadError}</div>
        )}

        <div className="mt-3 grid grid-cols-1 md:grid-cols-4 gap-2 text-sm">
          <input
            value={stateFilter}
            onChange={e => setStateFilter(e.target.value)}
            placeholder="Filter state"
            className="border rounded px-2 py-1"
          />
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
          <button
            className="px-3 py-1 rounded border"
            onClick={() => {
              setStateFilter('')
              setDistrictFilter('')
              setResourceFilter('')
            }}
          >
            Clear
          </button>
        </div>
      </Section>

      <Section title="Escalation Group Summary">
        {groupedSummary.length > 0 && (
          <div className="mb-2 flex gap-2">
            <button
              className="px-3 py-1 rounded border text-sm"
              onClick={() => downloadCsv('national_escalation_group_summary.csv', groupedSummary)}
            >
              Export Grouped CSV
            </button>
            <button
              className="px-3 py-1 rounded border text-sm"
              onClick={() => downloadCsv('national_escalation_details.csv', filteredEscalations)}
            >
              Export Details CSV
            </button>
          </div>
        )}

        {groupedSummary.length === 0 && (
          <EmptyState message="No escalation summary rows for current filters." />
        )}

        {groupedSummary.length > 0 && (
          <div className="overflow-x-auto border rounded mb-4">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">State</th>
                  <th className="p-2">District</th>
                  <th className="p-2">Resource</th>
                  <th className="p-2">Rows</th>
                  <th className="p-2">Escalated Qty (sum)</th>
                </tr>
              </thead>
              <tbody>
                {groupedSummary.map((row, idx) => (
                  <tr key={`${row.state_code}_${row.district_code}_${row.resource_id}_${idx}`} className="border-t">
                    <td className="p-2">{row.state_code}</td>
                    <td className="p-2">{row.district_code}</td>
                    <td className="p-2">{resourceNameMap[row.resource_id] || row.resource_id}</td>
                    <td className="p-2">{row.row_count}</td>
                    <td className="p-2">{row.quantity.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Escalated Demand">
        {filteredEscalations.length === 0 && (
          <EmptyState message="No unmet demand requiring national escalation." />
        )}

        {filteredEscalations.map((r, idx) => {
          const available = nationalStock[r.resource_id] ?? 0

          return (
            <div
              key={r.id || idx}
              className="border rounded-lg p-4 mb-4"
            >
              <div className="font-semibold text-lg">
                {resourceNameMap[r.resource_id] || r.resource_id} — Time {r.time}
              </div>

              <div className="text-sm">
                District: <b>{r.district_code}</b>
              </div>

              <div className="text-sm">
                State: <b>{r.state_code}</b>
              </div>

              <div className="text-sm text-red-600">
                Escalated Quantity: {r.quantity}
              </div>

              <div className="text-xs text-slate-600">
                Run ID: {r.run_id ?? '—'}
              </div>

              <div className="text-sm text-gray-600">
                National Available: {available}
              </div>

              <div className="text-xs text-slate-600">
                Priority {r.priority ?? 1} | Urgency {r.urgency ?? 1} | Confidence {r.confidence ?? 1} | Source {r.source ?? 'human'}
              </div>

              <div className="flex gap-2 mt-3">
                <button
                  className="px-3 py-1 bg-green-700 text-white rounded"
                  disabled={busyId === r.id}
                  onClick={() => resolve(r.id, 'allocated')}
                >
                  Allocate
                </button>

                <button
                  className="px-3 py-1 bg-amber-700 text-white rounded"
                  disabled={busyId === r.id}
                  onClick={() => resolve(r.id, 'partial')}
                >
                  Partial
                </button>

                <button
                  className="px-3 py-1 bg-red-700 text-white rounded"
                  disabled={busyId === r.id}
                  onClick={() => resolve(r.id, 'unmet')}
                >
                  Mark Unmet
                </button>
              </div>
            </div>
          )
        })}
      </Section>
    </div>
  )
}
