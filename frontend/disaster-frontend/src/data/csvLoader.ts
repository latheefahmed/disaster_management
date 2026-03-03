// frontend/src/data/csvLoader.ts

export async function loadCSV<T>(url: string): Promise<T[]> {
  const res = await fetch(url)

  if (!res.ok) {
    throw new Error(`Failed to fetch CSV ${url}`)
  }

  const text = await res.text()
  const lines = text.trim().split('\n')

  if (lines.length < 2) return []

  const headers = lines[0].split(',').map(h => h.trim())

  return lines.slice(1).map(line => {
    const values = line.split(',')
    const obj: any = {}

    headers.forEach((h, i) => {
      obj[h] = values[i]
    })

    return obj as T
  })
}
