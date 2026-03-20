import { Newspaper, Globe, Cpu, Database } from "lucide-react"
import { useAdminStats } from "@/api/hooks"
import StatsCard from "@/components/StatsCard"

export default function DashboardPage() {
  const { data, isLoading, error } = useAdminStats()

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-500">Error: {(error as Error).message}</div>

  const d = data?.data
  const cache = d?.cache || {}
  const totals = d?.llm_totals || {}
  const sources = d?.sources || []

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-800">Dashboard</h2>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Cached Articles"
          value={cache.article_count ?? 0}
          icon={<Newspaper size={20} />}
        />
        <StatsCard
          title="Active Sources"
          value={`${cache.news_sources ?? 0} / ${sources.length}`}
          icon={<Globe size={20} />}
        />
        <StatsCard
          title="Total Tokens"
          value={(totals.total_tokens ?? 0).toLocaleString()}
          icon={<Cpu size={20} />}
          subtitle={`${(totals.call_count ?? 0).toLocaleString()} calls`}
        />
        <StatsCard
          title="Redis Memory"
          value={`${cache.memory_used_mb ?? 0} MB`}
          icon={<Database size={20} />}
        />
      </div>

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
