import { Database, CheckCircle2, XCircle, FileText, Clock } from "lucide-react"
import { useAdminCache } from "@/api/hooks"
import StatsCard from "@/components/StatsCard"
import {
  Card, CardHeader, PageHeader, PageSkeleton, ErrorState, EmptyState,
  TableScroll, thClass, tdClass, Metric,
} from "@/components/ui"

function formatTTL(seconds?: number): string {
  if (!seconds) return "—"
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const parts = [d && `${d}d`, h && `${h}h`, m && `${m}m`].filter(Boolean)
  return parts.length ? parts.join(" ") : `${seconds}s`
}

export default function CachePage() {
  const { data, isLoading, error, refetch } = useAdminCache()

  if (isLoading) return <PageSkeleton />
  if (error) return <ErrorState title="Couldn't load cache stats" error={error} onRetry={() => refetch()} />

  const d = data?.data || {}
  const connected: boolean = !!d.connected
  // One TTL governs all three caches. This panel used to read article_seconds /
  // summary_seconds / news_seconds, which the API has never returned, so every
  // value rendered as a dash.
  const ttlSeconds: number | undefined = d.ttl_config?.cache_ttl_seconds
  const sourceCounts: Record<string, number> = d.source_counts || {}
  const rows = Object.entries(sourceCounts).sort(([, a], [, b]) => b - a)
  const totalListed = rows.reduce((sum, [, n]) => sum + n, 0)

  return (
    <div className="space-y-6">
      <PageHeader title="Cache" hint="Redis contents backing the news API." />

      {!connected && (
        <Card className="border-danger/40 bg-danger-soft p-4">
          <p className="text-sm font-medium text-danger">Redis is unreachable</p>
          <p className="mt-1 text-sm text-muted">
            The API keeps serving from memory where it can, but nothing new is being cached and
            scrape results are being discarded. Check the <code className="tnum">redis</code> container.
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Status"
          value={connected ? "Connected" : "Down"}
          tone={connected ? "ok" : "danger"}
          icon={connected ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
        />
        <StatsCard title="Articles" value={(d.article_count ?? 0).toLocaleString()} icon={<FileText size={18} />} />
        <StatsCard title="LLM results" value={(d.summary_count ?? 0).toLocaleString()} icon={<Database size={18} />} />
        <StatsCard title="Memory" value={`${d.memory_used_mb ?? 0} MB`} icon={<Database size={18} />} />
      </div>

      <Card>
        <CardHeader title="Retention" hint="How long cached entries live before Redis expires them." />
        <dl className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
          <Metric label="Cache TTL" value={formatTTL(ttlSeconds)} sub={ttlSeconds ? `${ttlSeconds.toLocaleString()}s` : undefined} />
          <Metric label="Applies to" value="Articles" sub="article:<url>" />
          <Metric label="Applies to" value="LLM results" sub="summary:<hash>" />
          <Metric label="Applies to" value="News lists" sub="news:<source>" />
        </dl>
      </Card>

      <Card>
        <CardHeader
          title="Articles per source"
          hint={rows.length ? `${rows.length} sources · ${totalListed.toLocaleString()} entries` : undefined}
          actions={
            <span className="flex items-center gap-1.5 text-xs text-subtle">
              <Clock size={12} aria-hidden /> refreshes every 30s
            </span>
          }
        />
        {rows.length === 0 ? (
          <EmptyState
            title="No news lists cached yet"
            hint="The scraper writes one list per source. Run a refresh from the Dashboard, or wait for the next 30-minute cycle."
          />
        ) : (
          <TableScroll>
            <table className="w-full">
              <thead className="bg-surface-2">
                <tr>
                  <th scope="col" className={thClass}>Source</th>
                  <th scope="col" className={`${thClass} text-right`}>Articles</th>
                  <th scope="col" className={`${thClass} w-1/3`}>Share</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map(([name, count]) => (
                  <tr key={name} className="hover:bg-surface-2">
                    <td className={`${tdClass} font-medium`}>{name}</td>
                    <td className={`${tdClass} tnum text-right`}>{count.toLocaleString()}</td>
                    <td className={tdClass}>
                      {/* Relative bar: which sources actually carry the feed. */}
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                        <div
                          className="h-full rounded-full bg-accent"
                          style={{ width: `${totalListed ? (count / rows[0][1]) * 100 : 0}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </Card>
    </div>
  )
}
