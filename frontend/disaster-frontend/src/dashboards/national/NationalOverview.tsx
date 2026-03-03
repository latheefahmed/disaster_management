import { useEffect, useMemo, useState } from 'react'
import Section from '../shared/Section'
import StatCard from '../shared/StatCard'
import EmptyState from '../shared/EmptyState'
import OpsDataTable from '../shared/OpsDataTable'
import ResourceStockTabs from '../../components/ResourceStockTabs'
import ResourceRefillPanel from '../../components/ResourceRefillPanel'

import { BACKEND_PATHS } from '../../data/backendPaths'
import { useAuth } from '../../auth/AuthContext'
import { downloadCsv } from '../../utils/csv'
import { useLiveAllocationStream } from '../../state/useLiveAllocationStream'

type NationalSummaryRow = {
  solver_run_id?: number
  state_code: string
  district_code: string
  resource_id: string
  time: number
  allocated_quantity: number
  unmet_quantity: number
  met: boolean
  final_demand_quantity?: number
}

type EscalationRow = {
  id: number
  state_code: string
  district_code: string
  resource_id: string
  quantity: number
  status: string
}

type NationalPoolTxRow = {
  id: number
  state_code: string | null
  district_code: string | null
  resource_id: string
  time: number
  quantity_delta: number
  reason: string
  actor_role: string
  actor_id: string
  created_at: string
}

type NationalStockRow = {
  resource_id: string
  district_stock: number
  state_stock: number
  national_stock: number
}

type MainTab = 'state-summaries' | 'national-stock' | 'refill' | 'inter-state' | 'agent' | 'history'

type ResourceMeta = {
  resource_id: string
  resource_name: string
  category?: string
  class?: string
}

type KpiPayload = {
  solver_run_id: number | null
  allocated: number
  unmet: number
  final_demand: number
  coverage: number
}

type RunHistoryRow = {
  run_id: number | string
  status?: string
  mode: string
  started_at?: string
  total_demand: number
  total_allocated: number
  total_unmet: number
}

export default function NationalOverview() {
  const { token } = useAuth()
  const streamEnabled = Boolean(token)

  const [summaryRows, setSummaryRows] = useState<NationalSummaryRow[]>([])
  const [solverRunId, setSolverRunId] = useState<number | null>(null)
  const [escalations, setEscalations] = useState<EscalationRow[]>([])
  const [poolTxRows, setPoolTxRows] = useState<NationalPoolTxRow[]>([])
  const [stockRows, setStockRows] = useState<NationalStockRow[]>([])
  const [resources, setResources] = useState<ResourceMeta[]>([])
  const [kpi, setKpi] = useState<KpiPayload>({ solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 })
  const [runHistoryRows, setRunHistoryRows] = useState<RunHistoryRow[]>([])
  const [loadError, setLoadError] = useState('')
  const [lastUpdatedAt, setLastUpdatedAt] = useState('')
  const [mainTab, setMainTab] = useState<MainTab>('state-summaries')
  const [overviewBoot, setOverviewBoot] = useState(true)

  const [stateFilter, setStateFilter] = useState('')

  async function loadData() {
    if (!token) return

    try {
      const shouldLoadSummary = !overviewBoot && mainTab === 'state-summaries'
      const shouldLoadEscalations = !overviewBoot && mainTab === 'inter-state'
      const shouldLoadPoolTx = !overviewBoot && mainTab === 'inter-state'
      const shouldLoadStock = !overviewBoot && (mainTab === 'national-stock' || mainTab === 'refill')
      const shouldLoadResources = !overviewBoot && (mainTab === 'national-stock' || mainTab === 'refill')
      const shouldLoadHistory = !overviewBoot && mainTab === 'history'
      const settled = await Promise.allSettled([
        shouldLoadSummary
          ? fetch(`${BACKEND_PATHS.nationalAllocationSummary}?page=1&page_size=200`, { headers: { Authorization: `Bearer ${token}` } })
          : Promise.resolve(new Response(JSON.stringify({ solver_run_id: solverRunId, rows: summaryRows }), { status: 200 })),
        shouldLoadEscalations
          ? fetch(BACKEND_PATHS.nationalEscalations, { headers: { Authorization: `Bearer ${token}` } })
          : Promise.resolve(new Response('[]', { status: 200 })),
        shouldLoadPoolTx
          ? fetch(BACKEND_PATHS.nationalPoolTransactions, { headers: { Authorization: `Bearer ${token}` } })
          : Promise.resolve(new Response('[]', { status: 200 })),
        shouldLoadStock
          ? fetch(BACKEND_PATHS.nationalStock, { headers: { Authorization: `Bearer ${token}` } })
          : Promise.resolve(new Response('[]', { status: 200 })),
        fetch(BACKEND_PATHS.nationalKpis, { headers: { Authorization: `Bearer ${token}` } }),
        shouldLoadResources
          ? fetch(BACKEND_PATHS.resourceCatalog, { headers: { Authorization: `Bearer ${token}` } })
          : Promise.resolve(new Response('[]', { status: 200 })),
        shouldLoadHistory
          ? fetch(`${BACKEND_PATHS.nationalRunHistory}?page=1&page_size=200`, { headers: { Authorization: `Bearer ${token}` } })
          : Promise.resolve(new Response('[]', { status: 200 })),
      ])

      const summaryRes = settled[0].status === 'fulfilled' ? settled[0].value : null
      const escalationsRes = settled[1].status === 'fulfilled' ? settled[1].value : null
      const poolRes = settled[2].status === 'fulfilled' ? settled[2].value : null
      const stockRes = settled[3].status === 'fulfilled' ? settled[3].value : null
      const kpiRes = settled[4].status === 'fulfilled' ? settled[4].value : null
      const resourceRes = settled[5].status === 'fulfilled' ? settled[5].value : null
      const historyRes = settled[6].status === 'fulfilled' ? settled[6].value : null

      const summaryPayload = summaryRes && summaryRes.ok ? await summaryRes.json() : { solver_run_id: null, rows: [] }
      const escalationsPayload = escalationsRes && escalationsRes.ok ? await escalationsRes.json() : []
      const poolPayload = poolRes && poolRes.ok ? await poolRes.json() : []
      const stockPayload = stockRes && stockRes.ok ? await stockRes.json() : []
      const kpiPayload = kpiRes && kpiRes.ok ? await kpiRes.json() : { solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 }
      const resourcePayload = resourceRes && resourceRes.ok ? await resourceRes.json() : []
      const historyPayload = historyRes && historyRes.ok ? await historyRes.json() : []

      if (shouldLoadSummary) {
        setSummaryRows(Array.isArray(summaryPayload?.rows) ? summaryPayload.rows : [])
        setSolverRunId(summaryPayload?.solver_run_id ?? null)
      }
      if (shouldLoadEscalations) setEscalations(Array.isArray(escalationsPayload) ? escalationsPayload : [])
      if (shouldLoadPoolTx) setPoolTxRows(Array.isArray(poolPayload) ? poolPayload : [])
      if (shouldLoadStock) setStockRows(Array.isArray(stockPayload) ? stockPayload : [])
      if (shouldLoadResources) setResources(Array.isArray(resourcePayload) ? resourcePayload : [])
      setKpi(kpiPayload || { solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 })
      if (shouldLoadHistory) setRunHistoryRows(Array.isArray(historyPayload) ? historyPayload : [])
      setLoadError('')
      setLastUpdatedAt(new Date().toLocaleTimeString())
    } catch (error) {
      if (mainTab === 'state-summaries') {
        setSummaryRows([])
        setSolverRunId(null)
      }
      setLoadError(error instanceof Error ? error.message : 'Failed to load national dashboard data')
    }
  }

  useEffect(() => {
    loadData()
    if (streamEnabled) return
    const id = setInterval(loadData, 5000)
    return () => clearInterval(id)
  }, [token, mainTab, streamEnabled])

  useEffect(() => {
    const onFocus = () => {
      loadData()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [token, mainTab])

  useLiveAllocationStream({
    enabled: streamEnabled,
    streamUrl: token ? `${BACKEND_PATHS.nationalAllocationsStream}?token=${encodeURIComponent(token)}` : '',
    onDelta: () => {
      loadData()
    },
  })

  const nationalDemand = Number(kpi.final_demand || 0)
  const nationalAllocated = Number(kpi.allocated || 0)
  const totalUnmet = Number(kpi.unmet || 0)

  const nationalStock = useMemo(
    () => stockRows.reduce((sum, row) => sum + Number(row.national_stock || 0), 0),
    [stockRows],
  )

  const interStateTransfers = useMemo(
    () => poolTxRows.filter((row) => row.reason?.toLowerCase().includes('transfer') || row.reason?.toLowerCase().includes('mutual')).length,
    [poolTxRows],
  )

  const topStatesByUnmet = useMemo(() => {
    const grouped = new Map<string, number>()
    for (const row of summaryRows) {
      grouped.set(String(row.state_code), (grouped.get(String(row.state_code)) || 0) + Number(row.unmet_quantity || 0))
    }
    return Array.from(grouped.entries())
      .map(([state_code, unmet_quantity]) => ({ state_code, unmet_quantity }))
      .sort((a, b) => b.unmet_quantity - a.unmet_quantity)
      .slice(0, 5)
  }, [summaryRows])

  const filteredStateSummaries = useMemo(() => {
    const needle = stateFilter.trim().toLowerCase()
    return summaryRows
      .filter((row) => !needle || String(row.state_code).toLowerCase().includes(needle))
      .sort((a, b) => {
        const sc = String(a.state_code).localeCompare(String(b.state_code))
        if (sc !== 0) return sc
        const dc = String(a.district_code).localeCompare(String(b.district_code))
        if (dc !== 0) return dc
        return Number(a.time || 0) - Number(b.time || 0)
      })
  }, [summaryRows, stateFilter])

  const tabs: Array<{ key: MainTab; label: string }> = [
    { key: 'state-summaries', label: 'State Summaries' },
    { key: 'national-stock', label: 'National Stock' },
    { key: 'refill', label: 'Refill Resources' },
    { key: 'inter-state', label: 'Inter-State Transfers' },
    { key: 'agent', label: 'Agent Recommendations' },
    { key: 'history', label: 'Run History' },
  ]

  return (
    <div className="space-y-4">
      <Section title="National Overview">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
          <StatCard label="National Demand" value={nationalDemand.toFixed(2)} />
          <StatCard label="National Stock" value={nationalStock.toFixed(2)} />
          <StatCard label="Total Unmet" value={totalUnmet.toFixed(2)} />
          <StatCard label="Inter-State Transfers" value={interStateTransfers.toString()} />
        </div>

        <div className="mb-2 text-xs text-slate-600">Run: {solverRunId ?? '—'} | Last refresh: {lastUpdatedAt || '—'}</div>

        {loadError && <div className="mb-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">{loadError}</div>}

        <div className="mb-3 text-xs border rounded px-3 py-2 bg-white">
          <span className="font-semibold">Top 5 states by unmet: </span>
          {topStatesByUnmet.length === 0
            ? 'None'
            : topStatesByUnmet.map((row) => `${row.state_code} (${row.unmet_quantity.toFixed(2)})`).join(', ')}
        </div>

        <div className="flex flex-wrap gap-2 border-b pb-2">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={`px-3 py-1 rounded border text-sm ${mainTab === tab.key ? 'bg-slate-800 text-white border-slate-800' : 'bg-white'}`}
              onClick={() => {
                setOverviewBoot(false)
                setMainTab(tab.key)
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </Section>

      {mainTab === 'state-summaries' && (
        <Section title="Nationwide Allocation Status">
          <div className="mb-2 flex flex-wrap gap-2">
            <button className="px-3 py-1 rounded border text-sm" onClick={() => downloadCsv('national_allocation_summary.csv', filteredStateSummaries)}>
              Export CSV
            </button>
            <input
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="border rounded px-2 py-1 text-sm"
              placeholder="Filter by state"
            />
          </div>

          <OpsDataTable
            rows={filteredStateSummaries}
            columns={[
              { key: 'solver_run_id', label: 'Run ID' },
              { key: 'state_code', label: 'State' },
              { key: 'district_code', label: 'District' },
              { key: 'resource_id', label: 'Resource' },
              { key: 'time', label: 'Time' },
              { key: 'allocated_quantity', label: 'Allocated' },
              { key: 'unmet_quantity', label: 'Unmet' },
              { key: 'met', label: 'Met' },
            ]}
            rowKey={(row, idx) => `${row.state_code}_${row.district_code}_${row.resource_id}_${row.time}_${idx}`}
            emptyMessage="No national summary rows."
          />
        </Section>
      )}

      {mainTab === 'national-stock' && (
        <Section title="National Stock">
          {stockRows.length === 0 ? (
            <EmptyState message="No national stock rows available." />
          ) : (
            <ResourceStockTabs rows={stockRows} resources={resources} defaultScope="national" />
          )}
        </Section>
      )}

      {mainTab === 'refill' && (
        <Section title="Refill Resources">
          <ResourceRefillPanel
            scope="national"
            resources={resources}
            endpoint={BACKEND_PATHS.nationalStockRefill}
            onRefilled={loadData}
          />
        </Section>
      )}

      {mainTab === 'inter-state' && (
        <Section title="Inter-State Allocations">
          <OpsDataTable
            rows={poolTxRows}
            columns={[
              { key: 'created_at', label: 'When' },
              { key: 'state_code', label: 'State' },
              { key: 'district_code', label: 'District' },
              { key: 'resource_id', label: 'Resource' },
              { key: 'time', label: 'Time' },
              { key: 'quantity_delta', label: 'Delta' },
              { key: 'reason', label: 'Reason' },
            ]}
            rowKey={(row) => String(row.id)}
            emptyMessage="No inter-state allocation transactions."
          />
        </Section>
      )}

      {mainTab === 'agent' && (
        <Section title="Agent Recommendations">
          <OpsDataTable
            rows={escalations.map((row) => ({
              ...row,
              finding_type: 'escalated_unmet',
              recommendation: `Prioritize cross-state transfer for ${row.resource_id}`,
              status: row.status,
            }))}
            columns={[
              { key: 'finding_type', label: 'Finding Type' },
              { key: 'resource_id', label: 'Resource' },
              { key: 'state_code', label: 'State' },
              { key: 'recommendation', label: 'Recommendation' },
              { key: 'status', label: 'Status' },
            ]}
            rowKey={(row) => String(row.id)}
            emptyMessage="No agent recommendation rows in current national scope."
          />
        </Section>
      )}

      {mainTab === 'history' && (
        <Section title="Run History">
          <OpsDataTable
            rows={runHistoryRows.map((row) => ({
              run_id: row.run_id,
              time: row.started_at ? new Date(row.started_at).toLocaleString() : '—',
              mode: row.mode || 'live',
              total_demand: Number(row.total_demand || 0).toFixed(2),
              total_allocated: Number(row.total_allocated || 0).toFixed(2),
              total_unmet: Number(row.total_unmet || 0).toFixed(2),
            }))}
            columns={[
              { key: 'run_id', label: 'Run ID' },
              { key: 'time', label: 'Time' },
              { key: 'mode', label: 'Mode' },
              { key: 'total_demand', label: 'Total Demand' },
              { key: 'total_allocated', label: 'Total Allocated' },
              { key: 'total_unmet', label: 'Total Unmet' },
            ]}
            rowKey={(row) => String(row.run_id)}
            pageSize={5}
            emptyMessage="No national run history rows."
          />
        </Section>
      )}
    </div>
  )
}
