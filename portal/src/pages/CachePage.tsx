import { Database, CheckCircle, XCircle } from "lucide-react"
import { useAdminCache } from "@/api/hooks"
import StatsCard from "@/components/StatsCard"

export default function CachePage() {
  const { data, isLoading, error } = useAdminCache()

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-500">Error: {(error as Error).message}</div>

  const d = data?.data || {}
  const ttl = d.ttl_config || {}
  const sourceCounts = d.source_counts || {}

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-800">Cache</h2>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Status"
          value={d.connected ? "Connected" : "Disconnected"}
          icon={d.connected ? <CheckCircle size={20} className="text-green-500" /> : <XCircle size={20} className="text-red-500" />}
        />
        <StatsCard title="Articles" value={d.article_count ?? 0} icon={<Database size={20} />} />
        <StatsCard title="LLM Results" value={d.summary_count ?? 0} icon={<Database size={20} />} />
        <StatsCard title="Memory" value={`${d.memory_used_mb ?? 0} MB`} icon={<Database size={20} />} />
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">TTL Configuration</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
          <div>
            <span className="text-gray-400">Article Cache</span>
            <p className="font-medium text-gray-800">{formatTTL(ttl.article_seconds)}</p>
          </div>
          <div>
            <span className="text-gray-400">Summary Cache</span>
            <p className="font-medium text-gray-800">{formatTTL(ttl.summary_seconds)}</p>
          </div>
          <div>
            <span className="text-gray-400">News List Cache</span>
            <p className="font-medium text-gray-800">{formatTTL(ttl.news_seconds)}</p>
          </div>
        </div>
      </div>

      {Object.keys(sourceCounts).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="p-4 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">Articles per Source ({d.news_sources} sources)</h3>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium text-right">Articles</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {Object.entries(sourceCounts)
                .sort(([, a], [, b]) => (b as number) - (a as number))
                .map(([name, count]) => (
                  <tr key={name} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-medium text-gray-800">{name}</td>
                    <td className="px-4 py-2 text-right text-gray-700">{(count as number)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function formatTTL(seconds?: number): string {
  if (!seconds) return "-"
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0 && m > 0) return `${h}h ${m}m`
  if (h > 0) return `${h}h`
  return `${m}m`
}
