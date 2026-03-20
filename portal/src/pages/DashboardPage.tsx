import { Newspaper, Globe, Cpu, Database, Clock, CheckCircle, XCircle, AlertTriangle, RefreshCw } from "lucide-react"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts"
import { useAdminStats, useAdminCron, useRefreshAll, useRefreshStatus } from "@/api/hooks"
import StatsCard from "@/components/StatsCard"

function formatCronTime(ts: number) {
  const d = new Date(ts * 1000)
  return `${d.getDate()}/${d.getMonth() + 1} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}

export default function DashboardPage() {
  const { data, isLoading, error } = useAdminStats()
  const { data: cronData } = useAdminCron()
  const refreshAllMut = useRefreshAll()
  const { data: statusData } = useRefreshStatus()

  const isRefreshing = statusData?.data?.running === true

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-500">Error: {(error as Error).message}</div>

  const d = data?.data
  const cache = d?.cache || {}
  const totals = d?.llm_totals || {}
  const sources = d?.sources || []
  const cronRuns: any[] = (cronData?.data?.runs || []).slice().reverse()

  const durationChart = cronRuns.map((r: any) => ({
    time: formatCronTime(r.started_at),
    duration: r.duration_s,
    articles: r.articles_total,
    sources_ok: r.sources_ok,
  }))

  // Latest run for quick status
  const lastRun = cronRuns.length ? cronRuns[cronRuns.length - 1] : null

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-800">Dashboard</h2>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard title="Cached Articles" value={cache.article_count ?? 0} icon={<Newspaper size={20} />} />
        <StatsCard title="Active Sources" value={`${cache.news_sources ?? 0} / ${sources.length}`} icon={<Globe size={20} />} />
        <StatsCard title="Total Tokens" value={(totals.total_tokens ?? 0).toLocaleString()} icon={<Cpu size={20} />} subtitle={`${(totals.call_count ?? 0).toLocaleString()} calls`} />
        <StatsCard title="Redis Memory" value={`${cache.memory_used_mb ?? 0} MB`} icon={<Database size={20} />} />
      </div>

      {/* Cron Job Status */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <Clock size={16} /> Cron Job
          </h3>
          <div className="flex items-center gap-3">
            {lastRun && <span className="text-xs text-gray-400">Last: {formatCronTime(lastRun.started_at)}</span>}
            {isRefreshing && <span className="text-xs text-blue-600 font-medium animate-pulse">Running...</span>}
            <button
              onClick={() => {
                if (!confirm("Scrape all sources for new articles now? (Same as the automatic 30-min cron)")) return
                refreshAllMut.mutate()
              }}
              disabled={isRefreshing || refreshAllMut.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
              {isRefreshing ? "Running..." : "Run Now"}
            </button>
          </div>
        </div>
        {refreshAllMut.isError && (
          <div className="mb-3 text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">
            {(refreshAllMut.error as Error).message}
          </div>
        )}
        {lastRun && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 text-sm">
            <div>
              <span className="text-gray-400">Duration</span>
              <p className="font-medium text-gray-800">{lastRun.duration_s}s</p>
            </div>
            <div>
              <span className="text-gray-400">Sources</span>
              <p className="font-medium text-gray-800">
                <span className="text-green-600">{lastRun.sources_ok}</span>
                <span className="text-gray-400"> / {lastRun.sources_total}</span>
              </p>
            </div>
            <div>
              <span className="text-gray-400">Articles</span>
              <p className="font-medium text-gray-800">{lastRun.articles_total}</p>
            </div>
            <div>
              <span className="text-gray-400">Failed</span>
              <p className={`font-medium ${lastRun.sources_failed > 0 ? "text-red-600" : "text-green-600"}`}>
                {lastRun.sources_failed}
              </p>
            </div>
            <div>
              <span className="text-gray-400">Status</span>
              <p className="flex items-center gap-1">
                {lastRun.timed_out ? (
                  <><AlertTriangle size={14} className="text-yellow-500" /> <span className="font-medium text-yellow-600">Timeout</span></>
                ) : lastRun.sources_failed > 0 ? (
                  <><XCircle size={14} className="text-orange-500" /> <span className="font-medium text-orange-600">Partial</span></>
                ) : (
                  <><CheckCircle size={14} className="text-green-500" /> <span className="font-medium text-green-600">OK</span></>
                )}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Cron Duration Chart */}
      {durationChart.length > 1 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4">Cron Run Duration</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={durationChart}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} unit="s" />
              <Tooltip formatter={(v, name) => [name === "duration" ? `${v}s` : v, name === "duration" ? "Duration" : "Articles"]} />
              <Line type="monotone" dataKey="duration" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} name="Duration" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Cron Runs History */}
      {cronRuns.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="p-4 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">Cron History ({cronRuns.length} runs)</h3>
          </div>
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-500 sticky top-0">
                <tr>
                  <th className="px-4 py-2 font-medium">Time</th>
                  <th className="px-4 py-2 font-medium text-right">Duration</th>
                  <th className="px-4 py-2 font-medium text-right">Sources</th>
                  <th className="px-4 py-2 font-medium text-right">Articles</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {[...cronRuns].reverse().map((r: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-500 whitespace-nowrap">{formatCronTime(r.started_at)}</td>
                    <td className="px-4 py-2 text-right text-gray-700">{r.duration_s}s</td>
                    <td className="px-4 py-2 text-right">
                      <span className="text-green-600">{r.sources_ok}</span>
                      <span className="text-gray-400">/{r.sources_total}</span>
                    </td>
                    <td className="px-4 py-2 text-right text-gray-700">{r.articles_total}</td>
                    <td className="px-4 py-2">
                      {r.timed_out ? (
                        <span className="text-xs bg-yellow-50 text-yellow-700 px-1.5 py-0.5 rounded font-medium">Timeout</span>
                      ) : r.sources_failed > 0 ? (
                        <span className="text-xs bg-orange-50 text-orange-700 px-1.5 py-0.5 rounded font-medium">Partial</span>
                      ) : (
                        <span className="text-xs bg-green-50 text-green-700 px-1.5 py-0.5 rounded font-medium">OK</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Sources */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="p-4 border-b border-gray-200">
          <h3 className="text-sm font-semibold text-gray-700">Sources</h3>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-500">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Domain</th>
              <th className="px-4 py-2 font-medium text-right">Articles</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sources.map((s: any) => (
              <tr key={s.name} className="hover:bg-gray-50">
                <td className="px-4 py-2 font-medium text-gray-800">{s.name}</td>
                <td className="px-4 py-2 text-gray-500">{s.domain}</td>
                <td className="px-4 py-2 text-right text-gray-700">{s.article_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
