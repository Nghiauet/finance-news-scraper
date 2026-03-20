const TOKEN_KEY = "scrape-news-token"

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function isAuthenticated(): boolean {
  return !!getToken()
}

export async function login(username: string, password: string): Promise<string> {
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  const json = await res.json()
  if (!res.ok || json.success === false) {
    throw new Error(json.error?.message || json.detail || "Login failed")
  }
  const token = json.data?.token
  if (!token) throw new Error("No token in response")
  setToken(token)
  return token
}

export function logout(): void {
  clearToken()
  window.location.href = import.meta.env.BASE_URL + "login"
}
