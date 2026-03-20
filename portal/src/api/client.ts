import { getToken, clearToken } from "./auth"

function authHeaders(): Record<string, string> {
  const token = getToken()
  if (token) return { Authorization: `Bearer ${token}` }
  return {}
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    clearToken()
    window.location.href = import.meta.env.BASE_URL + "login"
    throw new Error("Session expired")
  }
  if (!res.ok) {
    const errJson = await res.json().catch(() => null)
    throw new Error(errJson?.error?.message || errJson?.detail || `API error: ${res.status}`)
  }
  const json = await res.json()
  if (json.success === false) throw new Error(json.error?.message || "Unknown error")
  return json
}

async function apiRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() }
  const init: RequestInit = { method, headers }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json"
    init.body = JSON.stringify(body)
  }
  const res = await fetch(path, init)
  return handleResponse<T>(res)
}

export async function apiFetch<T>(path: string): Promise<T> {
  return apiRequest<T>("GET", path)
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiRequest<T>("POST", path, body)
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>("PUT", path, body)
}

export async function apiDelete<T>(path: string): Promise<T> {
  return apiRequest<T>("DELETE", path)
}
