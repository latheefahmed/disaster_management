type ResourceStockRow = {
  resource_id: string
  district_stock: number
  state_stock: number
  national_stock: number
  in_transit?: number
  available_stock?: number
}

type VisibilityLevel = 'district' | 'state' | 'national'

export default function ResourceStockModal({
  open,
  onClose,
  row,
  level,
}: {
  open: boolean
  onClose: () => void
  row: ResourceStockRow | null
  level: VisibilityLevel
}) {
  if (!open || !row) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="w-full max-w-md rounded border bg-white p-4 shadow-sm" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-semibold">{row.resource_id}</h3>
          <button className="rounded border px-2 py-1 text-sm" onClick={onClose}>Close</button>
        </div>

        <div className="space-y-2 text-sm">
          {level === 'district' && <div>District Stock: {Number(row.district_stock || 0).toFixed(2)}</div>}
          {(level === 'district' || level === 'state') && <div>State Stock: {Number(row.state_stock || 0).toFixed(2)}</div>}
          <div>National Stock: {Number(row.national_stock || 0).toFixed(2)}</div>
          <div>In Transit: {Number(row.in_transit || 0).toFixed(2)}</div>
          <div>Available Stock: {Number(row.available_stock ?? (Number(row.district_stock || 0) + Number(row.state_stock || 0) + Number(row.national_stock || 0))).toFixed(2)}</div>
        </div>
      </div>
    </div>
  )
}
