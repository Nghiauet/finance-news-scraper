import { useState, type FormEvent } from "react"
import { useNavigate, Navigate } from "react-router-dom"
import { AlertTriangle, Loader2 } from "lucide-react"
import { login, isAuthenticated } from "@/api/auth"
import { Button, Field, inputClass } from "@/components/ui"

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  if (isAuthenticated()) {
    return <Navigate to="/" replace />
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      await login(username, password)
      navigate("/", { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight text-fg">News Pipeline</h1>
          <p className="mt-1 text-sm text-muted">Operator console for the Vietnamese finance news scraper.</p>
        </div>

        <div className="rounded-xl border border-line bg-surface p-6 shadow-[var(--shadow-card)]">
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <Field label="Username">
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
                autoComplete="username"
                className={inputClass}
                placeholder="admin"
              />
            </Field>

            <Field label="Password">
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className={inputClass}
              />
            </Field>

            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger"
              >
                <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden />
                <span>{error}</span>
              </div>
            )}

            <Button type="submit" variant="primary" disabled={loading} className="w-full justify-center">
              {loading && <Loader2 size={14} className="animate-spin" aria-hidden />}
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
