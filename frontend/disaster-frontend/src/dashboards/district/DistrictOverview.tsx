import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import Section from '../shared/Section'
import StatCard from '../shared/StatCard'
import EmptyState from '../shared/EmptyState'
import OpsDataTable from '../shared/OpsDataTable'

import { BACKEND_PATHS } from '../../data/backendPaths'
import { AllocationRow } from '../../data/districtContracts'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch } from '../../data/apiClient'
import { downloadCsv } from '../../utils/csv'
import ResourceStockTabs from '../../components/ResourceStockTabs'
import ResourceRefillPanel from '../../components/ResourceRefillPanel'

import { useDistrictClaims } from '../../state/districtClaims'
import { useDistrictConsumption } from '../../state/districtConsumption'
import { useDistrictReturns } from '../../state/districtReturns'
import { useLiveAllocationStream } from '../../state/useLiveAllocationStream'

type ResourceMeta = {
  resource_id: string
  resource_name: string
  is_returnable?: boolean
  is_consumable?: boolean
  class?: string
}

type DistrictRequestRow = {
  id: number
  run_id?: number
  resource_id: string
  time: number
  quantity: number
  allocated_quantity?: number
  unmet_quantity?: number
  priority?: number
  urgency?: number
  status: string
  source?: string
  included_in_run?: boolean
  queued?: boolean
  final_demand_quantity?: number
  created_at?: string
}

type UnmetRow = {
  id: number
  solver_run_id: number
  resource_id: string
  district_code: string
  time: number
  unmet_quantity: number
}

type SolverStatus = {
  solver_run_id: number | null
  status: string
  mode: string
  started_at?: string
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

type TabKey = 'requests' | 'allocations' | 'upstream' | 'unmet' | 'stock' | 'refill' | 'agent' | 'history'
type RequestSubTab = 'pending' | 'allocated' | 'partial' | 'unmet' | 'escalated'

async function safeFetch<T>(url: string, init?: RequestInit): Promise<T> {
  return apiFetch<T>(url, init)
}

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

function sortAllocationsLatestFirst(rows: AllocationRow[]): AllocationRow[] {
  return [...rows].sort((a, b) => {
    const runDiff = Number(b.solver_run_id || 0) - Number(a.solver_run_id || 0)
    if (runDiff !== 0) return runDiff
    const timeDiff = Number(b.time || 0) - Number(a.time || 0)
    if (timeDiff !== 0) return timeDiff
    return Number(b.id || 0) - Number(a.id || 0)
  })
}

function sortRequestsLatestFirst(rows: DistrictRequestRow[]): DistrictRequestRow[] {
  return [...rows].sort((a, b) => {
    const runDiff = Number(b.run_id || 0) - Number(a.run_id || 0)
    if (runDiff !== 0) return runDiff
    const aTs = a.created_at ? Date.parse(a.created_at) : 0
    const bTs = b.created_at ? Date.parse(b.created_at) : 0
    if (bTs !== aTs) return bTs - aTs
    return Number(b.id || 0) - Number(a.id || 0)
  })
}

export default function DistrictOverview() {
    function supplyBadge(level?: string) {
      const v = String(level || 'district').toLowerCase()
      if (v === 'state') return <span className="px-2 py-1 rounded bg-blue-100 text-blue-700 border border-blue-200 text-xs font-medium">State</span>
      if (v === 'national') return <span className="px-2 py-1 rounded bg-purple-100 text-purple-700 border border-purple-200 text-xs font-medium">National</span>
      return <span className="px-2 py-1 rounded bg-emerald-100 text-emerald-700 border border-emerald-200 text-xs font-medium">District</span>
    }

  const { districtCode, token } = useAuth()
  const navigate = useNavigate()

  const [allocations, setAllocations] = useState<AllocationRow[]>([])
  const [requests, setRequests] = useState<DistrictRequestRow[]>([])
  const [unmetRows, setUnmetRows] = useState<UnmetRow[]>([])
  const [resources, setResources] = useState<ResourceMeta[]>([])
  const [solverStatus, setSolverStatus] = useState<SolverStatus>({ solver_run_id: null, status: 'idle', mode: 'live' })
  const [kpi, setKpi] = useState<KpiPayload>({ solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 })
  const [stockRows, setStockRows] = useState<StockRow[]>([])
  const [runHistoryRows, setRunHistoryRows] = useState<RunHistoryRow[]>([])

  const [mainTab, setMainTab] = useState<TabKey>('allocations')
  const [overviewBoot, setOverviewBoot] = useState(true)
  const [requestTab, setRequestTab] = useState<RequestSubTab>('pending')

  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>('')
  const [runBusy, setRunBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [claimBusy, setClaimBusy] = useState<string>('')
  const [demandMode, setDemandMode] = useState<string>('ai_human')
  const lastTopAllocationKeyRef = useRef<string>('')
  const autoLifecycleBusyRef = useRef(false)
  const autoLifecycleProcessedRef = useRef<Set<string>>(new Set())
  const shouldSyncOps = !overviewBoot && (mainTab === 'allocations' || mainTab === 'upstream')

  const { claims, claimResource, refreshClaims } = useDistrictClaims(shouldSyncOps)
  const { consumption, consumeResource, refreshConsumption } = useDistrictConsumption(shouldSyncOps)
  const { returns, returnResource, refreshReturns } = useDistrictReturns(shouldSyncOps)
  const streamEnabled = Boolean(token && districtCode)

  useEffect(() => {
    if (!overviewBoot) return
    setOverviewBoot(false)
  }, [overviewBoot])

  async function fetchData() {
    if (!districtCode || !token) return
    try {
      const shouldLoadRequests = !overviewBoot && mainTab === 'requests'
      const shouldLoadAllocations = !overviewBoot && (mainTab === 'allocations' || mainTab === 'upstream')
      const shouldLoadUnmet = !overviewBoot && mainTab === 'unmet'
      const shouldLoadStock = !overviewBoot && (mainTab === 'stock' || mainTab === 'refill')
      const shouldLoadHistory = !overviewBoot && mainTab === 'history'
      const shouldLoadResources = !overviewBoot && (mainTab === 'allocations' || mainTab === 'upstream' || mainTab === 'unmet' || mainTab === 'stock' || mainTab === 'refill' || mainTab === 'agent')

      const settled = await Promise.allSettled([
        shouldLoadAllocations ? safeFetch<AllocationRow[]>(`${BACKEND_PATHS.districtAllocations}?page=1&page_size=200`) : Promise.resolve([] as AllocationRow[]),
        shouldLoadUnmet ? safeFetch<UnmetRow[]>(`${BACKEND_PATHS.districtUnmet}?page=1&page_size=200`) : Promise.resolve([] as UnmetRow[]),
        safeFetch<{ demand_mode: string; ui_mode?: string }>(BACKEND_PATHS.districtGetDemandMode),
        safeFetch<SolverStatus>(BACKEND_PATHS.districtSolverStatus),
        shouldLoadResources ? safeFetch<ResourceMeta[]>(BACKEND_PATHS.resourceCatalog) : Promise.resolve([] as ResourceMeta[]),
        safeFetch<KpiPayload>(BACKEND_PATHS.districtKpis),
        shouldLoadStock ? safeFetch<StockRow[]>(BACKEND_PATHS.districtStock) : Promise.resolve([] as StockRow[]),
        shouldLoadHistory ? safeFetch<RunHistoryRow[]>(`${BACKEND_PATHS.districtRunHistory}?page=1&page_size=200`) : Promise.resolve([] as RunHistoryRow[]),
      ])

      const allocRes = settled[0].status === 'fulfilled' ? settled[0].value : []
      const unmetRes = settled[1].status === 'fulfilled' ? settled[1].value : []
      const modeRes = settled[2].status === 'fulfilled' ? settled[2].value : null
      const solverRes = settled[3].status === 'fulfilled' ? settled[3].value : null
      const resourceRes = settled[4].status === 'fulfilled' ? settled[4].value : []
      const kpiRes = settled[5].status === 'fulfilled' ? settled[5].value : null
      const stockRes = settled[6].status === 'fulfilled' ? settled[6].value : []
      const historyRes = settled[7].status === 'fulfilled' ? settled[7].value : []

      const scopedAlloc = safeArray<AllocationRow>(allocRes).filter((r) => String(r.district_code) === String(districtCode))
      const scopedUnmet = safeArray<UnmetRow>(unmetRes).filter((r) => String(r.district_code) === String(districtCode))

      if (shouldLoadAllocations) setAllocations(sortAllocationsLatestFirst(scopedAlloc))
      if (shouldLoadUnmet) setUnmetRows(scopedUnmet)
      if (shouldLoadResources) setResources(safeArray<ResourceMeta>(resourceRes))
      setSolverStatus(solverRes || { solver_run_id: null, status: 'idle', mode: 'live' })
      setKpi(kpiRes || { solver_run_id: null, allocated: 0, unmet: 0, final_demand: 0, coverage: 0 })
      if (shouldLoadStock) setStockRows(safeArray<StockRow>(stockRes))
      if (shouldLoadHistory) setRunHistoryRows(safeArray<RunHistoryRow>(historyRes))

      if (shouldLoadRequests) {
        try {
          const reqRes = await safeFetch<DistrictRequestRow[]>(`${BACKEND_PATHS.districtListRequests}?page=1&page_size=200`)
          const scopedRequests = safeArray<DistrictRequestRow>(reqRes).filter((r) => !districtCode || String((r as any).district_code || districtCode) === String(districtCode))
          setRequests(sortRequestsLatestFirst(scopedRequests))
        } catch {
        }
      }
      if (modeRes?.demand_mode) {
        setDemandMode(modeRes.ui_mode || (modeRes.demand_mode === 'baseline_plus_human' ? 'ai_human' : modeRes.demand_mode))
      }

      if (modeRes?.demand_mode && modeRes.ui_mode === 'human_only' && requestTab === 'allocated') {
        setRequestTab('pending')
      }

      setLastUpdatedAt(new Date().toLocaleTimeString())
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to refresh district dashboard')
    }
  }

  useEffect(() => {
    fetchData()
    if (shouldSyncOps) {
      refreshClaims()
      refreshConsumption()
      refreshReturns()
    }
    if (streamEnabled) return
    const id = setInterval(() => {
      fetchData()
      if (shouldSyncOps) {
        refreshClaims()
        refreshConsumption()
        refreshReturns()
      }
    }, 4000)
    return () => clearInterval(id)
  }, [districtCode, token, mainTab, streamEnabled, shouldSyncOps])

  useLiveAllocationStream({
    enabled: streamEnabled,
    streamUrl: token ? `${BACKEND_PATHS.districtAllocationsStream}?token=${encodeURIComponent(token)}` : '',
    onDelta: () => {
      fetchData()
      if (shouldSyncOps) {
        refreshClaims()
        refreshConsumption()
        refreshReturns()
      }
    },
  })

  useEffect(() => {
    const onFocus = () => {
      fetchData()
      if (shouldSyncOps) {
        refreshClaims()
        refreshConsumption()
        refreshReturns()
      }
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [districtCode, token, shouldSyncOps])

  const resourceNameMap = useMemo(() => {
    const out: Record<string, string> = {}
    for (const row of resources) out[row.resource_id] = row.resource_name
    return out
  }, [resources])

  const resourceReturnableMap = useMemo(() => {
    const out: Record<string, boolean> = {}
    for (const row of resources) {
      const classValue = String(row.class || '').toLowerCase()
      const inferredConsumable = typeof row.is_consumable === 'boolean'
        ? row.is_consumable
        : classValue === 'consumable'
      out[row.resource_id] = typeof row.is_returnable === 'boolean'
        ? Boolean(row.is_returnable)
        : !inferredConsumable
    }
    return out
  }, [resources])

  const totalFinalDemand = Number(kpi.final_demand || 0)
  const totalAllocated = Number(kpi.allocated || 0)
  const totalUnmet = Number(kpi.unmet || 0)
  const coveragePct = Number(kpi.coverage || 0) * 100

  const avgDelay = useMemo(() => {
    if (!allocations.length) return 0
    const totalDelay = allocations.reduce((sum, row) => sum + Number(row.implied_delay_hours || 0), 0)
    return totalDelay / allocations.length
  }, [allocations])

  const allocationTransparency = useMemo(() => {
    if (!requests.length) return 0
    const traced = requests.filter((row) => !!row.status && !!row.created_at).length
    const traceScore = traced / requests.length
    const coverageScore = Math.max(0, Math.min(1, coveragePct / 100))
    return ((coverageScore * 0.7) + (traceScore * 0.3)) * 100
  }, [requests, coveragePct])

  const topUnmetResources = useMemo(() => {
    const grouped = new Map<string, number>()
    for (const row of unmetRows) {
      grouped.set(row.resource_id, (grouped.get(row.resource_id) || 0) + Number(row.unmet_quantity || 0))
    }
    return Array.from(grouped.entries())
      .map(([resource_id, unmet_quantity]) => ({ resource_id, unmet_quantity }))
      .sort((a, b) => b.unmet_quantity - a.unmet_quantity)
      .slice(0, 5)
  }, [unmetRows])

  const requestStatusTabs: Array<{ key: RequestSubTab; label: string; match: (r: DistrictRequestRow) => boolean }> = [
    { key: 'pending', label: 'Pending', match: (r) => String(r.status).toLowerCase() === 'pending' },
    { key: 'allocated', label: 'Allocated', match: (r) => String(r.status).toLowerCase() === 'allocated' },
    { key: 'partial', label: 'Partial', match: (r) => String(r.status).toLowerCase() === 'partial' },
    { key: 'unmet', label: 'Unmet', match: (r) => String(r.status).toLowerCase() === 'unmet' },
    {
      key: 'escalated',
      label: 'Escalated',
      match: (r) => {
        const status = String(r.status).toLowerCase()
        return status.includes('escalat') || status === 'escalated_national'
      },
    },
  ]

  const activeRequestRows = useMemo(() => {
    const tab = requestStatusTabs.find((t) => t.key === requestTab)
    return requests.filter((row) => (tab ? tab.match(row) : true))
  }, [requests, requestTab])

  const requestRowsForTable = useMemo(
    () =>
      sortRequestsLatestFirst(activeRequestRows).map((row) => ({
        ...row,
        quantity_requested: Number(row.quantity || 0),
        resource_label: resourceNameMap[row.resource_id] || row.resource_id,
      })),
    [activeRequestRows, resourceNameMap],
  )

  const allocationRowsForTable = useMemo(() => {
    const slotKey = (runId: number, resourceId: string, time: number) => `${runId}_${resourceId}_${time}`

    const claimedBySlot = new Map<string, number>()
    for (const row of claims) {
      const runId = Number(row.solver_run_id || 0)
      if (!runId) continue
      const key = slotKey(runId, String(row.resource_id), Number(row.time))
      claimedBySlot.set(key, (claimedBySlot.get(key) || 0) + Number(row.claimed_quantity || 0))
    }

    const consumedBySlot = new Map<string, number>()
    for (const row of consumption) {
      const runId = Number(row.solver_run_id || 0)
      if (!runId) continue
      const key = slotKey(runId, String(row.resource_id), Number(row.time))
      consumedBySlot.set(key, (consumedBySlot.get(key) || 0) + Number(row.consumed_quantity || 0))
    }

    const returnedBySlot = new Map<string, number>()
    for (const row of returns) {
      const runId = Number(row.solver_run_id || 0)
      if (!runId) continue
      const key = slotKey(runId, String(row.resource_id), Number(row.time))
      returnedBySlot.set(key, (returnedBySlot.get(key) || 0) + Number(row.returned_quantity || 0))
    }

    return sortAllocationsLatestFirst(allocations).map((row, idx) => {
      const runId = Number(row.solver_run_id || 0)
      const key = slotKey(runId, String(row.resource_id), Number(row.time))

      const claimed = claimedBySlot.has(key)
        ? Number(claimedBySlot.get(key) || 0)
        : Number(row.claimed_quantity || 0)
      const consumed = consumedBySlot.has(key)
        ? Number(consumedBySlot.get(key) || 0)
        : Number(row.consumed_quantity || 0)
      const returned = returnedBySlot.has(key)
        ? Number(returnedBySlot.get(key) || 0)
        : Number(row.returned_quantity || 0)
      const remaining = Math.max(0, claimed - consumed - returned)
      return {
        ...row,
        _key: `${row.solver_run_id}_${row.resource_id}_${row.time}_${idx}`,
        resource_label: resourceNameMap[row.resource_id] || row.resource_id,
        delay_hrs: Number(row.implied_delay_hours || 0),
        receipt_confirmed_text: row.receipt_confirmed ? 'Yes' : 'No',
        claimed,
        consumed,
        returned,
        remaining,
      }
    })
  }, [allocations, resourceNameMap, claims, consumption, returns])

  const unmetRowsForTable = useMemo(() => {
    const finalDemandBySlot = new Map<string, number>()
    for (const req of requests) {
      const key = `${req.resource_id}_${req.time}`
      finalDemandBySlot.set(key, Math.max(finalDemandBySlot.get(key) || 0, Number(req.final_demand_quantity ?? req.quantity ?? 0)))
    }

    return unmetRows.map((row) => {
      const key = `${row.resource_id}_${row.time}`
      const finalDemand = finalDemandBySlot.get(key) || 0
      const scarcityPct = finalDemand > 1e-9 ? (Number(row.unmet_quantity || 0) / finalDemand) * 100 : 0
      return {
        ...row,
        resource_label: resourceNameMap[row.resource_id] || row.resource_id,
        scarcity_pct: `${scarcityPct.toFixed(1)}%`,
      }
    })
  }, [unmetRows, requests, resourceNameMap])

  const upstreamRowsForTable = useMemo(() => {
    return allocationRowsForTable
      .filter((row) => String(row.supply_level || '').toLowerCase() !== 'district')
      .map((row) => ({
        ...row,
        source_state: row.origin_state_code || row.state_code || 'NATIONAL',
        delay_display: Number(row.delay_hrs || 0).toFixed(2),
        receipt_display: row.receipt_confirmed ? 'Yes' : 'No',
      }))
  }, [allocationRowsForTable])

  const derivedAgentRows = useMemo(() => {
    return topUnmetResources.map((row, idx) => ({
      id: idx + 1,
      finding_type: 'chronic_unmet',
      resource: resourceNameMap[row.resource_id] || row.resource_id,
      district: districtCode || '—',
      recommendation: `Prioritize ${resourceNameMap[row.resource_id] || row.resource_id} rebalancing in next run`,
      status: 'pending_review',
      unmet_quantity: Number(row.unmet_quantity || 0),
    }))
  }, [topUnmetResources, resourceNameMap, districtCode])

  const runHistoryRowsForTable = useMemo(
    () => safeArray<RunHistoryRow>(runHistoryRows).map((row) => ({
      run_id: row.run_id,
      time: row.started_at ? new Date(row.started_at).toLocaleString() : '—',
      mode: row.mode || 'live',
      total_demand: Number(row.total_demand || 0).toFixed(2),
      total_allocated: Number(row.total_allocated || 0).toFixed(2),
      total_unmet: Number(row.total_unmet || 0).toFixed(2),
    })),
    [runHistoryRows],
  )

  async function runSolverNow() {
    if (runBusy) return
    setActionError('')
    setActionMessage('')
    setRunBusy(true)
    try {
      await safeFetch(BACKEND_PATHS.districtRunSolver, { method: 'POST' })
      setActionMessage('Solver run started.')
      await fetchData()
      await refreshClaims()
      await refreshConsumption()
      await refreshReturns()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to start solver run')
    } finally {
      setRunBusy(false)
    }
  }

  async function claimAllocation(resourceId: string, time: number, quantity: number, solverRunId?: number) {
    if (!districtCode || quantity <= 0) return
    const actionKey = `${solverRunId || 'latest'}_${resourceId}_${time}`
    setClaimBusy(actionKey)
    setActionError('')
    try {
      await claimResource(districtCode, resourceId, time, quantity, 'district_manager', solverRunId)
      await fetchData()
      setActionMessage(`Claim confirmed for ${resourceNameMap[resourceId] || resourceId} at time ${time}.`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Claim failed')
    } finally {
      setClaimBusy('')
    }
  }

  async function consumeAllocation(resourceId: string, time: number, quantity: number, solverRunId?: number) {
    if (!districtCode || quantity <= 0) return
    setActionError('')
    try {
      await consumeResource(districtCode, resourceId, time, quantity, solverRunId)
      await fetchData()
      setActionMessage(`Consumption confirmed for ${resourceNameMap[resourceId] || resourceId} at time ${time}.`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Consume failed')
    }
  }

  async function returnAllocation(
    resourceId: string,
    time: number,
    quantity: number,
    solverRunId?: number,
    allocationSourceScope?: string,
    allocationSourceCode?: string,
  ) {
    if (!districtCode || quantity <= 0) return
    setActionError('')
    try {
      await returnResource(
        districtCode,
        resourceId,
        time,
        quantity,
        'manual',
        solverRunId,
        allocationSourceScope,
        allocationSourceCode,
      )
      await fetchData()
      setActionMessage(`Return logged for ${resourceNameMap[resourceId] || resourceId} at time ${time}.`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Return failed')
    }
  }

  async function autoProcessTailAllocation(row: any) {
    if (!districtCode) return
    const runId = Number((row as any).solver_run_id || 0) || undefined
    const key = `${runId || 'latest'}_${row.resource_id}_${row.time}`
    if (autoLifecycleProcessedRef.current.has(key)) return
    if (autoLifecycleBusyRef.current) return

    autoLifecycleBusyRef.current = true
    setActionError('')
    try {
      const allocated = Number(row.allocated_quantity || 0)
      if (allocated <= 0) {
        autoLifecycleProcessedRef.current.add(key)
        return
      }

      let claimed = Number(row.claimed || 0)
      let consumed = Number(row.consumed || 0)
      let returned = Number(row.returned || 0)

      if (claimed <= 1e-9) {
        const claimQty = Math.max(1, Math.floor(allocated))
        await claimAllocation(row.resource_id, Number(row.time), claimQty, runId)
        claimed = claimQty
      }

      const remaining = Math.max(0, claimed - consumed - returned)
      if (remaining > 1e-9) {
        const actQty = Math.max(1, Math.floor(remaining))
        const returnable = resourceReturnableMap[row.resource_id] !== false
        if (returnable) {
          await returnAllocation(
            row.resource_id,
            Number(row.time),
            actQty,
            runId,
            String((row as any).allocation_source_scope || row.supply_level || ''),
            String((row as any).allocation_source_code || row.origin_state_code || row.state_code || ''),
          )
        } else {
          await consumeAllocation(row.resource_id, Number(row.time), actQty, runId)
        }
      }

      autoLifecycleProcessedRef.current.add(key)
      setActionMessage(`Auto-processed tail row for ${resourceNameMap[row.resource_id] || row.resource_id} (run ${runId || 'latest'}).`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Auto tail processing failed')
    } finally {
      autoLifecycleBusyRef.current = false
    }
  }

  useEffect(() => {
    if (mainTab !== 'allocations') return
    if (!allocationRowsForTable.length) return

    const top = allocationRowsForTable[0]
    const topKey = `${top.solver_run_id || 'latest'}_${top.resource_id}_${top.time}_${top.id || 0}`
    if (!lastTopAllocationKeyRef.current) {
      lastTopAllocationKeyRef.current = topKey
      return
    }
    if (topKey === lastTopAllocationKeyRef.current) return

    lastTopAllocationKeyRef.current = topKey
    const tail = allocationRowsForTable[allocationRowsForTable.length - 1]
    void autoProcessTailAllocation(tail)
  }, [mainTab, allocationRowsForTable])

  const tabs: Array<{ key: TabKey; label: string }> = [
    { key: 'requests', label: 'Requests' },
    { key: 'allocations', label: 'Allocations' },
    { key: 'upstream', label: 'Upstream Supply' },
    { key: 'unmet', label: 'Unmet' },
    { key: 'stock', label: 'Resource Stocks' },
    { key: 'refill', label: 'Refill Resources' },
    { key: 'agent', label: 'Agent Recommendations' },
    { key: 'history', label: 'Run History' },
  ]

  return (
    <div className="space-y-4">
      <Section title={`District Overview (District ${districtCode})`}>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-3">
          <StatCard label="Total Final Demand" value={totalFinalDemand.toFixed(2)} />
          <StatCard label="Allocated Resources" value={totalAllocated.toFixed(2)} />
          <StatCard label="Unmet Demand" value={totalUnmet.toFixed(2)} />
          <StatCard label="Coverage %" value={`${coveragePct.toFixed(1)}%`} />
          <StatCard label="Runs Freshness (Last Run Time)" value={lastUpdatedAt || '—'} />
        </div>

        <div className="mb-3 max-w-sm">
          <StatCard label="Allocation Transparency" value={`${allocationTransparency.toFixed(1)} / 100`} />
        </div>

        <div className="mb-3">
          <label className="mr-2 font-semibold text-sm">Demand Mode:</label>
          <select
            value={demandMode}
            onChange={async (e) => {
              const uiMode = e.target.value
              const backendMode = uiMode === 'ai_human' ? 'baseline_plus_human' : uiMode
              setDemandMode(uiMode)
              try {
                await apiFetch(BACKEND_PATHS.districtSetDemandMode, {
                  method: 'PUT',
                  body: JSON.stringify({ demand_mode: backendMode }),
                })
                await fetchData()
              } catch (error) {
                setActionError(error instanceof Error ? error.message : 'Failed to update demand mode')
              }
            }}
            className="border px-2 py-1 rounded"
          >
            <option value="ai_human">AI + Human</option>
            <option value="human_only">Human Only</option>
          </select>
        </div>

        <div className="mb-2 text-xs text-slate-600">Transparency score = weighted view of allocation coverage, unmet closure, and request traceability.</div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3 text-xs">
          <div className="border rounded px-3 py-2 bg-white">
            <div className="font-semibold">Avg Delay per resource</div>
            <div>{avgDelay.toFixed(2)} hrs</div>
          </div>
          <div className="border rounded px-3 py-2 bg-white md:col-span-2">
            <div className="font-semibold mb-1">Top 5 unmet resources</div>
            {topUnmetResources.length === 0 ? (
              <span>No unmet resources</span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {topUnmetResources.map((row) => (
                  <span key={row.resource_id} className="px-2 py-1 rounded bg-amber-50 border border-amber-200">
                    {(resourceNameMap[row.resource_id] || row.resource_id)}: {row.unmet_quantity.toFixed(2)}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2 mb-3">
          <button onClick={() => navigate('/district/request')} className="px-4 py-2 bg-blue-600 text-white rounded">
            Request Resources
          </button>
          <button onClick={runSolverNow} disabled={runBusy} className="px-4 py-2 bg-emerald-700 text-white rounded disabled:opacity-60">
            {runBusy ? 'Running Solver...' : 'Run Solver'}
          </button>
          <button
            className="px-3 py-2 rounded border text-sm"
            onClick={() => downloadCsv(`district_${districtCode}_allocations.csv`, allocationRowsForTable)}
          >
            Export CSV
          </button>
        </div>

        <div className="mb-2 text-xs text-slate-600">Run: {solverStatus.solver_run_id ?? '—'} | Status: {solverStatus.status} | Last refresh: {lastUpdatedAt || '—'}</div>

        {actionError && <div className="mb-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">{actionError}</div>}
        {actionMessage && <div className="mb-2 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1">{actionMessage}</div>}

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

      {mainTab === 'requests' && (
        <Section title="Request Logs (District)">
          <div className="flex flex-wrap gap-2 mb-3">
            {requestStatusTabs.map((tab) => (
              <button
                key={tab.key}
                className={`px-3 py-1 rounded border text-sm ${requestTab === tab.key ? 'bg-blue-600 text-white border-blue-600' : 'bg-white'}`}
                onClick={() => setRequestTab(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <OpsDataTable
            rows={requestRowsForTable}
            columns={[
              { key: 'run_id', label: 'Run ID' },
              { key: 'resource_label', label: 'Resource' },
              { key: 'time', label: 'Time' },
              { key: 'quantity_requested', label: 'Quantity Requested' },
              { key: 'status', label: 'Status' },
              { key: 'priority', label: 'Priority' },
              { key: 'urgency', label: 'Urgency' },
              { key: 'included_in_run', label: 'Included in Run' },
              { key: 'queued', label: 'Queued' },
            ]}
            emptyMessage="No request rows for selected status."
            rowKey={(row) => String(row.id)}
          />
        </Section>
      )}

      {mainTab === 'allocations' && (
        <Section title="Claim, Consume & Return Resources">
          <OpsDataTable
            rows={allocationRowsForTable}
            columns={[
              { key: 'resource_label', label: 'Resource' },
              { key: 'allocated_quantity', label: 'Allocated Quantity' },
              {
                key: 'supply_level',
                label: 'Supply Level',
                render: (row) => supplyBadge(String(row.supply_level || 'district')),
              },
              {
                key: 'allocation_source_scope',
                label: 'Source Scope',
                render: (row) => String((row as any).allocation_source_scope || row.supply_level || 'district'),
              },
              {
                key: 'allocation_source_code',
                label: 'Source Code',
                render: (row) => String((row as any).allocation_source_code || row.origin_state_code || row.state_code || '—'),
              },
              {
                key: 'origin',
                label: 'Origin State/District',
                render: (row) => `${row.origin_state_code || '—'} / ${row.origin_district_code || '—'}`,
                filterable: false,
              },
              { key: 'delay_hrs', label: 'Delay (hrs)' },
              { key: 'receipt_confirmed_text', label: 'Receipt Confirmed' },
              {
                key: 'actions',
                label: 'Actions',
                sortable: false,
                filterable: false,
                render: (row) => {
                  const actionKey = `${row.solver_run_id || 'latest'}_${row.resource_id}_${row.time}`
                  const allocated = Number(row.allocated_quantity || 0)
                  const claimed = Number(row.claimed || 0)
                  const consumed = Number(row.consumed || 0)
                  const returned = Number(row.returned || 0)
                  const remaining = Number(row.remaining || 0)
                  const returnable = resourceReturnableMap[row.resource_id] !== false
                  const consumable = !returnable
                  const runId = Number((row as any).solver_run_id || 0) || undefined

                  if (claimed > 0 && returned >= claimed - 1e-9) {
                    return <button className="px-2 py-1 rounded bg-slate-500 text-white text-xs" disabled>Returned</button>
                  }

                  if (claimed > 0 && consumed >= claimed - 1e-9) {
                    return <button className="px-2 py-1 rounded bg-slate-500 text-white text-xs" disabled>Consumed</button>
                  }

                  if (allocated <= 0) {
                    return <button className="px-2 py-1 rounded bg-slate-500 text-white text-xs" disabled>Empty</button>
                  }

                  if (claimed <= 1e-9) {
                    return (
                      <button
                        className="px-2 py-1 rounded bg-blue-600 text-white text-xs disabled:opacity-50"
                        disabled={claimBusy === actionKey || Number(row.allocated_quantity || 0) <= 0}
                        onClick={() => claimAllocation(row.resource_id, Number(row.time), Math.max(1, Math.floor(Number(row.allocated_quantity || 0))), runId)}
                      >
                        Claim
                      </button>
                    )
                  }

                  if (remaining <= 0) {
                    return <button className="px-2 py-1 rounded bg-slate-500 text-white text-xs" disabled>Claimed</button>
                  }

                  if (consumable) {
                    return (
                      <button
                        className="px-2 py-1 rounded bg-emerald-700 text-white text-xs disabled:opacity-50"
                        disabled={remaining <= 0}
                        onClick={() => consumeAllocation(row.resource_id, Number(row.time), Math.max(1, Math.floor(remaining)), runId)}
                      >
                        Consume
                      </button>
                    )
                  }

                  return (
                    <button
                      className="px-2 py-1 rounded bg-amber-700 text-white text-xs disabled:opacity-50"
                      disabled={remaining <= 0}
                      onClick={() =>
                        returnAllocation(
                          row.resource_id,
                          Number(row.time),
                          Math.max(1, Math.floor(remaining)),
                          runId,
                          String((row as any).allocation_source_scope || row.supply_level || ''),
                          String((row as any).allocation_source_code || row.origin_state_code || row.state_code || ''),
                        )
                      }
                    >
                      Return
                    </button>
                  )
                },
              },
            ]}
            rowKey={(row) => row._key}
            emptyMessage="No allocations for this district."
          />
          <div className="mt-2 text-xs text-slate-600">Coverage % uses allocated / final_demand based on current run request lineage.</div>
        </Section>
      )}

      {mainTab === 'upstream' && (
        <Section title="Upstream Allocations">
          <OpsDataTable
            rows={upstreamRowsForTable}
            columns={[
              { key: 'resource_label', label: 'Resource' },
              { key: 'allocated_quantity', label: 'Qty' },
              {
                key: 'supply_level',
                label: 'Source',
                render: (row) => supplyBadge(String(row.supply_level || 'district')),
              },
              { key: 'source_state', label: 'Source State' },
              { key: 'delay_display', label: 'Delay (hrs)' },
              { key: 'receipt_display', label: 'Receipt Confirmed' },
            ]}
            rowKey={(row) => row._key}
            emptyMessage="No upstream allocations in the latest completed run."
          />
        </Section>
      )}

      {mainTab === 'unmet' && (
        <Section title="Unmet Demand">
          <OpsDataTable
            rows={unmetRowsForTable}
            columns={[
              { key: 'resource_label', label: 'Resource' },
              { key: 'time', label: 'Time' },
              { key: 'unmet_quantity', label: 'Unmet Quantity' },
              { key: 'scarcity_pct', label: 'Scarcity %' },
            ]}
            rowKey={(row) => String(row.id)}
            emptyMessage="No unmet demand rows in current view."
          />
        </Section>
      )}

      {mainTab === 'stock' && (
        <Section title="Resource Stocks">
          <ResourceStockTabs rows={stockRows} resources={resources} defaultScope="district" />
        </Section>
      )}

      {mainTab === 'refill' && (
        <Section title="Refill Resources">
          <ResourceRefillPanel
            scope="district"
            resources={resources}
            endpoint={BACKEND_PATHS.districtStockRefill}
            onRefilled={async () => {
              await fetchData()
              await refreshClaims()
              await refreshConsumption()
              await refreshReturns()
            }}
          />
        </Section>
      )}

      {mainTab === 'agent' && (
        <Section title="Agent Recommendations">
          {derivedAgentRows.length === 0 ? (
            <EmptyState message="No recommendation rows available from current unmet signal." />
          ) : (
            <OpsDataTable
              rows={derivedAgentRows}
              columns={[
                { key: 'finding_type', label: 'Finding Type' },
                { key: 'resource', label: 'Resource' },
                { key: 'district', label: 'District' },
                { key: 'recommendation', label: 'Recommendation' },
                { key: 'status', label: 'Status' },
                {
                  key: 'approve',
                  label: 'Approve Button',
                  sortable: false,
                  filterable: false,
                  render: () => <button className="px-2 py-1 rounded bg-slate-700 text-white text-xs">Approve</button>,
                },
              ]}
              rowKey={(row) => String(row.id)}
            />
          )}
        </Section>
      )}

      {mainTab === 'history' && (
        <Section title="Run History">
          <OpsDataTable
            rows={runHistoryRowsForTable}
            columns={[
              { key: 'run_id', label: 'Run ID' },
              { key: 'time', label: 'Time' },
              { key: 'mode', label: 'Mode' },
              { key: 'total_demand', label: 'Total Demand' },
              { key: 'total_allocated', label: 'Total Allocated' },
              { key: 'total_unmet', label: 'Total Unmet' },
            ]}
            pageSize={5}
            rowKey={(row) => String(row.run_id)}
          />
        </Section>
      )}
    </div>
  )
}
