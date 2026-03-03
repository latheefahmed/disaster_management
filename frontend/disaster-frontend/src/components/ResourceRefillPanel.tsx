import { useMemo, useState } from 'react'

import { apiFetch } from '../data/apiClient'

type ResourceMeta = {
  resource_id: string
  resource_name?: string
  label?: string
  category?: string
  class?: string
}

type Scope = 'district' | 'state' | 'national'

export default function ResourceRefillPanel({
  scope,
  resources,
  endpoint,
  onRefilled,
}: {
  scope: Scope
  resources: ResourceMeta[]
  endpoint: string
  onRefilled: () => Promise<void> | void
}) {
  const [resourceId, setResourceId] = useState('')
  const [quantity, setQuantity] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const options = useMemo(() => {
    return resources
      .map((r) => ({
        id: String(r.resource_id),
        name: String(r.resource_name || r.label || r.resource_id),
        category: String(r.category || '—'),
      }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [resources])

  async function submitRefill() {
    const qty = Number(quantity)
    if (!resourceId) {
      setError('Select a resource first')
      return
    }
    if (!Number.isFinite(qty) || qty <= 0) {
      setError('Quantity must be greater than 0')
      return
    }

    setBusy(true)
    setError('')
    setMessage('')
    try {
      await apiFetch(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          resource_id: resourceId,
          quantity: qty,
          note: note.trim() || `${scope}_manual_refill`,
        }),
      })
      await onRefilled()
      setMessage('Stock refill applied successfully.')
      setQuantity('')
      setNote('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Refill failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded border bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold">Refill Resources</h3>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <div className="md:col-span-2">
          <label className="mb-1 block text-xs font-semibold text-slate-700">Resource</label>
          <select
            value={resourceId}
            onChange={(e) => setResourceId(e.target.value)}
            className="w-full rounded border px-2 py-2 text-sm"
          >
            <option value="">Select resource</option>
            {options.map((opt) => (
              <option key={opt.id} value={opt.id}>{opt.name} ({opt.id}) - {opt.category}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-700">Quantity</label>
          <input
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            type="number"
            min={1}
            step="1"
            className="w-full rounded border px-2 py-2 text-sm"
            placeholder="e.g. 500"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-slate-700">Note</label>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="w-full rounded border px-2 py-2 text-sm"
            placeholder="Optional reason"
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={submitRefill}
          disabled={busy}
          className="rounded bg-emerald-700 px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {busy ? 'Refilling...' : 'Apply Refill'}
        </button>
        <span className="text-xs text-slate-500">This updates backend stock immediately for next solver run and stock views.</span>
      </div>

      {error && <div className="mt-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-sm text-red-700">{error}</div>}
      {message && <div className="mt-2 rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-sm text-emerald-700">{message}</div>}
    </div>
  )
}
