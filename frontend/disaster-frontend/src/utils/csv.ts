export function downloadCsv(filename: string, rows: Array<Record<string, unknown>>) {
  if (!rows || rows.length === 0) return

  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach(k => set.add(k))
      return set
    }, new Set<string>())
  )

  const escapeCell = (value: unknown) => {
    const raw = value === null || value === undefined ? '' : String(value)
    const escaped = raw.replace(/"/g, '""')
    if (/[",\n]/.test(escaped)) return `"${escaped}"`
    return escaped
  }

  const lines = [
    headers.join(','),
    ...rows.map(row => headers.map(h => escapeCell(row[h])).join(',')),
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
