import { NavLink, Outlet } from "react-router-dom"
import { LayoutDashboard, Newspaper, Cpu, Database, Settings, Eye, LogOut } from "lucide-react"
import { logout } from "@/api/auth"

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/news", icon: Newspaper, label: "News" },
  { to: "/llm", icon: Cpu, label: "LLM Usage" },
  { to: "/cache", icon: Database, label: "Cache" },
  { to: "/settings", icon: Settings, label: "Settings" },
  { to: "/preview", icon: Eye, label: "Preview" },
]

export default function Layout() {
  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col shrink-0">
        <div className="p-4 border-b border-gray-200">
          <h1 className="text-lg font-semibold text-gray-800">News Portal</h1>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t border-gray-200">
          <button
            onClick={() => logout()}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors w-full"
          >
            <LogOut size={18} />
            Logout
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
