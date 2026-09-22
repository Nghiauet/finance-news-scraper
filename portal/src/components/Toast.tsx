import {
  useCallback, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react"
import { CheckCircle2, AlertTriangle, XCircle, X } from "lucide-react"
import { ToastContext, type Toast, type ToastApi, type ToastKind } from "@/lib/toast-context"

const DURATION: Record<ToastKind, number> = {
  // Errors stay until dismissed — an operator who stepped away shouldn't miss
  // that a purge or refresh failed.
  success: 4000,
  warn: 6000,
  error: 0,
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId.current++
      setToasts((prev) => [...prev, { id, kind, message }])
      const ms = DURATION[kind]
      if (ms > 0) timers.current.set(id, setTimeout(() => dismiss(id), ms))
    },
    [dismiss],
  )

  useEffect(() => {
    const map = timers.current
    return () => map.forEach(clearTimeout)
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      success: (m) => push("success", m),
      error: (m) => push("error", m),
      warn: (m) => push("warn", m),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <Toaster toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

const STYLES: Record<ToastKind, { cls: string; Icon: typeof CheckCircle2; label: string }> = {
  success: { cls: "border-ok/40 bg-ok-soft text-ok", Icon: CheckCircle2, label: "Success" },
  warn: { cls: "border-warn/40 bg-warn-soft text-warn", Icon: AlertTriangle, label: "Warning" },
  error: { cls: "border-danger/40 bg-danger-soft text-danger", Icon: XCircle, label: "Error" },
}

function Toaster({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div
      // Announced to screen readers without stealing focus.
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end"
    >
      {toasts.map(({ id, kind, message }) => {
        const { cls, Icon, label } = STYLES[kind]
        return (
          <div
            key={id}
            className={`pointer-events-auto flex w-full max-w-sm items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm shadow-lg ${cls}`}
          >
            <Icon size={16} className="mt-0.5 shrink-0" aria-hidden />
            <span className="sr-only">{label}:</span>
            <p className="flex-1 leading-snug break-words">{message}</p>
            <button
              onClick={() => onDismiss(id)}
              aria-label="Dismiss notification"
              className="shrink-0 rounded p-0.5 opacity-60 transition-opacity hover:opacity-100"
            >
              <X size={14} aria-hidden />
            </button>
          </div>
        )
      })}
    </div>
  )
}
