import { useMemo, useState } from 'react'
import OpsDataTable from '../dashboards/shared/OpsDataTable'

type ResourceMeta = {
  resource_id: string
  resource_name?: string
  label?: string
  category?: string
  class?: string
}

type StockRow = {
  resource_id: string
  district_stock: number
  state_stock: number
  national_stock: number
  in_transit?: number
  available_stock?: number
}

type Scope = 'district' | 'state' | 'national'

function toNumber(value: unknown): number {
  const parsed = Number(value || 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function qtyForScope(row: StockRow, scope: Scope): number {
  if (scope === 'district') return toNumber(row.district_stock)
  if (scope === 'state') return toNumber(row.state_stock)
  return toNumber(row.national_stock)
}

function available(row: StockRow): number {
  if (typeof row.available_stock === 'number') return toNumber(row.available_stock)
  return toNumber(row.district_stock) + toNumber(row.state_stock) + toNumber(row.national_stock) - toNumber(row.in_transit)
}

export default function ResourceStockTabs({
  rows,
  resources,
  defaultScope = 'district',
}: {
  rows: StockRow[]
  resources: ResourceMeta[]
  defaultScope?: Scope
}) {
  const [scope, setScope] = useState<Scope>(defaultScope)
  const [query, setQuery] = useState('')

  const resourceMap = useMemo(() => {
    const out: Record<string, ResourceMeta> = {}
    for (const row of resources) out[row.resource_id] = row
    return out
  }, [resources])

  const scopedRows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows
      .map((row) => {
        const meta = resourceMap[row.resource_id]
        return {
          ...row,
          resource_name: meta?.resource_name || meta?.label || row.resource_id,
          resource_category: meta?.category || '—',
          resource_class: meta?.class || '—',
          scope_quantity: qtyForScope(row, scope),
          available_quantity: available(row),
          in_transit_quantity: toNumber(row.in_transit),
        }
      })
      .filter((row) => {
        if (!needle) return true
        return (
          row.resource_id.toLowerCase().includes(needle)
          || String(row.resource_name).toLowerCase().includes(needle)
          || String(row.resource_category).toLowerCase().includes(needle)
        )
      })
      .sort((a, b) => b.scope_quantity - a.scope_quantity)
  }, [rows, resourceMap, scope, query])

  const scopeTotals = useMemo(() => {
    return {
      total: scopedRows.reduce((sum, row) => sum + Number(row.scope_quantity || 0), 0),
      available: scopedRows.reduce((sum, row) => sum + Number(row.available_quantity || 0), 0),
      inTransit: scopedRows.reduce((sum, row) => sum + Number(row.in_transit_quantity || 0), 0),
    }
  }, [scopedRows])

  const tabs: Array<{ key: Scope; label: string }> = [
    { key: 'district', label: 'District Stock' },
    { key: 'state', label: 'State Stock' },
    { key: 'national', label: 'National Stock' },
  ]

  return (
    <div className="rounded border bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Resource Stocks</h3>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search resource"
          className="rounded border px-2 py-1 text-sm"
        />
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setScope(tab.key)}
            className={`rounded border px-3 py-1 text-sm ${scope === tab.key ? 'bg-slate-800 text-white border-slate-800' : 'bg-white'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-3 text-xs">
        <div className="rounded border bg-slate-50 px-3 py-2"><span className="font-semibold">Scope Total: </span>{scopeTotals.total.toFixed(2)}</div>
        <div className="rounded border bg-slate-50 px-3 py-2"><span className="font-semibold">Available: </span>{scopeTotals.available.toFixed(2)}</div>
        <div className="rounded border bg-slate-50 px-3 py-2"><span className="font-semibold">In Transit: </span>{scopeTotals.inTransit.toFixed(2)}</div>
      </div>

      <OpsDataTable
        rows={scopedRows}
        pageSize={12}
        columns={[
          { key: 'resource_name', label: 'Resource' },
          { key: 'resource_id', label: 'Resource ID' },
          { key: 'resource_category', label: 'Category' },
          { key: 'resource_class', label: 'Class' },
          { key: 'scope_quantity', label: scope === 'district' ? 'District Qty' : scope === 'state' ? 'State Qty' : 'National Qty' },
          { key: 'in_transit_quantity', label: 'In Transit' },
          { key: 'available_quantity', label: 'Available' },
        ]}
        rowKey={(row) => String(row.resource_id)}
        emptyMessage="No stock rows found."
      />
    </div>
  )
}
