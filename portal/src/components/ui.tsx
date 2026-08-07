import type { ReactNode } from "react"
import { AlertTriangle, Inbox, RotateCw } from "lucide-react"

/* ---------------------------------------------------------------- containers */

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`rounded-xl border border-line bg-surface shadow-[var(--shadow-card)] ${className}`}
    >
      {children}
    </section>
  )
}

export function CardHeader({ title, hint, actions }: { title: string; hint?: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-subtle">{hint}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  )
}

/** Page heading with optional right-hand controls. */
export function PageHeader({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-fg">{title}</h1>
        {hint && <p className="mt-1 text-sm text-muted">{hint}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

/* ----------------------------------------------------------------- controls */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost"

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:opacity-90",
  secondary: "border border-line bg-surface text-fg hover:bg-surface-2",
  danger: "bg-danger text-white hover:opacity-90",
  ghost: "text-muted hover:bg-surface-2 hover:text-fg",
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  children: ReactNode
}

export function Button({ variant = "secondary", className = "", children, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

/** Icon-only button. `label` is required — it becomes the accessible name. */
export function IconButton({
  label, className = "", children, ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={`rounded-lg p-1.5 text-subtle transition-colors hover:bg-surface-2 hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-subtle">{hint}</span>}
    </label>
  )
}

export const inputClass =
  "w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-fg " +
  "placeholder:text-subtle focus:border-accent focus:outline-none"

/* ------------------------------------------------------------------- status */

type Tone = "ok" | "warn" | "danger" | "neutral" | "accent"

const TONES: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
  accent: "bg-accent-soft text-accent",
  neutral: "bg-surface-2 text-muted",
}

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  )
}

const DOTS: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  accent: "bg-accent",
  neutral: "bg-subtle",
}

export function StatusDot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0">
      {pulse && (
        <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${DOTS[tone]}`} />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${DOTS[tone]}`} />
    </span>
  )
}

/** A labelled figure. Numbers are monospaced so columns line up across cards. */
export function Metric({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-subtle">{label}</dt>
      <dd className="tnum mt-0.5 truncate text-sm font-medium text-fg">{value}</dd>
      {sub && <dd className="mt-0.5 truncate text-xs text-subtle">{sub}</dd>}
    </div>
  )
}

/* --------------------------------------------------------- loading & empties */

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-surface-2 ${className}`} aria-hidden />
}

/** Card-shaped placeholder grid, used while the first fetch is in flight. */
export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <Card key={i} className="p-4">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-3 h-7 w-24" />
        </Card>
      ))}
    </div>
  )
}

export function SkeletonRows({ rows = 6, className = "" }: { rows?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  )
}

export function PageSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-7 w-40" />
      <SkeletonCards />
      <Card className="p-4">
        <Skeleton className="h-4 w-32" />
        <SkeletonRows className="mt-4" />
      </Card>
    </div>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <Inbox size={24} className="text-subtle" aria-hidden />
      <p className="text-sm font-medium text-fg">{title}</p>
      {hint && <p className="max-w-sm text-sm text-muted">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/**
 * Failure state. Says what broke and offers the way out, rather than dumping a
 * red string on an otherwise blank page.
 */
export function ErrorState({ title, error, onRetry }: { title: string; error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error ?? "Unknown error")
  return (
    <Card className="p-6">
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-fg">{title}</p>
          <p className="mt-1 text-sm break-words text-muted">{message}</p>
          {onRetry && (
            <Button variant="secondary" className="mt-3" onClick={onRetry}>
              <RotateCw size={14} aria-hidden /> Try again
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------------- tables */

/**
 * Horizontal scroll container for tables.
 *
 * Wide tables used to widen the whole page on a phone; now they scroll inside
 * their own card and the page never gains a horizontal scrollbar.
 */
export function TableScroll({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`w-full overflow-x-auto ${className}`}>{children}</div>
}

export const thClass = "px-4 py-2 text-left text-xs font-medium tracking-wide text-subtle uppercase"
export const tdClass = "px-4 py-2 text-sm text-fg"
