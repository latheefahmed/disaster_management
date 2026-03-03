import { Fragment, useMemo, useState } from 'react'

type SortDirection = 'asc' | 'desc'

export type OpsColumn<T> = {
  key: keyof T | string
  label: string
  sortable?: boolean
  filterable?: boolean
  render?: (row: T) => React.ReactNode
}

type Props<T extends Record<string, any>> = {
  title?: string
  rows: T[]
  columns: Array<OpsColumn<T>>
  pageSize?: number
  emptyMessage?: string
  searchPlaceholder?: string
  rowKey?: (row: T, index: number) => string
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export default function OpsDataTable<T extends Record<string, any>>({
  title,
  rows,
  columns,
  pageSize = 10,
  emptyMessage = 'No rows found.',
  searchPlaceholder = 'Search table…',
  rowKey,
}: Props<T>) {
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [sortKey, setSortKey] = useState<string>('')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const filterableColumns = useMemo(
    () => columns.filter((c) => c.filterable !== false),
    [columns],
  )

  const processed = useMemo(() => {
    const needle = search.trim().toLowerCase()

    const filtered = rows.filter((row) => {
      const globalMatch =
        !needle ||
        columns.some((col) => {
          const value = col.render ? col.render(row) : row[col.key as keyof T]
          return stringifyValue(value).toLowerCase().includes(needle)
        })

      if (!globalMatch) return false

      for (const col of filterableColumns) {
        const value = (filters[col.key as string] || '').trim().toLowerCase()
        if (!value) continue
        const raw = stringifyValue(row[col.key as keyof T]).toLowerCase()
        if (!raw.includes(value)) return false
      }

      return true
    })

    if (!sortKey) return filtered

    return [...filtered].sort((a, b) => {
      const aVal = stringifyValue(a[sortKey as keyof T])
      const bVal = stringifyValue(b[sortKey as keyof T])
      const cmp = aVal.localeCompare(bVal, undefined, { numeric: true, sensitivity: 'base' })
      return sortDirection === 'asc' ? cmp : -cmp
    })
  }, [rows, columns, search, filters, filterableColumns, sortKey, sortDirection])

  const pageCount = Math.max(1, Math.ceil(processed.length / pageSize))
  const normalizedPage = Math.min(page, pageCount)
  const pagedRows = useMemo(() => {
    const start = (normalizedPage - 1) * pageSize
    return processed.slice(start, start + pageSize)
  }, [processed, normalizedPage, pageSize])

  function onSort(key: string) {
    if (sortKey === key) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
    setPage(1)
  }

  return (
    <div className="space-y-3">
      {title && <div className="text-sm font-semibold text-slate-700">{title}</div>}

      <div className="flex flex-wrap gap-2 items-center">
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
          placeholder={searchPlaceholder}
          className="border rounded px-2 py-1 text-sm min-w-64"
        />
        <span className="text-xs text-slate-500">Rows: {processed.length}</span>
      </div>

      <div className="overflow-x-auto border rounded max-h-[60vh]">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left sticky top-0 z-10">
            <tr>
              <th className="p-2 w-24">Raw JSON</th>
              {columns.map((col) => (
                <th key={String(col.key)} className="p-2">
                  <button
                    type="button"
                    className="font-semibold text-left"
                    onClick={() => (col.sortable === false ? undefined : onSort(String(col.key)))}
                  >
                    {col.label}
                    {sortKey === String(col.key) ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : ''}
                  </button>
                </th>
              ))}
            </tr>
            <tr>
              <th className="p-2" />
              {columns.map((col) => (
                <th key={`filter_${String(col.key)}`} className="p-1">
                  {col.filterable === false ? null : (
                    <input
                      value={filters[String(col.key)] || ''}
                      onChange={(e) => {
                        setFilters((prev) => ({ ...prev, [String(col.key)]: e.target.value }))
                        setPage(1)
                      }}
                      className="w-full border rounded px-1 py-1 text-xs"
                      placeholder="Filter"
                    />
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pagedRows.length === 0 ? (
              <tr>
                <td className="p-3 text-slate-500" colSpan={columns.length + 1}>
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              pagedRows.map((row, index) => {
                const key = rowKey ? rowKey(row, index) : `${normalizedPage}_${index}`
                const showRaw = !!expanded[key]
                return (
                  <Fragment key={key}>
                    <tr key={key} className="border-t align-top">
                      <td className="p-2">
                        <button
                          type="button"
                          className="px-2 py-1 rounded border text-xs"
                          onClick={() => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))}
                        >
                          {showRaw ? 'Hide' : 'View'}
                        </button>
                      </td>
                      {columns.map((col) => (
                        <td key={`${key}_${String(col.key)}`} className="p-2">
                          {col.render ? col.render(row) : stringifyValue(row[col.key as keyof T])}
                        </td>
                      ))}
                    </tr>
                    {showRaw && (
                      <tr className="border-t bg-slate-50">
                        <td className="p-2 text-xs text-slate-700" colSpan={columns.length + 1}>
                          <pre className="whitespace-pre-wrap break-words">{JSON.stringify(row, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-slate-600">
        <span>
          Page {normalizedPage} of {pageCount}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="px-2 py-1 rounded border"
            disabled={normalizedPage <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Prev
          </button>
          <button
            type="button"
            className="px-2 py-1 rounded border"
            disabled={normalizedPage >= pageCount}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
