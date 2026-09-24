import {
  Newspaper, Globe, Cpu, Database, CheckCircle2, XCircle, AlertTriangle,
  RefreshCw, Loader2,
} from "lucide-react"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts"
import { useAdminStats, useAdminCron, useRefreshAll, useRefreshStatus } from "@/api/hooks"
import { useChartColors } from "@/lib/theme"
import { useToast } from "@/lib/toast-context"
import StatsCard from "@/components/StatsCard"
import {
  Card, CardHeader, PageHeader, PageSkeleton, ErrorState, EmptyState, Button,
  Badge, StatusDot, Metric, TableScroll, thClass, tdClass,
} from "@/components/ui"

function formatCronTime(ts: number) {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

interface SourceRow {
  name: string
  domain: string
  article_count: number
  last_scraped_at?: string | null
}

/** Compact age, e.g. "14 min ago" / "3.5h ago" / "2d ago". */
function relTime(iso?: string | null): string {
  if (!iso) return "\u2014"
  const ms = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(ms)) return "\u2014"
  const mins = Math.round(ms / 60_000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins} min ago`
  const hours = ms / 3_600_000
  if (hours < 24) return `${hours < 10 ? hours.toFixed(1) : Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

/**
 * How healthy a source looks, judged by when it last produced a *new* article.
 *
 * Article count alone hides a dying source: cached entries keep the list looking
 * full until they expire, which is how kinhtechungkhoan sat dead for two weeks
 * behind a plausible-looking number. Thresholds derive from the cache TTL so they
 * stay correct if cache_ttl_hours changes.
 *
 * A healthy source gets no badge — colour stays reserved for what needs action.
 */
function freshness(
  s: SourceRow,
  ttlHours: number,
): { tone: "ok" | "warn" | "danger"; label: string | null } {
  if (!s.article_count) return { tone: "danger", label: "No data" }
  if (!s.last_scraped_at) return { tone: "warn", label: "Unknown" }
  const hours = (Date.now() - new Date(s.last_scraped_at).getTime()) / 3_600_000
  if (!Number.isFinite(hours)) return { tone: "warn", label: "Unknown" }
  if (hours >= ttlHours) return { tone: "danger", label: "Stale" }
  if (hours >= ttlHours / 2) return { tone: "warn", label: "Quiet" }
  return { tone: "ok", label: null }
}

function runTone(run: { timed_out?: boolean; sources_failed?: number }) {
  if (run.timed_out) return { tone: "warn" as const, label: "Timed out", Icon: AlertTriangle }
  if ((run.sources_failed ?? 0) > 0) return { tone: "danger" as const, label: "Partial", Icon: XCircle }
  return { tone: "ok" as const, label: "Complete", Icon: CheckCircle2 }
}

export default function DashboardPage() {
  const { data, isLoading, error, refetch } = useAdminStats()
  const { data: cronData } = useAdminCron()
  const refreshAllMut = useRefreshAll()
  const { data: statusData } = useRefreshStatus()
  const c = useChartColors()
  const toast = useToast()

  const isRefreshing = statusData?.data?.running === true

  if (isLoading) return <PageSkeleton />
  if (error) return <ErrorState title="Couldn't load dashboard" error={error} onRetry={() => refetch()} />

  const d = data?.data
  const cache = d?.cache || {}
  const totals = d?.llm_totals || {}
  const sources: SourceRow[] = d?.sources || []

  // Oldest-first for the chart (time reads left to right); the history table
  // below reverses it again so the newest run is on top.
  const cronRuns: any[] = (cronData?.data?.runs || []).slice().reverse()
  const lastRun = cronRuns.length ? cronRuns[cronRuns.length - 1] : null
  const durationChart = cronRuns.map((r) => ({
    time: formatCronTime(r.started_at),
    duration: r.duration_s,
    articles: r.articles_total,
  }))

  const errorCount = totals.error_count ?? 0
  const ttlHours = (cache.ttl_config?.cache_ttl_seconds ?? 43_200) / 3600
  const graded = sources.map((s) => ({ ...s, health: freshness(s, ttlHours) }))
  const emptySources = graded.filter((s) => s.health.label === "No data").length
  const attentionSources = graded.filter((s) => s.health.tone !== "ok").length

  function handleRefresh() {
    if (!confirm("Scrape every source for new articles now? This is the same work the 30-minute cycle does.")) return
    refreshAllMut.mutate(undefined, {
      onSuccess: () => toast.success("Refresh started. Progress shows in the sidebar."),
      onError: (err) => toast.error((err as Error).message),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" hint="Pipeline health at a glance.">
        <Button variant="primary" onClick={handleRefresh} disabled={isRefreshing || refreshAllMut.isPending}>
          {isRefreshing || refreshAllMut.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          ) : (
            <RefreshCw size={14} aria-hidden />
          )}
          {isRefreshing ? "Scraping…" : "Run scrape now"}
        </Button>
      </PageHeader>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Cached articles"
          value={(cache.article_count ?? 0).toLocaleString()}
          icon={<Newspaper size={18} />}
        />
        <StatsCard
          title="Sources with data"
          value={`${cache.news_sources ?? 0} / ${sources.length}`}
          tone={emptySources > 0 ? "danger" : attentionSources > 0 ? "warn" : "ok"}
          subtitle={
            emptySources > 0
              ? `${emptySources} with no data`
              : attentionSources > 0
                ? `${attentionSources} going quiet`
                : "all fresh"
          }
          icon={<Globe size={18} />}
        />
        <StatsCard
          title="Tokens used"
          value={(totals.total_tokens ?? 0).toLocaleString()}
          subtitle={`${(totals.call_count ?? 0).toLocaleString()} calls`}
          icon={<Cpu size={18} />}
        />
        <StatsCard
          title="LLM errors"
          value={errorCount.toLocaleString()}
          tone={errorCount > 0 ? "danger" : "ok"}
          subtitle={errorCount > 0 ? "see LLM Usage" : "none recorded"}
          icon={<Database size={18} />}
        />
      </div>

      <Card>
        <CardHeader
          title="Last scrape cycle"
          hint="Runs automatically every 30 minutes."
          actions={
            isRefreshing ? (
              <span className="flex items-center gap-1.5 text-xs font-medium text-accent">
                <StatusDot tone="accent" pulse /> in progress
              </span>
            ) : lastRun ? (
              <Badge tone={runTone(lastRun).tone}>{runTone(lastRun).label}</Badge>
            ) : undefined
          }
        />
        {!lastRun ? (
          <EmptyState
            title="No cycle has finished yet"
            hint="The first run starts when the API boots. Give it a few minutes, or start one now."
            action={<Button variant="primary" onClick={handleRefresh}>Run scrape now</Button>}
          />
        ) : (
          <dl className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-5">
            <Metric label="Started" value={formatCronTime(lastRun.started_at)} />
            <Metric label="Duration" value={`${lastRun.duration_s}s`} />
            <Metric label="Sources" value={`${lastRun.sources_ok} / ${lastRun.sources_total}`} />
            <Metric label="Articles" value={(lastRun.articles_total ?? 0).toLocaleString()} />
            <Metric
              label="Failed"
              value={
                <span className={lastRun.sources_failed > 0 ? "text-danger" : "text-ok"}>
                  {lastRun.sources_failed}
                </span>
              }
            />
          </dl>
        )}
      </Card>

      {durationChart.length > 1 && (
        <Card>
          <CardHeader title="Cycle duration" hint="Seconds per run. A rising line usually means a slow source or a slow model." />
          {/* overflow-hidden: recharts parks its tooltip wrapper at a stale
              absolute position while hidden, which widened the whole document on
              narrow viewports. Active tooltips stay inside the chart, so clipping
              only removes the off-screen artifact. */}
          <div className="overflow-hidden p-4 pt-2">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={durationChart} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 11, fill: c.muted }} stroke={c.line} />
                <YAxis tick={{ fontSize: 11, fill: c.muted }} stroke={c.line} unit="s" width={48} />
                <Tooltip
                  contentStyle={{
                    background: c.surface,
                    border: `1px solid ${c.line}`,
                    borderRadius: 8,
                    fontSize: 12,
                    color: c.fg,
                  }}
                  labelStyle={{ color: c.muted }}
                  formatter={(v) => [`${v}s`, "Duration"]}
                />
                <Line
                  type="monotone"
                  dataKey="duration"
                  stroke={c.accent}
                  strokeWidth={2}
                  dot={{ r: 2, fill: c.accent }}
                  activeDot={{ r: 4 }}
                  name="Duration"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {cronRuns.length > 0 && (
        <Card>
          <CardHeader title="Cycle history" hint={`${cronRuns.length} most recent runs, newest first.`} />
          <TableScroll className="max-h-72 overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-surface-2">
                <tr>
                  <th scope="col" className={thClass}>Started</th>
                  <th scope="col" className={`${thClass} text-right`}>Duration</th>
                  <th scope="col" className={`${thClass} text-right`}>Sources</th>
                  <th scope="col" className={`${thClass} text-right`}>Articles</th>
                  <th scope="col" className={thClass}>Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {[...cronRuns].reverse().map((r, i) => {
                  const { tone, label } = runTone(r)
                  return (
                    <tr key={i} className="hover:bg-surface-2">
                      <td className={`${tdClass} tnum whitespace-nowrap text-muted`}>{formatCronTime(r.started_at)}</td>
                      <td className={`${tdClass} tnum text-right`}>{r.duration_s}s</td>
                      <td className={`${tdClass} tnum text-right`}>
                        <span className={r.sources_failed > 0 ? "text-warn" : "text-ok"}>{r.sources_ok}</span>
                        <span className="text-subtle">/{r.sources_total}</span>
                      </td>
                      <td className={`${tdClass} tnum text-right`}>{r.articles_total}</td>
                      <td className="px-4 py-2"><Badge tone={tone}>{label}</Badge></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Sources"
          hint={`${sources.length} configured \u00b7 flagged after ${Math.round(ttlHours / 2)}h without a new article`}
        />
        <TableScroll>
          <table className="w-full">
            <thead className="bg-surface-2">
              <tr>
                <th scope="col" className={thClass}>Name</th>
                <th scope="col" className={thClass}>Domain</th>
                <th scope="col" className={`${thClass} text-right`}>Articles</th>
                <th scope="col" className={`${thClass} w-36`}>Newest article</th>
                <th scope="col" className={`${thClass} w-24`}>State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {graded.map((s) => (
                <tr key={s.name} className="hover:bg-surface-2">
                  <td className={`${tdClass} font-medium`}>{s.name}</td>
                  <td className={`${tdClass} text-muted`}>{s.domain}</td>
                  <td className={`${tdClass} tnum text-right`}>
                    {s.article_count ? (
                      s.article_count.toLocaleString()
                    ) : (
                      <span className="text-danger">0</span>
                    )}
                  </td>
                  <td
                    className={`${tdClass} tnum text-xs ${
                      s.health.tone === "danger"
                        ? "text-danger"
                        : s.health.tone === "warn"
                          ? "text-warn"
                          : "text-muted"
                    }`}
                    title={s.last_scraped_at || undefined}
                  >
                    {relTime(s.last_scraped_at)}
                  </td>
                  <td className="px-4 py-2">
                    {s.health.label && <Badge tone={s.health.tone}>{s.health.label}</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </Card>
    </div>
  )
}
