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

type StatePoolRow = {
  resource_id: string
  time: number
  quantity: number
}

type StateAllocationSummaryRow = {
  solver_run_id?: number
  district_code: string
  resource_id: string
  time: number
  allocated_quantity: number
  unmet_quantity: number
  met: boolean
  final_demand_quantity?: number
}

type StatePoolTxRow = {
  id: number
  state_code: string
  district_code: string | null
  resource_id: string
  time: number
  quantity_delta: number
  reason: string
  actor_role: string
  actor_id: string
  created_at: string
}

type MutualAidMarketRow = {
  id: number
  requesting_state: string
  requesting_district: string
  resource_id: string
  time: number
  quantity_requested: number
  accepted_quantity: number
  remaining_quantity: number
  status: string
}

type AgentRecommendationRow = {
  id: number
  entity_type?: string | null
  entity_id?: string | null
  finding_type?: string | null
  severity?: string | null
  evidence_json?: any
  recommendation_type?: string | null
  payload_json?: any
  message?: string | null
  status: string
}

type MainTab = 'district-requests' | 'mutual-aid' | 'state-stock' | 'refill' | 'agent' | 'history'

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

type StockRow = {
  resource_id: string
  district_stock: number
  state_stock: number
  national_stock: number
}

export default function StateOverview() {
  const { stateCode, token } = useAuth()
  const streamEnabled = Boolean(token && stateCode)

  const [allocationSummary, setAllocationSummary] = useState<StateAllocationSummaryRow[]>([])
  const [solverRunId, setSolverRunId] = useState<number | null>(null)
  const [poolRows, setPoolRows] = useState<StatePoolRow[]>([])
  const [poolTxRows, setPoolTxRows] = useState<StatePoolTxRow[]>([])
  const [mutualAidMarket, setMutualAidMarket] = useState<MutualAidMarketRow[]>([])
  const [agentRows, setAgentRows] = useState<AgentRecommendationRow[]>([])
  const [resources, setResources] = useState<ResourceMeta[]>([])
  const [kpi, setKpi] = useState<KpiPayload>({ solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 })
  const [stockRows, setStockRows] = useState<StockRow[]>([])
  const [runHistoryRows, setRunHistoryRows] = useState<RunHistoryRow[]>([])
  const [loadError, setLoadError] = useState('')

  const [districtFilter, setDistrictFilter] = useState('')
  const [mainTab, setMainTab] = useState<MainTab>('district-requests')
  const [overviewBoot, setOverviewBoot] = useState(true)
  const [lastUpdatedAt, setLastUpdatedAt] = useState('')
  const [offerQty, setOfferQty] = useState<Record<number, number>>({})
  const [offerBusyId, setOfferBusyId] = useState<number | null>(null)
  const [showDetailedAllocations, setShowDetailedAllocations] = useState(false)

  async function authFetch<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, {
      ...(init || {}),
      headers: {
        ...(init?.headers || {}),
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    })

    if (!res.ok) throw new Error(`Request failed: ${res.status}`)
    return await res.json()
  }

  async function loadData() {
    if (!token || !stateCode) return
    try {
      const shouldLoadSummary = !overviewBoot && mainTab === 'district-requests'
      const shouldLoadPool = !overviewBoot && (mainTab === 'mutual-aid' || mainTab === 'state-stock')
      const shouldLoadPoolTx = !overviewBoot && (mainTab === 'mutual-aid')
      const shouldLoadMarket = !overviewBoot && (mainTab === 'mutual-aid')
      const shouldLoadAgent = !overviewBoot && mainTab === 'agent'
      const shouldLoadStock = !overviewBoot && (mainTab === 'state-stock' || mainTab === 'refill')
      const shouldLoadResources = !overviewBoot && (mainTab === 'state-stock' || mainTab === 'refill')
      const shouldLoadHistory = !overviewBoot && mainTab === 'history'
      const settled = await Promise.allSettled([
        shouldLoadSummary
          ? authFetch<{ solver_run_id: number | null; rows: StateAllocationSummaryRow[] }>(`${BACKEND_PATHS.stateAllocationSummary}?page=1&page_size=200`)
          : Promise.resolve<{ solver_run_id: number | null; rows: StateAllocationSummaryRow[] }>({ solver_run_id: solverRunId, rows: allocationSummary }),
        shouldLoadPool ? authFetch<StatePoolRow[]>(BACKEND_PATHS.statePool) : Promise.resolve([] as StatePoolRow[]),
        shouldLoadPoolTx ? authFetch<StatePoolTxRow[]>(BACKEND_PATHS.statePoolTransactions) : Promise.resolve([] as StatePoolTxRow[]),
        shouldLoadMarket ? authFetch<MutualAidMarketRow[]>(BACKEND_PATHS.stateMutualAidMarket) : Promise.resolve([] as MutualAidMarketRow[]),
        shouldLoadAgent ? authFetch<AgentRecommendationRow[]>(BACKEND_PATHS.stateAgentRecommendations) : Promise.resolve([] as AgentRecommendationRow[]),
        authFetch<KpiPayload>(BACKEND_PATHS.stateKpis),
        shouldLoadStock ? authFetch<StockRow[]>(BACKEND_PATHS.stateStock) : Promise.resolve([] as StockRow[]),
        shouldLoadResources ? authFetch<ResourceMeta[]>(BACKEND_PATHS.resourceCatalog) : Promise.resolve([] as ResourceMeta[]),
        shouldLoadHistory ? authFetch<RunHistoryRow[]>(`${BACKEND_PATHS.stateRunHistory}?page=1&page_size=200`) : Promise.resolve([] as RunHistoryRow[]),
      ])

      const summaryRes = settled[0].status === 'fulfilled' ? settled[0].value : { solver_run_id: null, rows: [] }
      const poolRes = settled[1].status === 'fulfilled' ? settled[1].value : []
      const txRes = settled[2].status === 'fulfilled' ? settled[2].value : []
      const marketRes = settled[3].status === 'fulfilled' ? settled[3].value : []
      const agentRes = settled[4].status === 'fulfilled' ? settled[4].value : []
      const kpiRes = settled[5].status === 'fulfilled' ? settled[5].value : { solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 }
      const stockRes = settled[6].status === 'fulfilled' ? settled[6].value : []
      const resourceRes = settled[7].status === 'fulfilled' ? settled[7].value : []
      const historyRes = settled[8].status === 'fulfilled' ? settled[8].value : []

      if (shouldLoadSummary) {
        setAllocationSummary(Array.isArray(summaryRes?.rows) ? summaryRes.rows : [])
        setSolverRunId(summaryRes?.solver_run_id ?? null)
      }
      if (shouldLoadPool) setPoolRows(Array.isArray(poolRes) ? poolRes : [])
      if (shouldLoadPoolTx) setPoolTxRows(Array.isArray(txRes) ? txRes : [])
      if (shouldLoadMarket) setMutualAidMarket(Array.isArray(marketRes) ? marketRes : [])
      if (shouldLoadAgent) setAgentRows(Array.isArray(agentRes) ? agentRes : [])
      setKpi(kpiRes || { solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 })
      if (shouldLoadStock) setStockRows(Array.isArray(stockRes) ? stockRes : [])
      if (shouldLoadResources) setResources(Array.isArray(resourceRes) ? resourceRes : [])
      if (shouldLoadHistory) setRunHistoryRows(Array.isArray(historyRes) ? historyRes : [])
      setLoadError('')
      setLastUpdatedAt(new Date().toLocaleTimeString())
    } catch (error) {
      if (mainTab === 'district-requests') {
        setAllocationSummary([])
      }
      setLoadError(error instanceof Error ? error.message : 'Failed to load state dashboard data')
    }
  }

  useEffect(() => {
    loadData()
    if (streamEnabled) return
    const id = setInterval(loadData, 4000)
    return () => clearInterval(id)
  }, [token, stateCode, mainTab, streamEnabled])

  useEffect(() => {
    const onFocus = () => {
      loadData()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [token, stateCode, mainTab])

  useLiveAllocationStream({
    enabled: streamEnabled,
    streamUrl: token ? `${BACKEND_PATHS.stateAllocationsStream}?token=${encodeURIComponent(token)}` : '',
    onDelta: () => {
      loadData()
    },
  })

  const totalDemand = Number(kpi.final_demand || 0)
  const totalAllocated = Number(kpi.allocated || 0)
  const totalUnmet = Number(kpi.unmet || 0)

  const mutualAidSent = useMemo(
    () => poolTxRows.filter((row) => Number(row.quantity_delta || 0) < 0).reduce((sum, row) => sum + Math.abs(Number(row.quantity_delta || 0)), 0),
    [poolTxRows],
  )

  const mutualAidReceived = useMemo(
    () => poolTxRows.filter((row) => Number(row.quantity_delta || 0) > 0).reduce((sum, row) => sum + Number(row.quantity_delta || 0), 0),
    [poolTxRows],
  )

  const topDistrictsByUnmet = useMemo(() => {
    const grouped = new Map<string, number>()
    for (const row of allocationSummary) {
      grouped.set(String(row.district_code), (grouped.get(String(row.district_code)) || 0) + Number(row.unmet_quantity || 0))
    }
    return Array.from(grouped.entries())
      .map(([district_code, unmet_quantity]) => ({ district_code, unmet_quantity }))
      .sort((a, b) => b.unmet_quantity - a.unmet_quantity)
      .slice(0, 5)
  }, [allocationSummary])

  const filteredDistrictRows = useMemo(() => {
    const needle = districtFilter.trim().toLowerCase()
    return allocationSummary
      .filter((row) => !needle || String(row.district_code).toLowerCase().includes(needle))
      .map((row) => ({
        ...row,
        district_request: Number(row.final_demand_quantity || row.allocated_quantity + row.unmet_quantity || 0),
      }))
  }, [allocationSummary, districtFilter])

  const tabs: Array<{ key: MainTab; label: string }> = [
    { key: 'district-requests', label: 'District Requests' },
    { key: 'mutual-aid', label: 'Mutual Aid Outgoing / Incoming' },
    { key: 'state-stock', label: 'State Stock' },
    { key: 'refill', label: 'Refill Resources' },
    { key: 'agent', label: 'Agent Recommendations' },
    { key: 'history', label: 'Run History' },
  ]

  async function submitMutualAidOffer(row: MutualAidMarketRow) {
    const qty = Number(offerQty[row.id] ?? Math.max(1, Math.floor(Number(row.remaining_quantity || 0))))
    if (!qty || qty <= 0) return
    setOfferBusyId(row.id)
    try {
      await authFetch<{ status: string; offer_id: number }>(BACKEND_PATHS.stateMutualAidOffers, {
        method: 'POST',
        body: JSON.stringify({ request_id: row.id, quantity_offered: qty }),
      })
      await loadData()
    } finally {
      setOfferBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <Section title={`State Overview (State ${stateCode})`}>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-3">
          <StatCard label="Total District Demand" value={totalDemand.toFixed(2)} />
          <StatCard label="Total Allocated to Districts" value={totalAllocated.toFixed(2)} />
          <StatCard label="Total Unmet" value={totalUnmet.toFixed(2)} />
          <StatCard label="Mutual Aid Sent" value={mutualAidSent.toFixed(2)} />
          <StatCard label="Mutual Aid Received" value={mutualAidReceived.toFixed(2)} />
        </div>

        <div className="mb-2 text-xs text-slate-600">Run: {solverRunId ?? '—'} | Last refresh: {lastUpdatedAt || '—'}</div>

        {loadError && <div className="mb-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">{loadError}</div>}

        <div className="mb-3 text-xs border rounded px-3 py-2 bg-white">
          <span className="font-semibold">Top 5 districts by unmet: </span>
          {topDistrictsByUnmet.length === 0
            ? 'None'
            : topDistrictsByUnmet.map((row) => `${row.district_code} (${row.unmet_quantity.toFixed(2)})`).join(', ')}
        </div>

        <div className="mb-3 border rounded px-3 py-2 bg-white">
          <h3 className="text-sm font-semibold mb-2">Mutual Aid Market</h3>
          {mutualAidMarket.length === 0 ? (
            <div className="text-xs text-slate-500">No open mutual aid requests in market.</div>
          ) : (
            <button
              className="px-3 py-1 rounded bg-indigo-600 text-white text-sm"
              disabled={offerBusyId === mutualAidMarket[0].id}
              onClick={() => submitMutualAidOffer(mutualAidMarket[0])}
            >
              {offerBusyId === mutualAidMarket[0].id ? 'Offering...' : 'Offer Mutual Aid'}
            </button>
          )}
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

      {mainTab === 'district-requests' && (
        <Section title="District Allocation Summary">
          <div className="mb-2 flex flex-wrap gap-2">
            <button className="px-3 py-1 rounded border text-sm" onClick={() => downloadCsv(`state_${stateCode}_allocation_by_resource.csv`, filteredDistrictRows)}>
              Export Aggregated CSV
            </button>
            <button className="px-3 py-1 rounded border text-sm" onClick={() => downloadCsv(`state_${stateCode}_allocation_summary.csv`, filteredDistrictRows)}>
              Export Details CSV
            </button>
            <input
              value={districtFilter}
              onChange={(e) => setDistrictFilter(e.target.value)}
              className="border rounded px-2 py-1 text-sm"
              placeholder="Filter by district"
            />
            <button
              className="px-3 py-1 rounded border text-sm"
              onClick={() => setShowDetailedAllocations((v) => !v)}
            >
              {showDetailedAllocations ? 'Hide District-Level Details' : 'Show District-Level Details'}
            </button>
          </div>

          <OpsDataTable
            rows={filteredDistrictRows}
            columns={[
              { key: 'solver_run_id', label: 'Run ID' },
              { key: 'district_code', label: 'District' },
              { key: 'resource_id', label: 'Resource' },
              { key: 'time', label: 'Time' },
              { key: 'district_request', label: 'Requested Qty' },
              { key: 'allocated_quantity', label: 'Allocated Quantity' },
              { key: 'unmet_quantity', label: 'Unmet Quantity' },
              {
                key: 'coverage',
                label: 'Coverage %',
                render: (row) => {
                  const demand = Number(row.district_request || 0)
                  return demand > 0 ? `${((Number(row.allocated_quantity || 0) / demand) * 100).toFixed(1)}%` : '0.0%'
                },
                filterable: false,
              },
            ]}
            rowKey={(row, idx) => `${row.district_code}_${row.resource_id}_${row.time}_${idx}`}
            emptyMessage="No allocation summary available yet."
          />

          {showDetailedAllocations && (
            <div className="mt-4">
              <OpsDataTable
                rows={filteredDistrictRows}
                columns={[
                  { key: 'solver_run_id', label: 'Run ID' },
                  { key: 'district_code', label: 'District' },
                  { key: 'resource_id', label: 'Resource' },
                  { key: 'time', label: 'Time' },
                  { key: 'allocated_quantity', label: 'Allocated' },
                  { key: 'unmet_quantity', label: 'Unmet' },
                ]}
                rowKey={(row, idx) => `detail_${row.district_code}_${row.resource_id}_${row.time}_${idx}`}
                emptyMessage="No allocation summary available yet."
              />
            </div>
          )}
        </Section>
      )}

      {mainTab === 'mutual-aid' && (
        <Section title="Mutual Aid Market">
          <OpsDataTable
            rows={mutualAidMarket}
            columns={[
              { key: 'requesting_state', label: 'Requesting State' },
              { key: 'requesting_district', label: 'Requesting District' },
              { key: 'resource_id', label: 'Resource' },
              { key: 'time', label: 'Time' },
              { key: 'quantity_requested', label: 'Requested' },
              { key: 'accepted_quantity', label: 'Accepted' },
              { key: 'remaining_quantity', label: 'Remaining' },
              { key: 'status', label: 'Status' },
              {
                key: 'offer',
                label: 'Offer',
                sortable: false,
                filterable: false,
                render: (row) => (
                  <button
                    className="px-2 py-1 rounded bg-indigo-600 text-white text-xs"
                    disabled={offerBusyId === row.id}
                    onClick={() => submitMutualAidOffer(row)}
                  >
                    {offerBusyId === row.id ? 'Offering...' : 'Offer Mutual Aid'}
                  </button>
                ),
              },
            ]}
            rowKey={(row) => String(row.id)}
            emptyMessage="No open mutual aid requests."
          />
        </Section>
      )}

      {mainTab === 'state-stock' && (
        <Section title="State Stock">
          {stockRows.length === 0 ? (
            <EmptyState message="No state stock rows available." />
          ) : (
            <ResourceStockTabs rows={stockRows} resources={resources} defaultScope="state" />
          )}
        </Section>
      )}

      {mainTab === 'refill' && (
        <Section title="Refill Resources">
          <ResourceRefillPanel
            scope="state"
            resources={resources}
            endpoint={BACKEND_PATHS.stateStockRefill}
            onRefilled={loadData}
          />
        </Section>
      )}

      {mainTab === 'agent' && (
        <Section title="Agent Recommendations">
          <OpsDataTable
            rows={agentRows}
            columns={[
              { key: 'finding_type', label: 'Finding Type' },
              { key: 'entity_id', label: 'District' },
              { key: 'recommendation_type', label: 'Recommendation' },
              { key: 'severity', label: 'Severity' },
              { key: 'status', label: 'Status' },
            ]}
            rowKey={(row) => String(row.id)}
            emptyMessage="No state-scoped recommendations."
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
            emptyMessage="No state run history rows."
          />
        </Section>
      )}
    </div>
  )
}
