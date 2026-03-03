import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import Section from '../shared/Section'
import EmptyState from '../shared/EmptyState'
import StatCard from '../shared/StatCard'

import { BACKEND_PATHS } from '../../data/backendPaths'
import { apiFetch } from '../../data/apiClient'
import { downloadCsv } from '../../utils/csv'

type RunSummary = {
  run_id: number
  scenario_id: number
  status: string
  started_at?: string
  totals: {
    allocated_quantity: number
    unmet_quantity: number
    districts_covered: number
    districts_met: number
    districts_unmet: number
    allocation_rows: number
    unmet_rows: number
  }
  district_breakdown: Array<{
    district_code: string
    allocated_quantity: number
    unmet_quantity: number
    met: boolean
  }>
  allocation_details: Array<{
    district_code: string
    state_code: string
    resource_id: string
    time: number
    allocated_quantity: number
  }>
  unmet_details: Array<{
    district_code: string
    state_code: string
    resource_id: string
    time: number
    unmet_quantity: number
  }>
}

export default function AdminScenarioRunDetails() {
  const { scenarioId, runId } = useParams()

  const [summary, setSummary] = useState<RunSummary | null>(null)
    const totals = {
      allocated_quantity: Number(summary?.totals?.allocated_quantity || 0),
      unmet_quantity: Number(summary?.totals?.unmet_quantity || 0),
      districts_covered: Number(summary?.totals?.districts_covered || 0),
      districts_met: Number(summary?.totals?.districts_met || 0),
      districts_unmet: Number(summary?.totals?.districts_unmet || 0),
      allocation_rows: Number(summary?.totals?.allocation_rows || 0),
      unmet_rows: Number(summary?.totals?.unmet_rows || 0),
    }

  const [resourceFilter, setResourceFilter] = useState('')
  const [districtFilter, setDistrictFilter] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      if (!scenarioId || !runId) return
      setError('')
      try {
        const payload = await apiFetch<RunSummary>(
          BACKEND_PATHS.adminScenarioRunSummary(Number(scenarioId), Number(runId))
        )
        setSummary(payload)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load run summary')
        setSummary(null)
      }
    }

    load()
  }, [scenarioId, runId])

  const filteredAlloc = useMemo(() => {
    if (!summary) return []
    const resource = resourceFilter.trim().toLowerCase()
    const district = districtFilter.trim().toLowerCase()
    const rows = Array.isArray(summary.allocation_details) ? summary.allocation_details : []
    return rows.filter(r => {
      const byResource = !resource || String(r.resource_id).toLowerCase().includes(resource)
      const byDistrict = !district || String(r.district_code).toLowerCase().includes(district)
      return byResource && byDistrict
    })
  }, [summary, resourceFilter, districtFilter])

  const filteredUnmet = useMemo(() => {
    if (!summary) return []
    const resource = resourceFilter.trim().toLowerCase()
    const district = districtFilter.trim().toLowerCase()
    const rows = Array.isArray(summary.unmet_details) ? summary.unmet_details : []
    return rows.filter(r => {
      const byResource = !resource || String(r.resource_id).toLowerCase().includes(resource)
      const byDistrict = !district || String(r.district_code).toLowerCase().includes(district)
      return byResource && byDistrict
    })
  }, [summary, resourceFilter, districtFilter])

  return (
    <div>
      <Section title={`Scenario ${scenarioId} Run ${runId} Details`}>
        <div className="mb-3 text-sm">
          <Link to="/admin" className="text-blue-700 underline">Back to Admin Scenario Studio</Link>
        </div>

        {error && (
          <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">
            {error}
          </div>
        )}

        {!summary && !error && <EmptyState message="Loading run summary..." />}

        {summary && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <StatCard label="Allocated Qty" value={totals.allocated_quantity.toFixed(2)} />
              <StatCard label="Unmet Qty" value={totals.unmet_quantity.toFixed(2)} />
              <StatCard label="Districts Covered" value={totals.districts_covered.toString()} />
              <StatCard label="Districts Met" value={totals.districts_met.toString()} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3 text-sm">
              <input
                value={resourceFilter}
                onChange={e => setResourceFilter(e.target.value)}
                placeholder="Filter resource"
                className="border rounded px-2 py-1"
              />
              <input
                value={districtFilter}
                onChange={e => setDistrictFilter(e.target.value)}
                placeholder="Filter district"
                className="border rounded px-2 py-1"
              />
              <button
                onClick={() => {
                  setResourceFilter('')
                  setDistrictFilter('')
                }}
                className="px-3 py-1 rounded border"
              >
                Clear Filters
              </button>
            </div>

            <div className="mb-3 flex gap-2 text-sm">
              <button className="px-3 py-1 rounded border" onClick={() => downloadCsv(`scenario_${scenarioId}_run_${runId}_district_breakdown.csv`, summary.district_breakdown)}>
                Export District CSV
              </button>
              <button className="px-3 py-1 rounded border" onClick={() => downloadCsv(`scenario_${scenarioId}_run_${runId}_allocation_details.csv`, filteredAlloc)}>
                Export Allocation CSV
              </button>
              <button className="px-3 py-1 rounded border" onClick={() => downloadCsv(`scenario_${scenarioId}_run_${runId}_unmet_details.csv`, filteredUnmet)}>
                Export Unmet CSV
              </button>
            </div>
          </>
        )}
      </Section>

      <Section title="District Satisfaction">
        {!summary && <EmptyState message="No district summary found." />}
        {summary && (!Array.isArray(summary.district_breakdown) || summary.district_breakdown.length === 0) && <EmptyState message="No district breakdown found." />}
        {summary && Array.isArray(summary.district_breakdown) && summary.district_breakdown.length > 0 && (
          <div className="overflow-x-auto border rounded">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">District</th>
                  <th className="p-2">Allocated</th>
                  <th className="p-2">Unmet</th>
                  <th className="p-2">Met</th>
                </tr>
              </thead>
              <tbody>
                {summary.district_breakdown.map((row, idx) => (
                  <tr key={`${row.district_code}_${idx}`} className="border-t">
                    <td className="p-2">{row.district_code}</td>
                    <td className="p-2">{Number(row.allocated_quantity || 0).toFixed(2)}</td>
                    <td className="p-2">{Number(row.unmet_quantity || 0).toFixed(2)}</td>
                    <td className="p-2">{row.met ? 'Yes' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Allocation Details">
        {!summary && <EmptyState message="No allocation details available." />}
        {summary && filteredAlloc.length === 0 && <EmptyState message="No allocation rows for current filters." />}
        {summary && filteredAlloc.length > 0 && (
          <div className="overflow-x-auto border rounded">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">State</th>
                  <th className="p-2">District</th>
                  <th className="p-2">Resource</th>
                  <th className="p-2">Time</th>
                  <th className="p-2">Allocated</th>
                </tr>
              </thead>
              <tbody>
                {filteredAlloc.slice(0, 500).map((row, idx) => (
                  <tr key={`${row.state_code}_${row.district_code}_${row.resource_id}_${row.time}_${idx}`} className="border-t">
                    <td className="p-2">{row.state_code}</td>
                    <td className="p-2">{row.district_code}</td>
                    <td className="p-2">{row.resource_id}</td>
                    <td className="p-2">{row.time}</td>
                    <td className="p-2">{Number(row.allocated_quantity || 0).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Unmet Details">
        {!summary && <EmptyState message="No unmet details available." />}
        {summary && filteredUnmet.length === 0 && <EmptyState message="No unmet rows for current filters." />}
        {summary && filteredUnmet.length > 0 && (
          <div className="overflow-x-auto border rounded">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">State</th>
                  <th className="p-2">District</th>
                  <th className="p-2">Resource</th>
                  <th className="p-2">Time</th>
                  <th className="p-2">Unmet</th>
                </tr>
              </thead>
              <tbody>
                {filteredUnmet.slice(0, 500).map((row, idx) => (
                  <tr key={`${row.state_code}_${row.district_code}_${row.resource_id}_${row.time}_${idx}`} className="border-t">
                    <td className="p-2">{row.state_code}</td>
                    <td className="p-2">{row.district_code}</td>
                    <td className="p-2">{row.resource_id}</td>
                    <td className="p-2">{row.time}</td>
                    <td className="p-2">{Number(row.unmet_quantity || 0).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  )
}
