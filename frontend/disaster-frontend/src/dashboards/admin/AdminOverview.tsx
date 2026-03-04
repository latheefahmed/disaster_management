import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Section from '../shared/Section'
import EmptyState from '../shared/EmptyState'
import StatCard from '../shared/StatCard'

import { API_BASE, BACKEND_PATHS } from '../../data/backendPaths'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch } from '../../data/apiClient'
import OpsDataTable from '../shared/OpsDataTable'
import { useAuditLog } from '../../state/auditLog'

type ScenarioRow = {
  id: number
  name: string
  status?: string
  created_at?: string
  demand_rows?: number
  state_stock_rows?: number
  national_stock_rows?: number
}

type ScenarioRun = {
  id: number
  status: string
  mode: string
  started_at?: string
}

type ScenarioRunSummary = {
  run_id: number
  scenario_id?: number
  status?: string
  started_at?: string
  escalation_status?: {
    events_found: number
    state_marked: number
    national_marked: number
    neighbor_offers_created: number
    neighbor_offers_accepted: number
    neighbor_accepted_quantity: number
    mode: string
  }
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
  source_scope_breakdown?: {
    allocations: {
      district: number
      state: number
      neighbor_state: number
      national: number
    }
    percentages: {
      district: number
      state: number
      neighbor_state: number
      national: number
    }
  }
  by_time_breakdown?: Array<{
    time: number
    demand_quantity: number
    allocated_quantity: number
    unmet_quantity: number
    service_ratio: number
  }>
  used_state_stock?: boolean
  used_national_stock?: boolean
  allocation_details?: Array<{
    resource_id: string
    district_code: string
    time: number
    allocated_quantity: number
    source_level: 'district' | 'state' | 'national'
  }>
  fairness?: {
    district_ratio_jain?: number | null
    state_ratio_jain?: number | null
    district_ratio_gap?: number | null
    state_ratio_gap?: number | null
    time_service_early_avg?: number | null
    time_service_late_avg?: number | null
    fairness_flags: string[]
  }
}

type ScenarioAnalysis = {
  explanations: Array<{
    id: number
    summary: string
    details?: any
    created_at?: string
    solver_run_id?: number
  }>
  recommendations: Array<{
    id: number
    district_code?: string
    resource_id?: string
    action_type: string
    message: string
    requires_confirmation: boolean
    status: string
    created_at?: string
  }>
}

type StateMeta = {
  state_code: string
  state_name: string
}

type DistrictMeta = {
  district_code: string
  district_name?: string
  state_code: string
}

type ResourceMeta = {
  resource_id: string
  resource_name: string
}

type AgentRecommendationRow = {
  id: number
  finding_id?: number | null
  entity_type?: string | null
  entity_id?: string | null
  finding_type?: string | null
  severity?: string | null
  evidence_json?: any
  recommendation_type?: string | null
  payload_json?: any
  message?: string | null
  status: string
  created_at?: string
}

type RandomizerPreview = {
  scenario_id: number
  preset: string
  intensity_ratio?: number
  seed?: number | null
  time_horizon: number
  stress_mode: boolean
  replace_existing: boolean
  latest_live_run_id?: number | null
  district_count: number
  resource_count: number
  row_count: number
  total_quantity: number
  baseline_total_quantity: number
  demand_ratio_vs_baseline?: number | null
  total_available_supply?: number
  total_generated_demand?: number
  demand_supply_ratio?: number | null
  expected_shortage_estimate?: number
  selected_districts?: string[]
  selected_resources?: string[]
  avg_available_stock?: number
  avg_priority?: number
  avg_time_index?: number
  stock_backed_rows?: number
  zero_stock_rows?: number
  quantity_mode?: 'fixed' | 'stock_aware'
  guardrail_warnings: string[]
}

type RevertVerify = {
  scenario_id: number
  run_ids: number[]
  debit_total: number
  revert_total: number
  net_total: number
  ok: boolean
}

type ScenarioIncident = {
  run_id: number
  status: string
  started_at?: string
  reasons: string[]
  unmet_quantity: number
  districts_unmet: number
  time_service_early_avg?: number | null
  time_service_late_avg?: number | null
  fairness_flags: string[]
  scope_allocations: {
    district: number
    state: number
    neighbor_state: number
    national: number
  }
}

type ScenarioIncidentResponse = {
  scenario_id: number
  scanned_runs: number
  incident_count: number
  incidents: ScenarioIncident[]
}

type AdminOverviewProps = {
  initialAdminView?: 'system' | 'scenarios'
}

type ScenarioLifecycleState =
  | 'draft'
  | 'ready'
  | 'running'
  | 'completed'
  | 'failed'
  | 'reverting'
  | 'verifying'
  | 'finalized'

export default function AdminOverview({ initialAdminView = 'system' }: AdminOverviewProps) {
  const { token } = useAuth()
  const { events } = useAuditLog()

  const [scenarios, setScenarios] = useState<ScenarioRow[]>([])
  const [selectedScenarioId, setSelectedScenarioId] = useState<number | null>(null)
  const [scenarioRuns, setScenarioRuns] = useState<ScenarioRun[]>([])
  const [analysis, setAnalysis] = useState<ScenarioAnalysis>({ explanations: [], recommendations: [] })

  const [states, setStates] = useState<StateMeta[]>([])
  const [districts, setDistricts] = useState<DistrictMeta[]>([])
  const [resources, setResources] = useState<ResourceMeta[]>([])

  const [busy, setBusy] = useState(false)
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [isApplyingRandomizer, setIsApplyingRandomizer] = useState(false)
  const [isRunningScenario, setIsRunningScenario] = useState(false)
  const [isReverting, setIsReverting] = useState(false)
  const [isVerifying, setIsVerifying] = useState(false)
  const [loadingMeta, setLoadingMeta] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState<{ kind: 'success' | 'info' | 'error'; message: string } | null>(null)

  const [newScenarioName, setNewScenarioName] = useState('')

  const [selectedStateCode, setSelectedStateCode] = useState('')
  const [selectedDistrictCodes, setSelectedDistrictCodes] = useState<string[]>([])
  const [selectedResourceIds, setSelectedResourceIds] = useState<string[]>([])

  const [scenarioType, setScenarioType] = useState('multi_district_intra_state')
  const [timeHorizon, setTimeHorizon] = useState<number | ''>(1)
  const [demandMultiplier, setDemandMultiplier] = useState<number | ''>(1)
  const [baseDemandQty, setBaseDemandQty] = useState<number | ''>(100)
  const [resourceDemandMap, setResourceDemandMap] = useState<Record<string, number>>({})
  const [manualPriority, setManualPriority] = useState<number | ''>(3)
  const [manualUrgency, setManualUrgency] = useState<number | ''>(3)
  const [manualTimeIndex, setManualTimeIndex] = useState<number | ''>(1)

  const [stateStockDraft, setStateStockDraft] = useState({
    state_code: '',
    resource_id: '',
    quantity: 0,
  })

  const [nationalStockDraft, setNationalStockDraft] = useState({
    resource_id: '',
    quantity: 0,
  })
  const [selectedRunSummary, setSelectedRunSummary] = useState<ScenarioRunSummary | null>(null)
  const [agentRows, setAgentRows] = useState<AgentRecommendationRow[]>([])
  const [agentBusyId, setAgentBusyId] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<'system-health' | 'solver-runs' | 'neural' | 'agent' | 'audit'>(initialAdminView === 'scenarios' ? 'solver-runs' : 'system-health')
  const [modelingMode, setModelingMode] = useState<'manual' | 'guided_random'>('manual')
  const [randomPreset, setRandomPreset] = useState<'extremely_low' | 'low' | 'medium_low' | 'medium' | 'medium_high' | 'high' | 'extremely_high'>('medium')
  const [randomSeed, setRandomSeed] = useState<number | ''>(() => Number(`${Date.now()}`.slice(-8)))
  const [randomStressMode, setRandomStressMode] = useState<boolean>(false)
  const [randomStockAwareDistribution, setRandomStockAwareDistribution] = useState<boolean>(false)
  const [randomizerPreview, setRandomizerPreview] = useState<RandomizerPreview | null>(null)
  const [revertVerify, setRevertVerify] = useState<RevertVerify | null>(null)
  const [incidentData, setIncidentData] = useState<ScenarioIncidentResponse | null>(null)

  async function reloadScenarios() {
    if (!token) return
    const rows = await apiFetch<ScenarioRow[]>(BACKEND_PATHS.adminScenarios)
    setScenarios(Array.isArray(rows) ? rows : [])

    if (!selectedScenarioId && rows?.length) {
      setSelectedScenarioId(rows[0].id)
    }
  }

  async function reloadScenarioArtifacts(scenarioId: number) {
    if (!token) return
    const [runs, analysisData, incidents] = await Promise.all([
      apiFetch<ScenarioRun[]>(`${BACKEND_PATHS.adminScenarios}/${scenarioId}/runs`),
      apiFetch<ScenarioAnalysis>(`${BACKEND_PATHS.adminScenarios}/${scenarioId}/analysis`),
      apiFetch<ScenarioIncidentResponse>(BACKEND_PATHS.adminScenarioRunIncidents(scenarioId, 80)),
    ])

    setScenarioRuns(Array.isArray(runs) ? runs : [])
    setAnalysis(analysisData || { explanations: [], recommendations: [] })
    setIncidentData(incidents || { scenario_id: scenarioId, scanned_runs: 0, incident_count: 0, incidents: [] })

    const latestRunId = Array.isArray(runs) && runs.length > 0 ? Number(runs[0].id) : 0
    if (latestRunId > 0) {
      try {
        const summary = await apiFetch<ScenarioRunSummary>(
          BACKEND_PATHS.adminScenarioRunSummary(scenarioId, latestRunId)
        )
        setSelectedRunSummary(summary)
      } catch {
        setSelectedRunSummary(null)
      }
    } else {
      setSelectedRunSummary(null)
    }
  }

  async function loadMetadata() {
    if (!token) return
    setLoadingMeta(true)
    try {
      const [stateRows, districtRows, resourceRows] = await Promise.all([
        apiFetch<StateMeta[]>(`${API_BASE}/metadata/states`),
        apiFetch<DistrictMeta[]>(`${API_BASE}/metadata/districts`),
        apiFetch<ResourceMeta[]>(BACKEND_PATHS.resourceCatalog),
      ])

      setStates(Array.isArray(stateRows) ? stateRows : [])
      setDistricts(Array.isArray(districtRows) ? districtRows : [])
      setResources(Array.isArray(resourceRows) ? resourceRows : [])
    } finally {
      setLoadingMeta(false)
    }
  }

  async function loadAgentRecommendations() {
    if (!token) return
    const rows = await apiFetch<AgentRecommendationRow[]>(BACKEND_PATHS.adminAgentRecommendations)
    setAgentRows(Array.isArray(rows) ? rows : [])
  }

  useEffect(() => {
    if (!token) return
    setError('')
    Promise.all([reloadScenarios(), loadMetadata(), loadAgentRecommendations()]).catch(e => {
      setError(e instanceof Error ? e.message : 'Failed to load admin data')
    })
  }, [token])

  useEffect(() => {
    if (!token || !selectedScenarioId) return
    setIncidentData(null)
    reloadScenarioArtifacts(selectedScenarioId).catch(e => {
      setError(e instanceof Error ? e.message : 'Failed to load scenario artifacts')
    })
  }, [token, selectedScenarioId])

  const selectedScenario = useMemo(
    () => scenarios.find(s => s.id === selectedScenarioId) || null,
    [scenarios, selectedScenarioId]
  )

  const persistedDemandRows = useMemo(() => Number(selectedScenario?.demand_rows || 0), [selectedScenario])
  const pendingManualDemandRows = useMemo(
    () => Number(selectedDistrictCodes.length * selectedResourceIds.length * clampPositiveInt(timeHorizon, 1)),
    [selectedDistrictCodes.length, selectedResourceIds.length, timeHorizon]
  )
  const pendingRandomizedRows = useMemo(
    () => Number(randomizerPreview?.row_count || 0),
    [randomizerPreview]
  )

  const lifecycleState = useMemo<ScenarioLifecycleState>(() => {
    if (isRunningScenario) return 'running'
    if (isReverting) return 'reverting'
    if (isVerifying) return 'verifying'

    const status = String(selectedScenario?.status || '').toLowerCase()
    if (status === 'failed') return 'failed'
    if (status === 'completed') return 'completed'
    if (status === 'finalized') return 'finalized'
    if (persistedDemandRows > 0) return 'ready'
    return 'draft'
  }, [isRunningScenario, isReverting, isVerifying, selectedScenario, persistedDemandRows])

  const canRunScenario = useMemo(() => {
    if (!selectedScenarioId) return false
    if (busy || isRunningScenario || isReverting || isVerifying) return false
    if (persistedDemandRows <= 0) return false
    return ['ready', 'completed', 'failed'].includes(lifecycleState)
  }, [selectedScenarioId, busy, isRunningScenario, isReverting, isVerifying, persistedDemandRows, lifecycleState])

  const isBlockingOverlayVisible = isRunningScenario || isReverting

  const sharedScope = useMemo(() => {
    const alloc = selectedRunSummary?.source_scope_breakdown?.allocations
    return {
      district: Number(alloc?.district || 0),
      state: Number(alloc?.state || 0),
      neighbor: Number(alloc?.neighbor_state || 0),
      national: Number(alloc?.national || 0),
    }
  }, [selectedRunSummary])

  const sharedFlags = useMemo(
    () => selectedRunSummary?.fairness?.fairness_flags || [],
    [selectedRunSummary]
  )

  const pendingAgentCount = useMemo(
    () => agentRows.filter(r => String(r.status || '').toLowerCase() === 'pending').length,
    [agentRows]
  )

  const districtsInState = useMemo(() => {
    if (!selectedStateCode) return []
    return districts.filter(d => String(d.state_code) === String(selectedStateCode))
  }, [districts, selectedStateCode])

  const selectedDistrictRows = useMemo(
    () => districts.filter(d => selectedDistrictCodes.includes(String(d.district_code))),
    [districts, selectedDistrictCodes]
  )

  const selectedResourceRows = useMemo(
    () => resources.filter(r => selectedResourceIds.includes(String(r.resource_id))),
    [resources, selectedResourceIds]
  )

  useEffect(() => {
    const nextMap: Record<string, number> = {}
    for (const resourceId of selectedResourceIds) {
      nextMap[resourceId] = resourceDemandMap[resourceId] ?? Number(baseDemandQty) * Number(demandMultiplier)
    }
    setResourceDemandMap(nextMap)
  }, [selectedResourceIds, baseDemandQty, demandMultiplier])

  async function createScenario() {
    if (!token || !newScenarioName.trim()) return
    setBusy(true)
    setError('')
    try {
      const created = await apiFetch<ScenarioRow>(BACKEND_PATHS.adminScenarios, {
        method: 'POST',
        body: JSON.stringify({ name: newScenarioName.trim() }),
      })
      setNewScenarioName('')
      await reloadScenarios()
      setSelectedScenarioId(created.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create scenario')
    } finally {
      setBusy(false)
    }
  }

  async function addDemandBatch() {
    if (!token || !selectedScenarioId) return
    if (selectedDistrictCodes.length === 0 || selectedResourceIds.length === 0) {
      setError('Select at least one district and one resource')
      return
    }

    setBusy(true)
    setError('')
    try {
      const rows: Array<{
        district_code: string
        state_code: string
        resource_id: string
        time: number
        quantity: number
        priority: number
        urgency: number
        time_index: number
      }> = []

      for (const districtCode of selectedDistrictCodes) {
        const district = districts.find(d => String(d.district_code) === String(districtCode))
        const stateCode = district?.state_code || selectedStateCode
        for (const resourceId of selectedResourceIds) {
          const requestedQty = Number(resourceDemandMap[resourceId] ?? (Number(baseDemandQty || 0) * Number(demandMultiplier || 0)))
          const horizon = clampPositiveInt(timeHorizon, 1)
          for (let t = 1; t <= horizon; t++) {
            rows.push({
              district_code: districtCode,
              state_code: String(stateCode),
              resource_id: resourceId,
              time: t,
              quantity: requestedQty,
              priority: clampRangeInt(manualPriority, 1, 5, 3),
              urgency: clampRangeInt(manualUrgency, 1, 5, 3),
              time_index: clampNonNegativeFloat(manualTimeIndex, 1),
            })
          }
        }
      }

      await apiFetch(BACKEND_PATHS.adminScenarioDemandBatch(selectedScenarioId), {
        method: 'POST',
        body: JSON.stringify({ rows, scenario_type: scenarioType }),
      })

      await reloadScenarios()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add demand batch')
    } finally {
      setBusy(false)
    }
  }

  async function addStateStock() {
    if (!token || !selectedScenarioId) return
    setBusy(true)
    setError('')
    try {
      await apiFetch(`${BACKEND_PATHS.adminScenarios}/${selectedScenarioId}/set-state-stock`, {
        method: 'POST',
        body: JSON.stringify(stateStockDraft),
      })
      await reloadScenarios()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add state stock override')
    } finally {
      setBusy(false)
    }
  }

  async function addNationalStock() {
    if (!token || !selectedScenarioId) return
    setBusy(true)
    setError('')
    try {
      await apiFetch(`${BACKEND_PATHS.adminScenarios}/${selectedScenarioId}/set-national-stock`, {
        method: 'POST',
        body: JSON.stringify(nationalStockDraft),
      })
      await reloadScenarios()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add national stock override')
    } finally {
      setBusy(false)
    }
  }

  async function runScenario() {
    if (!token || !selectedScenarioId || !canRunScenario) return
    setIsRunningScenario(true)
    setBusy(true)
    setError('')
    setToast(null)
    try {
      await apiFetch(`${BACKEND_PATHS.adminScenarios}/${selectedScenarioId}/run`, {
        method: 'POST',
        body: JSON.stringify({ scope_mode: 'focused' }),
      })
      await reloadScenarios()
      await reloadScenarioArtifacts(selectedScenarioId)
      setToast({ kind: 'success', message: 'Scenario run completed successfully.' })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run scenario')
      setToast({ kind: 'error', message: 'Scenario run failed.' })
    } finally {
      setBusy(false)
      setIsRunningScenario(false)
    }
  }

  async function finalizeSelectedScenario() {
    if (!selectedScenarioId) return
    setBusy(true)
    setError('')
    try {
      await apiFetch(BACKEND_PATHS.adminScenarioFinalize(selectedScenarioId), {
        method: 'POST',
        body: JSON.stringify({}),
      })
      await reloadScenarios()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to finalize scenario')
    } finally {
      setBusy(false)
    }
  }

  async function cloneSelectedScenario() {
    if (!selectedScenarioId) return
    setBusy(true)
    setError('')
    try {
      const clone = await apiFetch<{ cloned_scenario_id: number }>(BACKEND_PATHS.adminScenarioClone(selectedScenarioId), {
        method: 'POST',
        body: JSON.stringify({ name: `${selectedScenario?.name || 'Scenario'} clone` }),
      })
      await reloadScenarios()
      if (clone?.cloned_scenario_id) {
        setSelectedScenarioId(Number(clone.cloned_scenario_id))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to clone scenario')
    } finally {
      setBusy(false)
    }
  }

  function clampPositiveInt(value: number | '', fallback: number) {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) return Math.max(1, Math.trunc(fallback || 1))
    return Math.max(1, Math.trunc(parsed))
  }

  function clampRangeInt(value: number | '', min: number, max: number, fallback: number) {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) return fallback
    return Math.max(min, Math.min(max, Math.trunc(parsed)))
  }

  function clampNonNegativeFloat(value: number | '', fallback: number) {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) return fallback
    return Math.max(0, parsed)
  }

  function randomizerPayload() {
    return {
      preset: randomPreset,
      seed: (randomSeed === '' ? undefined : Number(randomSeed)),
      time_horizon: clampPositiveInt(timeHorizon, 1),
      stress_mode: randomStressMode,
      state_codes: selectedStateCode ? [selectedStateCode] : [],
      district_codes: selectedDistrictCodes,
      resource_ids: selectedResourceIds,
      quantity_mode: randomStockAwareDistribution ? 'stock_aware' : 'fixed',
      stock_aware_distribution: randomStockAwareDistribution,
      replace_existing: false,
    }
  }

  async function previewRandomizer() {
    if (!selectedScenarioId) return
    setIsPreviewing(true)
    setBusy(true)
    setError('')
    setToast(null)
    try {
      const preview = await apiFetch<RandomizerPreview>(BACKEND_PATHS.adminScenarioRandomizerPreview(selectedScenarioId), {
        method: 'POST',
        body: JSON.stringify(randomizerPayload()),
      })
      setRandomizerPreview(preview)
      setToast({ kind: 'info', message: `Preview generated: ${Number(preview?.row_count || 0)} rows.` })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to preview randomizer')
      setToast({ kind: 'error', message: 'Randomizer preview failed.' })
    } finally {
      setBusy(false)
      setIsPreviewing(false)
    }
  }

  async function applyRandomizer() {
    if (!selectedScenarioId) return
    const shouldProceed = window.confirm('Apply randomizer and add to existing scenario demand rows?')
    if (!shouldProceed) return
    setIsApplyingRandomizer(true)
    setBusy(true)
    setError('')
    setToast(null)
    try {
      await apiFetch(BACKEND_PATHS.adminScenarioRandomizerApply(selectedScenarioId), {
        method: 'POST',
        body: JSON.stringify(randomizerPayload()),
      })
      await reloadScenarios()
      const preview = await apiFetch<RandomizerPreview>(BACKEND_PATHS.adminScenarioRandomizerPreview(selectedScenarioId), {
        method: 'POST',
        body: JSON.stringify(randomizerPayload()),
      })
      setRandomizerPreview(preview)
      setToast({ kind: 'success', message: 'Randomizer applied successfully.' })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to apply randomizer')
      setToast({ kind: 'error', message: 'Randomizer apply failed.' })
    } finally {
      setBusy(false)
      setIsApplyingRandomizer(false)
    }
  }

  async function revertScenarioEffects() {
    if (!selectedScenarioId) return
    setIsReverting(true)
    setBusy(true)
    setError('')
    setToast(null)
    try {
      await apiFetch(BACKEND_PATHS.adminScenarioRevertEffects(selectedScenarioId), {
        method: 'POST',
        body: JSON.stringify({}),
      })
      await verifyRevertScenarioEffects()
      setToast({ kind: 'success', message: 'Scenario effects reverted.' })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to revert scenario effects')
      setToast({ kind: 'error', message: 'Revert operation failed.' })
    } finally {
      setBusy(false)
      setIsReverting(false)
    }
  }

  async function verifyRevertScenarioEffects() {
    if (!selectedScenarioId) return
    setIsVerifying(true)
    setBusy(true)
    setError('')
    try {
      const verify = await apiFetch<RevertVerify>(BACKEND_PATHS.adminScenarioRevertVerify(selectedScenarioId))
      setRevertVerify(verify)
      setToast({ kind: verify.ok ? 'success' : 'info', message: verify.ok ? 'Revert balance verified.' : 'Revert balance check found a mismatch.' })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to verify revert effects')
      setToast({ kind: 'error', message: 'Revert verification failed.' })
    } finally {
      setBusy(false)
      setIsVerifying(false)
    }
  }

  async function loadRunSummary(runId: number) {
    if (!selectedScenarioId) return
    setError('')
    try {
      const summary = await apiFetch<ScenarioRunSummary>(
        BACKEND_PATHS.adminScenarioRunSummary(selectedScenarioId, runId)
      )
      setSelectedRunSummary(summary)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load run details')
      setSelectedRunSummary(null)
    }
  }

  function addDistrictSelection(code: string) {
    if (!code) return
    setSelectedDistrictCodes(prev => (prev.includes(code) ? prev : [...prev, code]))
  }

  function removeDistrictSelection(code: string) {
    setSelectedDistrictCodes(prev => prev.filter(d => d !== code))
  }

  function addAllDistrictsInState() {
    const allCodes = districtsInState.map(d => String(d.district_code))
    setSelectedDistrictCodes(prev => Array.from(new Set([...prev, ...allCodes])))
  }

  function clearDistrictSelection() {
    setSelectedDistrictCodes([])
  }

  async function decideAgentRecommendation(recommendationId: number, decision: 'approved' | 'rejected') {
    setAgentBusyId(recommendationId)
    setError('')
    try {
      await apiFetch(BACKEND_PATHS.adminAgentRecommendationDecision(recommendationId), {
        method: 'POST',
        body: JSON.stringify({ decision }),
      })
      await loadAgentRecommendations()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to decide recommendation')
    } finally {
      setAgentBusyId(null)
    }
  }

  return (
    <div>
      {isBlockingOverlayVisible && (
        <div className="fixed inset-0 z-50 bg-black/25 backdrop-blur-[1px] flex items-center justify-center">
          <div className="bg-white border rounded px-4 py-3 text-sm shadow-sm">
            {isRunningScenario ? 'Scenario run in progress...' : 'Reverting scenario effects...'}
          </div>
        </div>
      )}

      <div className="mb-3 text-sm flex items-center gap-3">
        <a href="/admin/system" className="text-blue-700 underline">Admin System</a>
        <a href="/admin/scenarios" className="text-blue-700 underline">Scenario Studio</a>
      </div>

      <div className="mb-4 flex flex-wrap gap-2 border-b pb-2">
        <button className={`px-3 py-1 rounded border text-sm ${activeTab === 'system-health' ? 'bg-slate-800 text-white border-slate-800' : 'bg-white'}`} onClick={() => setActiveTab('system-health')}>System Health</button>
        <button className={`px-3 py-1 rounded border text-sm ${activeTab === 'solver-runs' ? 'bg-slate-800 text-white border-slate-800' : 'bg-white'}`} onClick={() => setActiveTab('solver-runs')}>Solver Runs</button>
        <button className={`px-3 py-1 rounded border text-sm ${activeTab === 'neural' ? 'bg-slate-800 text-white border-slate-800' : 'bg-white'}`} onClick={() => setActiveTab('neural')}>Neural Controller Status</button>
        <button className={`px-3 py-1 rounded border text-sm ${activeTab === 'agent' ? 'bg-slate-800 text-white border-slate-800' : 'bg-white'}`} onClick={() => setActiveTab('agent')}>Agent Findings</button>
        <button className={`px-3 py-1 rounded border text-sm ${activeTab === 'audit' ? 'bg-slate-800 text-white border-slate-800' : 'bg-white'}`} onClick={() => setActiveTab('audit')}>Audit Logs</button>
      </div>

      <div className="mb-4 border rounded bg-slate-50 p-3 text-xs">
        <div className="font-semibold mb-2">Global Operational Context (Cross-Tab)</div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <div>Scenario: {selectedScenarioId || '—'}</div>
          <div>Latest Run: {selectedRunSummary?.run_id || '—'}</div>
          <div>Unmet: {selectedRunSummary ? Number(selectedRunSummary.totals.unmet_quantity || 0).toFixed(2) : '—'}</div>
          <div>Incident Runs: {incidentData?.incident_count ?? 0}</div>
          <div>Pending Agent: {pendingAgentCount}</div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
          <div>District Scope: {sharedScope.district.toFixed(2)}</div>
          <div>State Scope: {sharedScope.state.toFixed(2)}</div>
          <div>Neighbor Scope: {sharedScope.neighbor.toFixed(2)}</div>
          <div>National Scope: {sharedScope.national.toFixed(2)}</div>
        </div>
        <div className={`mt-2 ${sharedFlags.length > 0 ? 'text-amber-700' : 'text-emerald-700'}`}>
          Active Flags: {sharedFlags.length > 0 ? sharedFlags.join(', ') : 'none'}
        </div>
      </div>

      {activeTab === 'system-health' && (
      <Section title="Admin Scenario Studio">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-4">
          <StatCard label="Scenarios" value={scenarios.length.toString()} />
          <StatCard label="Runs (selected)" value={scenarioRuns.length.toString()} />
          <StatCard label="Recommendations" value={analysis.recommendations.length.toString()} />
          <StatCard label="Explanations" value={analysis.explanations.length.toString()} />
          <StatCard label="Incident Runs" value={String(incidentData?.incident_count || 0)} />
          <StatCard label="Fairness Flags" value={String(sharedFlags.length)} />
        </div>

        {error && (
          <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">
            {error}
          </div>
        )}

        {toast && (
          <div className={`mb-3 text-sm border rounded px-2 py-1 ${toast.kind === 'success' ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : toast.kind === 'error' ? 'text-red-700 bg-red-50 border-red-200' : 'text-blue-700 bg-blue-50 border-blue-200'}`}>
            {toast.message}
          </div>
        )}

        <div className="flex gap-2 mb-4">
          <input
            value={newScenarioName}
            onChange={e => setNewScenarioName(e.target.value)}
            className="border rounded px-3 py-2 w-80"
            placeholder="New scenario name"
          />
          <button
            disabled={busy}
            onClick={createScenario}
            className="px-4 py-2 bg-blue-600 text-white rounded"
          >
            Create Scenario
          </button>
        </div>

        <div className="mb-4">
          <label className="text-sm mr-2">Selected Scenario:</label>
          <select
            value={selectedScenarioId ?? ''}
            onChange={e => setSelectedScenarioId(Number(e.target.value))}
            className="border rounded px-2 py-1"
          >
            <option value="">Select scenario</option>
            {scenarios.map(s => (
              <option key={s.id} value={s.id}>
                #{s.id} {s.name}
              </option>
            ))}
          </select>
        </div>

        {selectedScenario && (
          <div className="text-sm text-slate-600 mb-4">
            Status: <b>{selectedScenario.status || 'created'}</b> | Demand rows: {selectedScenario.demand_rows || 0} | State stock rows: {selectedScenario.state_stock_rows || 0} | National stock rows: {selectedScenario.national_stock_rows || 0}
          </div>
        )}

        <div className="border rounded p-3 mb-4 bg-white text-sm">
          <div className="font-semibold mb-1">Lifecycle State</div>
          <div>Current: <b>{lifecycleState}</b></div>
          <div>Pending Demand Rows: {pendingManualDemandRows}</div>
          <div>Pending Randomizer Rows: {pendingRandomizedRows}</div>
          <div>Persisted Demand Rows: {persistedDemandRows}</div>
          <div className="text-xs text-slate-600 mt-1">Run is enabled only when persisted demand rows are available and lifecycle is ready/completed/failed.</div>
        </div>

        <div className="border rounded p-3 mb-4 bg-slate-50">
          <div className="font-semibold mb-2">Scenario Lifecycle Controls</div>
          <div className="flex flex-wrap gap-2">
            <button disabled={!canRunScenario} onClick={runScenario} className="px-3 py-1 bg-green-700 text-white rounded disabled:opacity-60">
              {isRunningScenario ? 'Working...' : 'Run Scenario'}
            </button>
            <button disabled={!selectedScenarioId || busy || isRunningScenario || isReverting || isVerifying} onClick={finalizeSelectedScenario} className="px-3 py-1 bg-slate-700 text-white rounded disabled:opacity-60">
              Finalize Scenario
            </button>
            <button disabled={!selectedScenarioId || busy || isRunningScenario || isReverting || isVerifying} onClick={cloneSelectedScenario} className="px-3 py-1 border rounded disabled:opacity-60">
              Clone as New
            </button>
            <button disabled={!selectedScenarioId || busy || isRunningScenario || isReverting} onClick={revertScenarioEffects} className="px-3 py-1 bg-amber-700 text-white rounded disabled:opacity-60">
              {isReverting ? 'Working...' : 'Revert Scenario Effects'}
            </button>
            <button disabled={!selectedScenarioId || busy || isRunningScenario || isReverting || isVerifying} onClick={verifyRevertScenarioEffects} className="px-3 py-1 border rounded disabled:opacity-60">
              {isVerifying ? 'Working...' : 'Verify Revert Balance'}
            </button>
          </div>
          {revertVerify && (
            <div className={`mt-2 text-xs ${revertVerify.ok ? 'text-emerald-700' : 'text-rose-700'}`}>
              Revert Verify: debit={revertVerify.debit_total.toFixed(2)} revert={revertVerify.revert_total.toFixed(2)} net={revertVerify.net_total.toFixed(2)} ({revertVerify.ok ? 'PASS' : 'FAIL'})
            </div>
          )}
        </div>

        <div className="border rounded p-3 mb-4 bg-slate-50">
          <div className="font-semibold mb-2">Demand Modeling Mode</div>
          <label className="mr-4 text-sm">
            <input
              type="radio"
              className="mr-1"
              checked={modelingMode === 'manual'}
              onChange={() => setModelingMode('manual')}
            />
            Manual
          </label>
          <label className="text-sm">
            <input
              type="radio"
              className="mr-1"
              checked={modelingMode === 'guided_random'}
              onChange={() => setModelingMode('guided_random')}
            />
            Guided Random
          </label>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div className="border rounded p-3 space-y-2">
            <h3 className="font-semibold">Hierarchical Selector</h3>
            <div className="text-sm">Country: INDIA</div>
            <div>
              <label className="text-xs block">State</label>
              <select
                value={selectedStateCode}
                onChange={e => {
                  setSelectedStateCode(e.target.value)
                  setStateStockDraft(prev => ({ ...prev, state_code: e.target.value }))
                }}
                className="border rounded px-2 py-1 w-full"
                disabled={loadingMeta}
              >
                <option value="">Select state</option>
                {states.map(s => (
                  <option key={s.state_code} value={s.state_code}>
                    {s.state_code} - {s.state_name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs block">District (Add one at a time)</label>
              <select
                className="border rounded px-2 py-1 w-full"
                onChange={e => addDistrictSelection(e.target.value)}
                value=""
                disabled={!selectedStateCode}
              >
                <option value="">Select district</option>
                {districtsInState.map(d => (
                  <option key={d.district_code} value={d.district_code}>
                    {d.district_code} - {d.district_name || d.district_code}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex gap-2">
              <button onClick={addAllDistrictsInState} className="px-2 py-1 rounded bg-slate-700 text-white" disabled={!selectedStateCode}>Add All Districts</button>
              <button onClick={clearDistrictSelection} className="px-2 py-1 rounded border">Clear Selection</button>
            </div>

            <div className="max-h-32 overflow-auto border rounded p-2 text-sm">
              {selectedDistrictRows.length === 0 && <div className="text-slate-500">No districts selected.</div>}
              {selectedDistrictRows.map(d => (
                <div key={d.district_code} className="flex items-center justify-between">
                  <span>{d.district_code} - {d.district_name || d.district_code}</span>
                  <button className="text-red-600" onClick={() => removeDistrictSelection(String(d.district_code))}>remove</button>
                </div>
              ))}
            </div>
          </div>

          <div className="border rounded p-3 space-y-2">
            <h3 className="font-semibold">Simulation Controls</h3>
            {modelingMode !== 'manual' && (
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                Manual controls are disabled while Guided Random mode is active.
              </div>
            )}

            <div>
              <label className="text-xs block">Scenario Type</label>
              <select value={scenarioType} onChange={e => setScenarioType(e.target.value)} className="border rounded px-2 py-1 w-full">
                <option value="multi_district_intra_state">Multi District Intra State</option>
                <option value="single_district_shock">Single District Shock</option>
                <option value="state_collapse">State Collapse</option>
                <option value="national_scarcity">National Scarcity</option>
              </select>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-xs block">Time Horizon</label>
                <input type="number" min={1} value={timeHorizon} onChange={e => setTimeHorizon(e.target.value === '' ? '' : clampPositiveInt(Number(e.target.value), 1))} className="border rounded px-2 py-1 w-full" />
              </div>
              <div>
                <label className="text-xs block">Base Demand</label>
                <input type="number" min={1} value={baseDemandQty} onChange={e => setBaseDemandQty(e.target.value === '' ? '' : Number(e.target.value))} className="border rounded px-2 py-1 w-full" disabled={modelingMode !== 'manual'} />
              </div>
              <div>
                <label className="text-xs block">Demand Multiplier</label>
                <input type="number" min={0.1} step={0.1} value={demandMultiplier} onChange={e => setDemandMultiplier(e.target.value === '' ? '' : Number(e.target.value))} className="border rounded px-2 py-1 w-full" disabled={modelingMode !== 'manual'} />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-xs block">Manual Priority (1-5)</label>
                <input type="number" min={1} max={5} value={manualPriority} onChange={e => setManualPriority(e.target.value === '' ? '' : clampRangeInt(Number(e.target.value), 1, 5, 3))} className="border rounded px-2 py-1 w-full" disabled={modelingMode !== 'manual'} />
              </div>
              <div>
                <label className="text-xs block">Manual Urgency (1-5)</label>
                <input type="number" min={1} max={5} value={manualUrgency} onChange={e => setManualUrgency(e.target.value === '' ? '' : clampRangeInt(Number(e.target.value), 1, 5, 3))} className="border rounded px-2 py-1 w-full" disabled={modelingMode !== 'manual'} />
              </div>
              <div>
                <label className="text-xs block">Manual Time Index</label>
                <input type="number" min={0} step={0.1} value={manualTimeIndex} onChange={e => setManualTimeIndex(e.target.value === '' ? '' : clampNonNegativeFloat(Number(e.target.value), 0))} className="border rounded px-2 py-1 w-full" disabled={modelingMode !== 'manual'} />
              </div>
            </div>

            <div>
              <label className="text-xs block">Resource Types (multi-select)</label>
              <div className="max-h-36 overflow-auto border rounded p-2 text-sm">
                {resources.map(r => {
                  const checked = selectedResourceIds.includes(String(r.resource_id))
                  return (
                    <label key={r.resource_id} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={e => {
                          if (e.target.checked) {
                            setSelectedResourceIds(prev => [...prev, String(r.resource_id)])
                          } else {
                            setSelectedResourceIds(prev => prev.filter(x => x !== String(r.resource_id)))
                          }
                        }}
                      />
                      <span>{r.resource_id} - {r.resource_name}</span>
                    </label>
                  )
                })}
              </div>
            </div>

            {selectedResourceRows.length > 0 && (
              <div>
                <label className="text-xs block">Demand by Resource</label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-36 overflow-auto border rounded p-2 text-sm">
                  {selectedResourceRows.map(r => (
                    <label key={`demand_${r.resource_id}`} className="flex items-center justify-between gap-2">
                      <span>{r.resource_id}</span>
                      <input
                        type="number"
                        min={1}
                        disabled={modelingMode !== 'manual'}
                        value={resourceDemandMap[String(r.resource_id)] ?? Number(baseDemandQty || 0) * Number(demandMultiplier || 0)}
                        onChange={e =>
                          setResourceDemandMap(prev => ({
                            ...prev,
                            [String(r.resource_id)]: Number(e.target.value),
                          }))
                        }
                        className="border rounded px-2 py-1 w-28"
                      />
                    </label>
                  ))}
                </div>
              </div>
            )}

            <button disabled={!selectedScenarioId || busy || modelingMode !== 'manual'} onClick={addDemandBatch} className="px-3 py-1 bg-slate-700 text-white rounded disabled:opacity-60">
              Add Demand Batch
            </button>
          </div>
        </div>

        <div className="border rounded p-3 mb-4 space-y-3">
          <h3 className="font-semibold">Guided Randomizer (Realistic, Rule-Based)</h3>
          {modelingMode !== 'guided_random' && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              Guided Randomizer is disabled while Manual mode is active.
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-sm">
            <label className="flex flex-col gap-1">
              <span className="text-xs">Demand Level</span>
              <select value={randomPreset} onChange={e => setRandomPreset(e.target.value as any)} className="border rounded px-2 py-1" disabled={modelingMode !== 'guided_random'}>
                <option value="extremely_low">Extremely Low (0.20x supply)</option>
                <option value="low">low</option>
                <option value="medium_low">Medium Low (0.70x supply)</option>
                <option value="medium">medium</option>
                <option value="medium_high">Medium High (1.25x supply)</option>
                <option value="high">high</option>
                <option value="extremely_high">Extremely High (1.79x supply)</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs">Seed</span>
              <input type="number" value={randomSeed} onChange={e => setRandomSeed(e.target.value === '' ? '' : Number(e.target.value))} className="border rounded px-2 py-1" disabled={modelingMode !== 'guided_random'} />
            </label>
            <label className="flex items-center gap-2 mt-5">
              <input type="checkbox" checked={randomStressMode} onChange={e => setRandomStressMode(e.target.checked)} disabled={modelingMode !== 'guided_random'} />
              <span className="text-xs">Stress mode</span>
            </label>
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                checked={randomStockAwareDistribution}
                onChange={() => setRandomStockAwareDistribution(true)}
                disabled={modelingMode !== 'guided_random'}
              />
              Stock-aware distribution
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                checked={!randomStockAwareDistribution}
                onChange={() => setRandomStockAwareDistribution(false)}
                disabled={modelingMode !== 'guided_random'}
              />
              Fixed manual quantities
            </label>
          </div>
          <div className="flex gap-2">
            <button disabled={!selectedScenarioId || busy || modelingMode !== 'guided_random'} onClick={previewRandomizer} className="px-3 py-1 border rounded disabled:opacity-60">
              {isPreviewing ? 'Working...' : 'Preview Randomizer'}
            </button>
            <button disabled={!selectedScenarioId || busy || modelingMode !== 'guided_random'} onClick={applyRandomizer} className="px-3 py-1 bg-indigo-700 text-white rounded disabled:opacity-60">
              {isApplyingRandomizer ? 'Working...' : 'Apply Randomizer'}
            </button>
          </div>

          {randomizerPreview && (
            <div className={`text-xs border rounded p-2 ${isPreviewing ? 'bg-blue-50 border-blue-200' : 'bg-slate-50'}`}>
              <div>Preview rows={randomizerPreview.row_count} districts={randomizerPreview.district_count} resources={randomizerPreview.resource_count} total_qty={Number(randomizerPreview.total_quantity || 0).toFixed(2)}</div>
              <div>Total available supply={Number(randomizerPreview.total_available_supply || 0).toFixed(2)} | Total generated demand={Number(randomizerPreview.total_generated_demand || 0).toFixed(2)}</div>
              <div>Demand/Supply ratio={randomizerPreview.demand_supply_ratio ?? 'n/a'} | Expected shortage={Number(randomizerPreview.expected_shortage_estimate || 0).toFixed(2)} | Intensity ratio={Number(randomizerPreview.intensity_ratio || 0).toFixed(2)}</div>
              <div>Mode={randomizerPreview.quantity_mode || (randomStockAwareDistribution ? 'stock_aware' : 'fixed')} | Scope districts={randomizerPreview.district_count} | Scope resources={randomizerPreview.resource_count}</div>
              <div>Selected districts={(randomizerPreview.selected_districts || []).join(', ') || '—'}</div>
              <div>Selected resources={(randomizerPreview.selected_resources || []).join(', ') || '—'}</div>
              <div>Stock-backed rows={Number(randomizerPreview.stock_backed_rows || 0)} | Zero-stock rows={Number(randomizerPreview.zero_stock_rows || 0)} | Avg available stock={Number(randomizerPreview.avg_available_stock || 0).toFixed(2)}</div>
              <div>Randomizer Priority/TimeIndex: avg_priority={Number(randomizerPreview.avg_priority || 0).toFixed(2)} avg_time_index={Number(randomizerPreview.avg_time_index || 0).toFixed(2)}</div>
              <div>Apply Mode=additive | Existing rows are preserved and matching slots are incremented.</div>
              <div>Live baseline run={randomizerPreview.latest_live_run_id ?? 'none'} preset={randomizerPreview.preset}</div>
              <div className={randomizerPreview.guardrail_warnings.length > 0 ? 'text-amber-700' : 'text-emerald-700'}>
                Guardrails: {randomizerPreview.guardrail_warnings.length > 0 ? `${randomizerPreview.guardrail_warnings.length} clamp warning(s)` : 'no warnings'}
              </div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div className="border rounded p-3 space-y-2">
            <h3 className="font-semibold">State Stock Override</h3>
            <input className="border rounded px-2 py-1 w-full" placeholder="state_code" value={stateStockDraft.state_code} onChange={e => setStateStockDraft({ ...stateStockDraft, state_code: e.target.value })} />
            <input className="border rounded px-2 py-1 w-full" placeholder="resource_id" value={stateStockDraft.resource_id} onChange={e => setStateStockDraft({ ...stateStockDraft, resource_id: e.target.value })} />
            <input className="border rounded px-2 py-1 w-full" type="number" placeholder="quantity" value={stateStockDraft.quantity} onChange={e => setStateStockDraft({ ...stateStockDraft, quantity: Number(e.target.value) })} />
            <button disabled={!selectedScenarioId || busy} onClick={addStateStock} className="px-3 py-1 bg-slate-700 text-white rounded">Add State Stock</button>
          </div>

          <div className="border rounded p-3 space-y-2">
            <h3 className="font-semibold">National Stock Override</h3>
            <input className="border rounded px-2 py-1 w-full" placeholder="resource_id" value={nationalStockDraft.resource_id} onChange={e => setNationalStockDraft({ ...nationalStockDraft, resource_id: e.target.value })} />
            <input className="border rounded px-2 py-1 w-full" type="number" placeholder="quantity" value={nationalStockDraft.quantity} onChange={e => setNationalStockDraft({ ...nationalStockDraft, quantity: Number(e.target.value) })} />
            <button disabled={!selectedScenarioId || busy} onClick={addNationalStock} className="px-3 py-1 bg-slate-700 text-white rounded">Add National Stock</button>
          </div>
        </div>

        <div className="border rounded p-3 mb-4 text-sm bg-slate-50">
          <div className="font-semibold mb-1">Preview</div>
          <div>Scenario Type: {scenarioType}</div>
          <div>Modeling Mode: {modelingMode === 'manual' ? 'Manual' : 'Guided Random'}</div>
          <div>State: {selectedStateCode || '—'}</div>
          <div>Districts Selected: {selectedDistrictCodes.length}</div>
          <div>District IDs: {selectedDistrictCodes.length > 0 ? selectedDistrictCodes.slice(0, 12).join(', ') : '—'}</div>
          <div>Resources Selected: {selectedResourceRows.length}</div>
          <div>Resource IDs: {selectedResourceIds.length > 0 ? selectedResourceIds.slice(0, 12).join(', ') : '—'}</div>
          <div>Time Horizon: {timeHorizon}</div>
          <div>Per-slot Base Quantity: {Number(baseDemandQty || 0) * Number(demandMultiplier || 0)}</div>
          <div>Total Demand Rows To Add: {selectedDistrictCodes.length * selectedResourceRows.length * clampPositiveInt(timeHorizon, 1)}</div>
        </div>

        <div className="text-xs text-slate-600">
          Scenario controls are isolated from live dashboards; use Revert + Verify after test cycles to restore pool balance.
        </div>
      </Section>
      )}

      {activeTab === 'agent' && (
      <Section title="Agent Recommendations">
        <div className="border rounded p-2 mb-3 text-xs bg-slate-50">
          <div className="font-semibold mb-1">Agent Context</div>
          <div>Latest Run: {selectedRunSummary?.run_id || '—'} | Incidents: {incidentData?.incident_count || 0} | Pending: {pendingAgentCount}</div>
          <div className={`${sharedFlags.length ? 'text-amber-700' : 'text-emerald-700'}`}>
            Shared Flags: {sharedFlags.length ? sharedFlags.join(', ') : 'none'}
          </div>
        </div>

        {agentRows.length === 0 && <EmptyState message="No agent recommendations yet." />}

        {agentRows.length > 0 && (
          <div className="overflow-x-auto border rounded">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 text-left">
                <tr>
                  <th className="p-2">Entity</th>
                  <th className="p-2">Finding</th>
                  <th className="p-2">Recommendation</th>
                  <th className="p-2">Severity</th>
                  <th className="p-2">Evidence</th>
                  <th className="p-2">Status</th>
                  <th className="p-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {agentRows.map((row) => (
                  <tr key={`agent_${row.id}`} className="border-t align-top">
                    <td className="p-2">{row.entity_type || '—'}:{row.entity_id || '—'}</td>
                    <td className="p-2">{row.finding_type || '—'}</td>
                    <td className="p-2">{row.recommendation_type || '—'}<div className="text-xs text-slate-600">{row.message || ''}</div></td>
                    <td className="p-2">{row.severity || 'low'}</td>
                    <td className="p-2 max-w-sm"><pre className="text-xs whitespace-pre-wrap">{JSON.stringify(row.evidence_json || {}, null, 2)}</pre></td>
                    <td className="p-2">{row.status}</td>
                    <td className="p-2">
                      {row.status === 'pending' ? (
                        <div className="flex gap-2">
                          <button
                            className="px-2 py-1 rounded bg-emerald-700 text-white disabled:opacity-60"
                            disabled={agentBusyId === row.id}
                            onClick={() => decideAgentRecommendation(row.id, 'approved')}
                          >
                            Approve
                          </button>
                          <button
                            className="px-2 py-1 rounded bg-rose-700 text-white disabled:opacity-60"
                            disabled={agentBusyId === row.id}
                            onClick={() => decideAgentRecommendation(row.id, 'rejected')}
                          >
                            Reject
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500">No actions</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      )}

      {activeTab === 'solver-runs' && (
      <Section title="Scenario Run Logs">
        {scenarioRuns.length === 0 && (
          <EmptyState message="No solver runs for selected scenario yet." />
        )}

        {incidentData && incidentData.incidents.length > 0 && (
          <div className="border rounded p-3 mb-3 bg-amber-50 text-sm">
            <div className="font-semibold mb-2">Incident Explorer (High-Signal Runs)</div>
            <div className="overflow-x-auto border rounded bg-white">
              <table className="w-full text-xs">
                <thead className="bg-slate-100 text-left">
                  <tr>
                    <th className="p-2">Run</th>
                    <th className="p-2">Reasons</th>
                    <th className="p-2">Unmet</th>
                    <th className="p-2">Districts Unmet</th>
                    <th className="p-2">Early/Late</th>
                    <th className="p-2">Neighbor Scope</th>
                    <th className="p-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {incidentData.incidents.slice(0, 30).map((inc, idx) => (
                    <tr key={`incident_${inc.run_id}_${idx}`} className="border-t align-top">
                      <td className="p-2">#{inc.run_id}</td>
                      <td className="p-2">{(inc.reasons || []).join(', ')}</td>
                      <td className="p-2">{Number(inc.unmet_quantity || 0).toFixed(2)}</td>
                      <td className="p-2">{inc.districts_unmet}</td>
                      <td className="p-2">{inc.time_service_early_avg == null ? 'n/a' : Number(inc.time_service_early_avg).toFixed(4)} / {inc.time_service_late_avg == null ? 'n/a' : Number(inc.time_service_late_avg).toFixed(4)}</td>
                      <td className="p-2">{Number((inc.scope_allocations || {}).neighbor_state || 0).toFixed(2)}</td>
                      <td className="p-2">
                        <button className="px-2 py-1 rounded border" onClick={() => loadRunSummary(inc.run_id)}>
                          Inspect
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {scenarioRuns.map(run => (
          <div key={run.id} className="border rounded p-3 mb-2 text-sm">
            <div><b>Run #{run.id}</b></div>
            <div>Status: {run.status}</div>
            <div>Mode: {run.mode}</div>
            <div>Started: {run.started_at || '—'}</div>
            <div className="mt-2 flex gap-2">
              <button
                className="px-3 py-1 rounded border"
                onClick={() => loadRunSummary(run.id)}
              >
                Quick View
              </button>
              <Link
                to={`/admin/scenarios/${selectedScenarioId}/runs/${run.id}`}
                className="px-3 py-1 rounded border text-blue-700"
              >
                Open Full Details
              </Link>
            </div>
          </div>
        ))}

        {selectedRunSummary && (
          <div className="border rounded p-3 text-sm bg-slate-50">
            <div className="font-semibold mb-2">Run #{selectedRunSummary.run_id} Details</div>
            <div>Allocated Quantity: {selectedRunSummary.totals.allocated_quantity.toFixed(2)}</div>
            <div>Unmet Quantity: {selectedRunSummary.totals.unmet_quantity.toFixed(2)}</div>
            <div>Districts Covered: {selectedRunSummary.totals.districts_covered}</div>
            <div>Districts Met: {selectedRunSummary.totals.districts_met}</div>
            <div>Districts Unmet: {selectedRunSummary.totals.districts_unmet}</div>

            {selectedRunSummary.escalation_status && (
              <div className="mt-2 border rounded p-2 bg-white text-xs">
                <div className="font-semibold mb-1">Escalation Status</div>
                <div>Mode: {selectedRunSummary.escalation_status.mode}</div>
                <div>Events Found: {selectedRunSummary.escalation_status.events_found}</div>
                <div>State Marked: {selectedRunSummary.escalation_status.state_marked}</div>
                <div>National Marked: {selectedRunSummary.escalation_status.national_marked}</div>
                <div>Neighbor Offers: created={selectedRunSummary.escalation_status.neighbor_offers_created} accepted={selectedRunSummary.escalation_status.neighbor_offers_accepted}</div>
                <div>Neighbor Accepted Qty: {Number(selectedRunSummary.escalation_status.neighbor_accepted_quantity || 0).toFixed(2)}</div>
              </div>
            )}

            <div className="mt-2 overflow-x-auto border rounded bg-white">
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
                  {selectedRunSummary.district_breakdown.slice(0, 120).map((row, idx) => (
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

            {selectedRunSummary.source_scope_breakdown && (
              <div className="mt-3 border rounded p-2 bg-white">
                <div className="font-semibold mb-1">Allocation Source Scope</div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                  <div>District: {Number(selectedRunSummary.source_scope_breakdown.allocations.district || 0).toFixed(2)} ({Number((selectedRunSummary.source_scope_breakdown.percentages.district || 0) * 100).toFixed(1)}%)</div>
                  <div>State: {Number(selectedRunSummary.source_scope_breakdown.allocations.state || 0).toFixed(2)} ({Number((selectedRunSummary.source_scope_breakdown.percentages.state || 0) * 100).toFixed(1)}%)</div>
                  <div>Neighbor: {Number(selectedRunSummary.source_scope_breakdown.allocations.neighbor_state || 0).toFixed(2)} ({Number((selectedRunSummary.source_scope_breakdown.percentages.neighbor_state || 0) * 100).toFixed(1)}%)</div>
                  <div>National: {Number(selectedRunSummary.source_scope_breakdown.allocations.national || 0).toFixed(2)} ({Number((selectedRunSummary.source_scope_breakdown.percentages.national || 0) * 100).toFixed(1)}%)</div>
                </div>
                <div className="mt-1 text-xs">
                  used_state_stock={selectedRunSummary.used_state_stock ? 'true' : 'false'} | used_national_stock={selectedRunSummary.used_national_stock ? 'true' : 'false'}
                </div>
              </div>
            )}

            {selectedRunSummary.allocation_details && selectedRunSummary.allocation_details.length > 0 && (
              <div className="mt-3 overflow-x-auto border rounded bg-white">
                <div className="font-semibold p-2">Allocation Provenance (resource_id, district_code, time, allocated_quantity, source_level)</div>
                <table className="w-full text-sm">
                  <thead className="bg-slate-100 text-left">
                    <tr>
                      <th className="p-2">resource_id</th>
                      <th className="p-2">district_code</th>
                      <th className="p-2">time</th>
                      <th className="p-2">allocated_quantity</th>
                      <th className="p-2">source_level</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRunSummary.allocation_details.slice(0, 200).map((row, idx) => (
                      <tr key={`alloc_detail_${idx}`} className="border-t">
                        <td className="p-2">{row.resource_id}</td>
                        <td className="p-2">{row.district_code}</td>
                        <td className="p-2">{row.time}</td>
                        <td className="p-2">{Number(row.allocated_quantity || 0).toFixed(2)}</td>
                        <td className="p-2">{row.source_level}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {selectedRunSummary.by_time_breakdown && selectedRunSummary.by_time_breakdown.length > 0 && (
              <div className="mt-3 overflow-x-auto border rounded bg-white">
                <div className="font-semibold p-2">By-Time Service Quality</div>
                <table className="w-full text-sm">
                  <thead className="bg-slate-100 text-left">
                    <tr>
                      <th className="p-2">Time</th>
                      <th className="p-2">Demand</th>
                      <th className="p-2">Allocated</th>
                      <th className="p-2">Unmet</th>
                      <th className="p-2">Service Ratio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRunSummary.by_time_breakdown.slice(0, 40).map((row, idx) => (
                      <tr key={`time_row_${row.time}_${idx}`} className="border-t">
                        <td className="p-2">{row.time}</td>
                        <td className="p-2">{Number(row.demand_quantity || 0).toFixed(2)}</td>
                        <td className="p-2">{Number(row.allocated_quantity || 0).toFixed(2)}</td>
                        <td className="p-2">{Number(row.unmet_quantity || 0).toFixed(2)}</td>
                        <td className="p-2">{Number(row.service_ratio || 0).toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {selectedRunSummary.fairness && (
              <div className="mt-3 border rounded p-2 bg-white text-xs">
                <div className="font-semibold mb-1">Fairness & Time Index Diagnostics</div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  <div>District Jain: {selectedRunSummary.fairness.district_ratio_jain == null ? 'n/a' : Number(selectedRunSummary.fairness.district_ratio_jain).toFixed(4)}</div>
                  <div>State Jain: {selectedRunSummary.fairness.state_ratio_jain == null ? 'n/a' : Number(selectedRunSummary.fairness.state_ratio_jain).toFixed(4)}</div>
                  <div>District Gap: {selectedRunSummary.fairness.district_ratio_gap == null ? 'n/a' : Number(selectedRunSummary.fairness.district_ratio_gap).toFixed(4)}</div>
                  <div>State Gap: {selectedRunSummary.fairness.state_ratio_gap == null ? 'n/a' : Number(selectedRunSummary.fairness.state_ratio_gap).toFixed(4)}</div>
                  <div>Early Avg: {selectedRunSummary.fairness.time_service_early_avg == null ? 'n/a' : Number(selectedRunSummary.fairness.time_service_early_avg).toFixed(4)}</div>
                  <div>Late Avg: {selectedRunSummary.fairness.time_service_late_avg == null ? 'n/a' : Number(selectedRunSummary.fairness.time_service_late_avg).toFixed(4)}</div>
                </div>
                <div className={`mt-1 ${selectedRunSummary.fairness.fairness_flags?.length ? 'text-amber-700' : 'text-emerald-700'}`}>
                  Flags: {selectedRunSummary.fairness.fairness_flags?.length ? selectedRunSummary.fairness.fairness_flags.join(', ') : 'none'}
                </div>
              </div>
            )}
          </div>
        )}
      </Section>
      )}

      {activeTab === 'solver-runs' && (
      <Section title="Scenario Analysis">
        {analysis.explanations.length === 0 && analysis.recommendations.length === 0 && (
          <EmptyState message="No analysis available yet for selected scenario." />
        )}

        {analysis.explanations.map(ex => (
          <div key={ex.id} className="border rounded p-3 mb-2 text-sm bg-blue-50">
            <div className="font-semibold">Explanation (Run {ex.solver_run_id || '—'})</div>
            <div>{ex.summary}</div>
          </div>
        ))}

        {analysis.recommendations.slice(0, 25).map(rec => (
          <div key={rec.id} className="border rounded p-3 mb-2 text-sm bg-amber-50">
            <div className="font-semibold">{rec.action_type}</div>
            <div>{rec.message}</div>
            <div className="text-xs text-slate-600">
              District: {rec.district_code || '—'} | Resource: {rec.resource_id || '—'} | Confirmation: {rec.requires_confirmation ? 'required' : 'not required'}
            </div>
          </div>
        ))}
      </Section>
      )}

      {activeTab === 'neural' && (
        <Section title="Neural Controller Status">
          <div className="border rounded p-2 mb-3 text-xs bg-slate-50">
            <div className="font-semibold mb-1">Controller Context</div>
            <div>Selected Scenario: {selectedScenarioId || '—'} | Latest Run: {selectedRunSummary?.run_id || '—'} | Incidents: {incidentData?.incident_count || 0}</div>
            <div>Scope Mix: district={sharedScope.district.toFixed(2)} state={sharedScope.state.toFixed(2)} neighbor={sharedScope.neighbor.toFixed(2)} national={sharedScope.national.toFixed(2)}</div>
          </div>

          <OpsDataTable
            rows={scenarioRuns.map((run) => ({
              run_id: run.id,
              mode: run.mode,
              status: run.status,
              started_at: run.started_at || '—',
              source: run.mode === 'scenario' ? 'scenario_runner' : 'live_runner',
            }))}
            columns={[
              { key: 'run_id', label: 'Run ID' },
              { key: 'mode', label: 'Controller Mode' },
              { key: 'status', label: 'Status' },
              { key: 'source', label: 'Source' },
              { key: 'started_at', label: 'Updated At' },
            ]}
            emptyMessage="No run metadata available to infer controller state."
            rowKey={(row) => String(row.run_id)}
          />
        </Section>
      )}

      {activeTab === 'audit' && (
        <Section title="Audit Logs">
          <div className="border rounded p-2 mb-3 text-xs bg-slate-50">
            <div className="font-semibold mb-1">Audit Context</div>
            <div>Total events: {events.length} | Latest run: {selectedRunSummary?.run_id || '—'} | Incidents: {incidentData?.incident_count || 0}</div>
            <div>Revert check: {revertVerify ? (revertVerify.ok ? `PASS net=${Number(revertVerify.net_total || 0).toFixed(2)}` : `FAIL net=${Number(revertVerify.net_total || 0).toFixed(2)}`) : 'not checked in this view'}</div>
          </div>

          <OpsDataTable
            rows={events.map((event, index) => ({ ...event, id: index + 1 }))}
            columns={[
              { key: 'id', label: 'ID' },
              { key: 'timestamp', label: 'Timestamp' },
              { key: 'actor_level', label: 'Actor Level' },
              { key: 'actor_id', label: 'Actor ID' },
              { key: 'action', label: 'Action' },
              { key: 'resource_id', label: 'Resource' },
              { key: 'quantity', label: 'Quantity' },
              { key: 'time', label: 'Time' },
            ]}
            rowKey={(row) => String(row.id)}
            emptyMessage="No audit events found in browser-local audit log."
          />
        </Section>
      )}

    </div>
  )
}
