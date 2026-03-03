import { apiFetch } from './apiClient'

export async function loadJSON<T>(url: string): Promise<T> {
  return apiFetch<T>(url)
}
