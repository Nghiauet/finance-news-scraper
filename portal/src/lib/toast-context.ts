import { createContext, useContext } from "react"

export type ToastKind = "success" | "error" | "warn"

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

export interface ToastApi {
  success: (message: string) => void
  error: (message: string) => void
  warn: (message: string) => void
}

/**
 * Kept out of Toast.tsx so that file exports components only — mixing a hook in
 * breaks React Fast Refresh for the whole module.
 */
export const ToastContext = createContext<ToastApi | null>(null)

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>")
  return ctx
}
