type ResourceStockRow = {
  resource_id: string
  district_stock: number
  state_stock: number
  national_stock: number
  in_transit?: number
  available_stock?: number
}

type VisibilityLevel = 'district' | 'state' | 'national'

function totalByLevel(row: ResourceStockRow, level: VisibilityLevel) {
  if (typeof row.available_stock === 'number') {
    return Number(row.available_stock || 0)
  }
  if (level === 'district') {
    return Number(row.district_stock || 0) + Number(row.state_stock || 0) + Number(row.national_stock || 0)
  }
  if (level === 'state') {
    return Number(row.state_stock || 0) + Number(row.national_stock || 0)
  }
  return Number(row.national_stock || 0)
}

export default function ResourceInventoryPanel({
  rows,
  level,
  onSelect,
}: {
  rows: ResourceStockRow[]
  level: VisibilityLevel
  onSelect: (row: ResourceStockRow) => void
}) {
  return (
    <div className="mb-3 rounded border bg-white px-3 py-2">
      <h3 className="mb-2 text-sm font-semibold">Resource Inventory</h3>
      {rows.length === 0 ? (
        <div className="text-xs text-slate-500">No stock rows available.</div>
      ) : (
        <div className="divide-y">
          {rows.map((row) => (
            <button
              key={row.resource_id}
              className="flex w-full items-center justify-between py-2 text-left text-sm hover:bg-slate-50"
              onClick={() => onSelect(row)}
            >
              <span>{row.resource_id}</span>
              <span>Total: {totalByLevel(row, level).toFixed(2)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
