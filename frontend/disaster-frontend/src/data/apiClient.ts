export class ApiError extends Error {
  status: number
  body: string

  constructor(message: string, status: number, body: string) {
    super(message)
    this.status = status
    this.body = body
  }
}

type CacheEntry = {
  expiresAt: number
  value: unknown
}

const RESPONSE_CACHE = new Map<string, CacheEntry>()

function nowMs(): number {
  return Date.now()
}

export function invalidateApiCache(prefix?: string) {
  if (!prefix) {
    RESPONSE_CACHE.clear()
    return
  }
  for (const key of RESPONSE_CACHE.keys()) {
    if (key.startsWith(prefix)) RESPONSE_CACHE.delete(key)
  }
}

function tryParseJson(text: string): unknown | undefined {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

export async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const method = String(init?.method || 'GET').toUpperCase()
  const isCacheable = method === 'GET' && !init?.body
  const cacheKey = `${method}:${url}`
  if (isCacheable) {
    const hit = RESPONSE_CACHE.get(cacheKey)
    if (hit && hit.expiresAt > nowMs()) {
      return hit.value as T
    }
  }

  const token = localStorage.getItem('token')

  const res = await fetch(url, {
    ...(init || {}),
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  })

  const text = await res.text()
  if (!res.ok) {
    let message = `Request failed: ${res.status}`
    const parsed = tryParseJson(text) as { detail?: unknown } | undefined
    if (parsed && typeof parsed === 'object' && parsed.detail != null) {
      message = String(parsed.detail)
    } else if (text) {
      message = text
    }
    throw new ApiError(message, res.status, text)
  }

  if (!text) {
    const empty = {} as T
    if (isCacheable) RESPONSE_CACHE.set(cacheKey, { expiresAt: nowMs() + 3000, value: empty })
    return empty
  }
  const parsed = tryParseJson(text)
  if (parsed !== undefined) {
    if (isCacheable) RESPONSE_CACHE.set(cacheKey, { expiresAt: nowMs() + 3000, value: parsed })
    return parsed as T
  }

  const looksLikeJson = /^[\s]*[\[{]/.test(text)
  if (looksLikeJson) {
    throw new ApiError('Malformed JSON response from server', res.status, text)
  }

  const plain = text as T
  if (isCacheable) RESPONSE_CACHE.set(cacheKey, { expiresAt: nowMs() + 3000, value: plain })
  return plain
}
