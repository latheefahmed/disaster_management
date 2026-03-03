import { useEffect, useMemo, useState } from "react"
import Section from "../shared/Section"
import EmptyState from "../shared/EmptyState"

import { BACKEND_PATHS } from "../../data/backendPaths"
import { apiFetch } from "../../data/apiClient"

import { useAuth } from "../../auth/AuthContext"
import { useAuditLog } from "../../state/auditLog"

/* ---------------- TYPES ---------------- */

type Resource = {
  resource_id: string
  resource_name: string
  label?: string
  unit?: string
  ethical_priority: number
  max_per_resource?: number
  requires_integer_quantity?: boolean
}

type AllocationRow = {
  resource_id: string
  district_code: string
  state_code: string
  time: number
  allocated_quantity: number
}

type Urgency = "Low" | "Medium" | "High" | "Critical"

type ExistingRequest = {
  id: number
  resource_id: string
  time: number
  quantity: number
  human_priority?: number | null
  human_urgency?: number | null
  predicted_priority?: number | null
  predicted_urgency?: number | null
  prediction_confidence?: number | null
  prediction_explanation?: {
    features?: Array<{
      feature: string
      contribution: number
      model_type?: string
    }>
  } | null
  source: string
  status: string
  created_at?: string
}

type DraftRequest = {
  resource_id: string
  quantity: number
  time: number
  priority: number | null
  urgency: Urgency | ""
  confidence: number
  source: string
  notes?: string
}

/* ---------------- COMPONENT ---------------- */

export default function DistrictRequest() {
  const { districtCode } = useAuth()
  const { logEvent } = useAuditLog()

  const [resources, setResources] = useState<Resource[]>([])
  const [allocations, setAllocations] = useState<AllocationRow[]>([])
  const [existingRequests, setExistingRequests] =
    useState<ExistingRequest[]>([])

  const [drafts, setDrafts] = useState<DraftRequest[]>([])

  const [activeDraft, setActiveDraft] = useState<DraftRequest>({
    resource_id: "",
    quantity: 0,
    time: 0,
    priority: null,
    urgency: "",
    confidence: 1,
    source: "human"
  })

  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [submitBusy, setSubmitBusy] = useState(false)

  /* ---------------- LOAD DATA ---------------- */

  useEffect(() => {
    async function loadResources() {
      try {
        const res = await apiFetch<Resource[]>(
          BACKEND_PATHS.resourceCatalog
        )
        setResources(Array.isArray(res) ? res : [])
      } catch {
        setResources([])
      }
    }

    async function loadAllocations() {
      try {
        const json = await apiFetch<AllocationRow[]>(BACKEND_PATHS.districtAllocations)
        setAllocations(Array.isArray(json) ? json : [])
      } catch {
        setAllocations([])
      }
    }

    async function loadExistingRequests() {
      try {
        const reqJson = await apiFetch<ExistingRequest[]>(BACKEND_PATHS.districtListRequests)
        setExistingRequests(Array.isArray(reqJson) ? reqJson : [])
      } catch {
        setExistingRequests([])
      }
    }

    async function load() {
      await Promise.all([loadResources(), loadAllocations(), loadExistingRequests()])
    }

    load()
    const id = setInterval(load, 3000)
    return () => clearInterval(id)
  }, [])

  const resourceNameById = useMemo(() => {
    const out: Record<string, string> = {}
    for (const resource of resources) {
      out[resource.resource_id] = resource.resource_name
    }
    return out
  }, [resources])

  function toUrgencyNumber(value: Urgency): number {
    if (value === 'Low') return 1
    if (value === 'Medium') return 2
    if (value === 'High') return 3
    return 4
  }

  function predictionTooltip(req: ExistingRequest): string {
    const features = req.prediction_explanation?.features || []
    if (!features.length) return "No model explanation available"
    return features
      .slice(0, 3)
      .map(f => `${f.model_type || 'model'}: ${f.feature} (${Number(f.contribution).toFixed(3)})`)
      .join(' | ')
  }

  /* ---------------- DERIVED ---------------- */

  const allocatedForActive = useMemo(() => {
    if (!activeDraft.resource_id) return 0

    return allocations
      .filter(
        a =>
          a.district_code === districtCode &&
          a.resource_id === activeDraft.resource_id &&
          a.time === activeDraft.time
      )
      .reduce((s, r) => s + r.allocated_quantity, 0)
  }, [allocations, activeDraft, districtCode])

  const resourceMetaById = useMemo(() => {
    const out: Record<string, Resource> = {}
    for (const row of resources) {
      out[row.resource_id] = row
    }
    return out
  }, [resources])

  function mustUseWholeQuantity(resourceId: string): boolean {
    const rid = String(resourceId || '').trim()
    if (!rid) return false
    if (resourceMetaById[rid]?.requires_integer_quantity != null) {
      return Boolean(resourceMetaById[rid]?.requires_integer_quantity)
    }
    if (/^R\d+$/i.test(rid)) return true

    const unit = String(resourceMetaById[rid]?.unit || '').toLowerCase()
    if (!unit) return false
    return !unit.includes('liter')
  }

  function validateDraft(draft: DraftRequest): string | null {
    if (!draft.resource_id) return 'Select a resource.'
    if (!Number.isFinite(draft.time) || !Number.isInteger(draft.time) || draft.time < 0) return 'Time index must be an integer >= 0.'
    if (!Number.isFinite(draft.quantity) || draft.quantity <= 0) return 'Quantity must be greater than 0.'
    if (mustUseWholeQuantity(draft.resource_id) && !Number.isInteger(draft.quantity)) {
      return 'Selected resource requires whole-number quantity.'
    }
    const maxQty = Number(resourceMetaById[draft.resource_id]?.max_per_resource || 0)
    if (maxQty > 0 && Number(draft.quantity) > maxQty) {
      return `Quantity exceeds max allowed for selected resource (${Math.floor(maxQty)}).`
    }
    if (draft.priority != null) {
      if (!Number.isInteger(draft.priority) || draft.priority < 1 || draft.priority > 5) return 'Priority must be an integer between 1 and 5.'
    }
    if (!Number.isFinite(draft.confidence) || draft.confidence < 0 || draft.confidence > 1) return 'Confidence must be between 0 and 1.'
    return null
  }

  /* ---------------- ACTIONS ---------------- */

  function addDraft() {
    setError(null)
    setSuccess(null)

    const validationError = validateDraft(activeDraft)
    if (validationError) {
      setError(validationError)
      return
    }

    const existingIndex = drafts.findIndex(d => (
      d.resource_id === activeDraft.resource_id &&
      d.time === activeDraft.time &&
      (d.priority ?? null) === (activeDraft.priority ?? null) &&
      d.urgency === activeDraft.urgency &&
      d.source === activeDraft.source
    ))

    if (existingIndex >= 0) {
      const next = [...drafts]
      next[existingIndex] = {
        ...next[existingIndex],
        quantity: Number(next[existingIndex].quantity) + Number(activeDraft.quantity),
      }
      setDrafts(next)
    } else {
      setDrafts([...drafts, activeDraft])
    }

    setActiveDraft({
      resource_id: "",
      quantity: 0,
      time: activeDraft.time,
      priority: null,
      urgency: "",
      confidence: 1,
      source: "human"
    })
  }

  async function submitAll() {
    setError(null)
    setSuccess(null)

    if (drafts.length === 0) {
      setError("No resource requests added.")
      return
    }

    const firstInvalid = drafts.map(validateDraft).find(Boolean)
    if (firstInvalid) {
      setError(firstInvalid)
      return
    }

    setSubmitBusy(true)
    try {
      const payloadItems = drafts.map(d => ({
        resource_id: d.resource_id,
        time: d.time,
        quantity: d.quantity,
        priority: d.priority,
        urgency: d.urgency ? toUrgencyNumber(d.urgency as Urgency) : null,
        confidence: d.confidence,
        source: d.source,
      }))

      await apiFetch(BACKEND_PATHS.districtCreateRequestBatch, {
        method: "POST",
        body: JSON.stringify({ items: payloadItems })
      })

      for (const d of drafts) {
        logEvent({
          actor_level: "district",
          actor_id: districtCode!,
          action: "REQUEST",
          resource_id: d.resource_id,
          quantity: d.quantity,
          time: d.time,
          timestamp: new Date().toISOString(),
          request_context: {
            priority: d.priority ?? undefined,
            confidence: d.confidence,
            source: d.source,
            urgency: d.urgency || undefined,
            notes: d.notes
          }
        })
      }

      setDrafts([])
      setSuccess(`Submitted ${payloadItems.length} requests in one batch.`)

      const reqRows = await apiFetch<ExistingRequest[]>(BACKEND_PATHS.districtListRequests)
      setExistingRequests(Array.isArray(reqRows) ? reqRows : [])

    } catch (e: any) {
      setError(e.message || "Failed to submit requests.")
    } finally {
      setSubmitBusy(false)
    }
  }

  /* ---------------- UI ---------------- */

  return (
    <Section title={`District Resource Request — District ${districtCode}`}>
      <div className="max-w-4xl mx-auto space-y-6">

        <div className="bg-white rounded-xl shadow p-6 space-y-4">

          <h3 className="text-lg font-semibold">
            Add Resource Request
          </h3>

          <div className="grid grid-cols-2 gap-4">

            <div>
              <label className="text-sm font-medium">Resource</label>
              <select
                value={activeDraft.resource_id}
                onChange={e =>
                  setActiveDraft({
                    ...activeDraft,
                    resource_id: e.target.value
                  })
                }
                className="w-full border rounded px-3 py-2"
              >
                <option value="">Select resource</option>

                {resources.map(r => (
                  <option key={r.resource_id} value={r.resource_id}>
                    {r.resource_id} — {r.label || r.resource_name} ({r.unit || 'units'})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-sm font-medium">Time Index</label>
              <input
                type="number"
                min={0}
                value={activeDraft.time}
                onChange={e =>
                  setActiveDraft({
                    ...activeDraft,
                    time: Number(e.target.value)
                  })
                }
                className="w-full border rounded px-3 py-2"
              />
            </div>

            <div>
              <label className="text-sm font-medium">Quantity</label>
              <input
                type="number"
                min={1}
                value={activeDraft.quantity}
                onChange={e =>
                  setActiveDraft({
                    ...activeDraft,
                    quantity: Number(e.target.value)
                  })
                }
                className="w-full border rounded px-3 py-2"
              />
            </div>

            <div>
              <label className="text-sm font-medium">Priority</label>
              <input
                type="number"
                min={1}
                max={5}
                value={activeDraft.priority ?? ""}
                onChange={e =>
                  setActiveDraft({
                    ...activeDraft,
                    priority: e.target.value === "" ? null : Number(e.target.value)
                  })
                }
                placeholder="Leave blank for ML suggestion"
                className="w-full border rounded px-3 py-2"
              />
            </div>

            <div>
              <label className="text-sm font-medium">Urgency</label>
              <select
                value={activeDraft.urgency}
                onChange={e =>
                  setActiveDraft({
                    ...activeDraft,
                    urgency: e.target.value as Urgency | ""
                  })
                }
                className="w-full border rounded px-3 py-2"
              >
                <option value="">Auto (ML suggestion)</option>
                <option>Low</option>
                <option>Medium</option>
                <option>High</option>
                <option>Critical</option>
              </select>
            </div>

            <div>
              <label className="text-sm font-medium">Confidence (0-1)</label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={activeDraft.confidence}
                onChange={e =>
                  setActiveDraft({
                    ...activeDraft,
                    confidence: Number(e.target.value)
                  })
                }
                className="w-full border rounded px-3 py-2"
              />
            </div>

            <div>
              <label className="text-sm font-medium">Source</label>
              <select
                value={activeDraft.source}
                onChange={e =>
                  setActiveDraft({
                    ...activeDraft,
                    source: e.target.value
                  })
                }
                className="w-full border rounded px-3 py-2"
              >
                <option value="human">human</option>
                <option value="human_ai_agent">human_ai_agent</option>
              </select>
            </div>

          </div>

          {activeDraft.resource_id && (
            <div className="text-sm text-gray-600">
              Already allocated for this resource & time:{" "}
              <b>{allocatedForActive}</b>
            </div>
          )}

          <button
            onClick={addDraft}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Add to Request Batch
          </button>

          {error && (
            <div className="text-red-600 text-sm">{error}</div>
          )}

          {success && (
            <div className="text-green-600 text-sm">{success}</div>
          )}

        </div>

        <div className="bg-white rounded-xl shadow p-6">

          <h3 className="text-lg font-semibold mb-2">
            Pending Requests
          </h3>

          {drafts.length === 0 && (
            <EmptyState message="No resources added yet." />
          )}

          <div className="space-y-2">
            {drafts.map((d, i) => (
              <div
                key={i}
                className="border rounded p-3 flex justify-between text-sm"
              >
                <div>
                  <b>{resourceNameById[d.resource_id] || d.resource_id}</b> — Qty {d.quantity} — Time {d.time} — P{d.priority ?? "auto"}
                </div>
                <div className="text-orange-600">{d.urgency || "auto"} • {d.source}</div>
              </div>
            ))}
          </div>

        </div>

        <div className="bg-white rounded-xl shadow p-6 space-y-3">

          <h3 className="text-lg font-semibold">
            Submit Requests
          </h3>

          <button
            onClick={submitAll}
            disabled={submitBusy}
            className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
          >
            {submitBusy ? 'Submitting...' : 'Submit All Requests'}
          </button>

        </div>

        <div className="bg-white rounded-xl shadow p-6">

          <h3 className="text-lg font-semibold mb-2">
            Request Status Log (Live)
          </h3>

          {existingRequests.length === 0 && (
            <EmptyState message="No requests found yet." />
          )}

          {existingRequests.length > 0 && (
            <div className="overflow-x-auto border rounded">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 text-left">
                  <tr>
                    <th className="p-2">Resource</th>
                    <th className="p-2">Time</th>
                    <th className="p-2">Qty</th>
                    <th className="p-2">Priority</th>
                    <th className="p-2">Urgency</th>
                    <th className="p-2">Confidence</th>
                    <th className="p-2">Suggested</th>
                    <th className="p-2">Source</th>
                    <th className="p-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {existingRequests.slice(0, 20).map(r => (
                    <tr key={r.id} className="border-t">
                      <td className="p-2">{resourceNameById[r.resource_id] || r.resource_id}</td>
                      <td className="p-2">{r.time}</td>
                      <td className="p-2">{r.quantity}</td>
                      <td className="p-2">{r.human_priority ?? "auto"}</td>
                      <td className="p-2">{r.human_urgency ?? "auto"}</td>
                      <td className="p-2">{r.prediction_confidence == null ? "-" : Number(r.prediction_confidence).toFixed(2)}</td>
                      <td className="p-2">
                        {r.human_priority == null && r.predicted_priority != null && (
                          <span
                            className="inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
                            title={predictionTooltip(r)}
                          >
                            Suggested Priority: {Number(r.predicted_priority).toFixed(0)}
                          </span>
                        )}
                        {r.human_urgency == null && r.predicted_urgency != null && (
                          <div className="mt-1 text-xs text-amber-700">
                            Suggested Urgency: {Number(r.predicted_urgency).toFixed(0)}
                          </div>
                        )}
                      </td>
                      <td className="p-2">{r.source}</td>
                      <td className="p-2">{r.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

        </div>

      </div>
    </Section>
  )
}
