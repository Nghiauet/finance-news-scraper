import { useCallback, useMemo, useSyncExternalStore } from "react"

export type Theme = "light" | "dark"

const KEY = "portal.theme"

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === "dark" || v === "light" ? v : null
  } catch {
    return null
  }
}

/* ---------------------------------------------------------------------------
   Module-level store.

   The theme has to be shared: the toggle lives in the sidebar while the charts
   read the resolved colours somewhere else entirely. Per-component useState
   would give each caller its own copy, and flipping the toggle would leave the
   charts on the old palette.
   --------------------------------------------------------------------------- */

let current: Theme = storedTheme() ?? systemTheme()
const listeners = new Set<() => void>()

function apply(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark")
}

function emit() {
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function setTheme(theme: Theme, persist: boolean) {
  if (theme === current) return
  current = theme
  apply(theme)
  if (persist) {
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      /* storage blocked — the theme still applies for this session */
    }
  }
  emit()
}

// Follow the OS for as long as the user hasn't made an explicit choice.
if (typeof window !== "undefined") {
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (!storedTheme()) setTheme(systemTheme(), false)
    })
}

/**
 * Current theme plus a toggle.
 *
 * The initial `.dark` class is set by an inline script in index.html so there's
 * no white flash before React mounts; this only keeps things in sync after.
 */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, () => current, () => current)
  const toggle = useCallback(() => setTheme(current === "dark" ? "light" : "dark", true), [])
  return { theme, toggle }
}

export interface ChartColors {
  accent: string
  ok: string
  warn: string
  danger: string
  line: string
  muted: string
  surface: string
  fg: string
}

/**
 * Resolved chart colours for the active theme.
 *
 * Recharts writes stroke/fill as SVG presentation attributes, which don't accept
 * `var()` — so the custom properties have to be read off the document and handed
 * over as concrete values, and re-read whenever the theme flips.
 */
export function useChartColors(): ChartColors {
  const { theme } = useTheme()
  return useMemo(() => {
    const cs = getComputedStyle(document.documentElement)
    const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback
    return {
      accent: v("--accent", "#3b4fd8"),
      ok: v("--ok", "#0a7f47"),
      warn: v("--warn", "#a55a06"),
      danger: v("--danger", "#b62525"),
      line: v("--line", "#dfe4ec"),
      muted: v("--fg-muted", "#58637a"),
      surface: v("--surface", "#ffffff"),
      fg: v("--fg", "#111725"),
    }
    // `theme` is the trigger: the variables changed, not this function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme])
}
