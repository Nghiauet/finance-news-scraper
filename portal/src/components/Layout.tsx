import { useEffect, useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import {
  LayoutDashboard, Newspaper, Cpu, Database, Settings, LogOut,
  Menu, X, Moon, Sun, Activity,
} from "lucide-react"
import { logout } from "@/api/auth"
import { useAdminStats, useRefreshStatus } from "@/api/hooks"
import { useTheme } from "@/lib/theme"
import { IconButton, StatusDot } from "@/components/ui"

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/news", icon: Newspaper, label: "News" },
  { to: "/llm", icon: Cpu, label: "LLM Usage" },
  { to: "/cache", icon: Database, label: "Cache" },
  { to: "/settings", icon: Settings, label: "Settings" },
]

/**
 * Pipeline state, always visible.
 *
 * The two things an operator actually needs to know — is Redis up, and is a
 * scrape running — used to require navigating to two different pages.
 */
function HealthStrip() {
  const { data: stats } = useAdminStats()
  const { data: status } = useRefreshStatus()

  const connected: boolean | undefined = stats?.data?.cache?.connected
  const running = status?.data?.running === true
  const articles: number | undefined = stats?.data?.cache?.article_count

  return (
    <div className="space-y-1.5 border-t border-line px-3 py-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-subtle">
          <Database size={12} aria-hidden /> Redis
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot tone={connected === undefined ? "neutral" : connected ? "ok" : "danger"} />
          <span className={connected === false ? "text-danger" : "text-muted"}>
            {connected === undefined ? "—" : connected ? "up" : "down"}
          </span>
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-subtle">
          <Activity size={12} aria-hidden /> Scrape
        </span>
        <span className="flex items-center gap-1.5">
          <StatusDot tone={running ? "accent" : "neutral"} pulse={running} />
          <span className="text-muted">{running ? "running" : "idle"}</span>
        </span>
      </div>
      {articles !== undefined && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-subtle">Cached</span>
          <span className="tnum text-muted">{articles.toLocaleString()}</span>
        </div>
      )}
    </div>
  )
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Sections">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-accent-soft text-accent"
                  : "text-muted hover:bg-surface-2 hover:text-fg"
              }`
            }
          >
            <Icon size={17} aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>
      <HealthStrip />
      <div className="p-2">
        <button
          onClick={() => logout()}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
        >
          <LogOut size={17} aria-hidden />
          Sign out
        </button>
      </div>
    </>
  )
}

export default function Layout() {
  const { theme, toggle } = useTheme()
  const location = useLocation()

  // The drawer is open only for the route it was opened on, so any navigation —
  // including browser back/forward — closes it without an effect that would
  // trigger a second render pass on every route change.
  const [openedAt, setOpenedAt] = useState<string | null>(null)
  const drawerOpen = openedAt === location.pathname
  const setDrawerOpen = (open: boolean) => setOpenedAt(open ? location.pathname : null)

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [drawerOpen])

  const themeButton = (
    <IconButton label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"} onClick={toggle}>
      {theme === "dark" ? <Sun size={17} aria-hidden /> : <Moon size={17} aria-hidden />}
    </IconButton>
  )

  return (
    <div className="min-h-screen bg-bg lg:flex">
      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center gap-2 border-b border-line bg-surface px-3 py-2 lg:hidden">
        <IconButton label="Open navigation" onClick={() => setDrawerOpen(true)}>
          <Menu size={18} aria-hidden />
        </IconButton>
        <span className="flex-1 truncate text-sm font-semibold text-fg">News Pipeline</span>
        {themeButton}
      </header>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            className="absolute inset-0 bg-black/50"
            aria-label="Close navigation"
            onClick={() => setDrawerOpen(false)}
          />
          <aside
            className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-surface"
            aria-label="Navigation"
          >
            <div className="flex items-center justify-between border-b border-line px-3 py-3">
              <span className="text-sm font-semibold text-fg">News Pipeline</span>
              <IconButton label="Close navigation" onClick={() => setDrawerOpen(false)}>
                <X size={17} aria-hidden />
              </IconButton>
            </div>
            <SidebarContent onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside
        className="hidden w-56 shrink-0 flex-col border-r border-line bg-surface lg:sticky lg:top-0 lg:flex lg:h-screen"
        aria-label="Navigation"
      >
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-fg">News Pipeline</p>
            <p className="text-xs text-subtle">Operator console</p>
          </div>
          {themeButton}
        </div>
        <SidebarContent />
      </aside>

      <main className="min-w-0 flex-1 p-4 sm:p-6">
        <Outlet />
      </main>
    </div>
  )
}
