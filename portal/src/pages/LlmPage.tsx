import { useMemo, useState } from "react"
import {
  Cpu, AlertCircle, Plus, Trash2, Zap, Pencil, X, Loader2, Play, CheckCircle2,
} from "lucide-react"
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend,
} from "recharts"
import {
  useAdminLlm, useAddModel, useUpdateModel, useDeleteModel,
  useActivateModel, useTestModel, useAdminErrors,
} from "@/api/hooks"
import { useChartColors } from "@/lib/theme"
import { useToast } from "@/lib/toast-context"
import StatsCard from "@/components/StatsCard"
import {
  Card, CardHeader, PageHeader, PageSkeleton, ErrorState, EmptyState, Button,
  IconButton, Badge, Field, inputClass, TableScroll, thClass, tdClass, Metric,
} from "@/components/ui"

interface ModelForm {
  name: string
  base_url: string
  api_key: string
  model_name: string
}

const emptyForm: ModelForm = { name: "", base_url: "", api_key: "", model_name: "" }

/** Hint for the key field while editing — the stored key arrives masked. */
function keyPlaceholder(mask: string) {
  const tail = mask.replace(/^\*+/, "")
  return tail ? `Leave blank to keep ····${tail}` : "Leave blank to keep current key"
}

function formatBucket(ts: number) {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:00`
}

/** Group LLM calls into hourly buckets. */
function buildTokenTimeline(calls: any[]) {
  if (!calls.length) return []
  const buckets: Record<number, { prompt: number; completion: number }> = {}
  for (const c of calls) {
    const hour = Math.floor(c.timestamp / 3600) * 3600
    buckets[hour] ??= { prompt: 0, completion: 0 }
    buckets[hour].prompt += c.prompt_tokens
    buckets[hour].completion += c.completion_tokens
  }
  return Object.entries(buckets)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([ts, v]) => ({ time: formatBucket(Number(ts)), ...v }))
}

/** Group errors into hourly buckets by category. */
function buildErrorTimeline(errors: any[]) {
  if (!errors.length) return []
  const buckets: Record<number, { llm: number; scrape: number; cron: number }> = {}
  for (const e of errors) {
    const hour = Math.floor(e.ts / 3600) * 3600
    buckets[hour] ??= { llm: 0, scrape: 0, cron: 0 }
    if (e.category in buckets[hour]) buckets[hour][e.category as "llm" | "scrape" | "cron"]++
  }
  return Object.entries(buckets)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([ts, v]) => ({ time: formatBucket(Number(ts)), ...v }))
}

export default function LlmPage() {
  const { data, isLoading, error, refetch } = useAdminLlm()
  const { data: errorsData } = useAdminErrors(24)
  const addMut = useAddModel()
  const updateMut = useUpdateModel()
  const deleteMut = useDeleteModel()
  const activateMut = useActivateModel()
  const testMut = useTestModel()
  const c = useChartColors()
  const toast = useToast()

  const [showAdd, setShowAdd] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<ModelForm>(emptyForm)
  const [keyMask, setKeyMask] = useState("")
  const [testResults, setTestResults] = useState<Record<string, any>>({})

  function closeForm() {
    setShowAdd(false)
    setEditId(null)
    setForm(emptyForm)
    setKeyMask("")
  }

  const d = data?.data
  const calls: any[] = useMemo(() => (d?.recent_calls || []).slice().reverse(), [d])
  const tokenTimeline = useMemo(() => buildTokenTimeline(calls), [calls])
  const errorEvents: any[] = errorsData?.data?.errors || []
  const errorTimeline = useMemo(() => buildErrorTimeline(errorEvents), [errorEvents])

  if (isLoading) return <PageSkeleton />
  if (error) return <ErrorState title="Couldn't load LLM usage" error={error} onRetry={() => refetch()} />

  const active = d?.model || {}
  const totals = d?.totals || {}
  const models: any[] = d?.models || []
  const activeModelId: string = d?.active_model_id || ""
  const formValid = form.name.trim() && form.base_url.trim() && form.model_name.trim()

  function handleAdd() {
    addMut.mutate(form, {
      onSuccess: () => { toast.success(`Added ${form.name}`); closeForm() },
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleUpdate() {
    if (!editId) return
    // Omit the key when left blank so the server keeps the stored one.
    const { api_key, ...rest } = form
    const payload = api_key.trim() ? { ...rest, api_key: api_key.trim() } : rest
    updateMut.mutate({ id: editId, ...payload }, {
      onSuccess: () => { toast.success(`Saved ${form.name}`); closeForm() },
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function startEdit(m: any) {
    setEditId(m.id)
    // api_key arrives masked — start blank rather than sending the mask back.
    setForm({ name: m.name || "", base_url: m.base_url || "", api_key: "", model_name: m.model_name || "" })
    setKeyMask(m.api_key || "")
    setShowAdd(false)
  }

  function handleDelete(id: string, name: string) {
    if (!confirm(`Delete "${name}"? If it's the active model the API falls back to the .env credentials.`)) return
    deleteMut.mutate(id, {
      onSuccess: () => toast.success(`Deleted ${name}`),
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleActivate(id: string, name: string) {
    activateMut.mutate(id, {
      onSuccess: () => toast.success(`${name} is now handling extraction`),
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleTest(id: string) {
    setTestResults((prev) => ({ ...prev, [id]: { loading: true } }))
    testMut.mutate(id, {
      onSuccess: (resp) => setTestResults((prev) => ({ ...prev, [id]: resp?.data })),
      onError: (err) => setTestResults((prev) => ({ ...prev, [id]: { ok: false, error: (err as Error).message } })),
    })
  }

  const errorCount = totals.error_count ?? 0
  const callCount = totals.call_count ?? 0

  return (
    <div className="space-y-6">
      <PageHeader title="LLM usage" hint="Models that extract, summarise and translate each article.">
        <Button
          variant={showAdd ? "primary" : "secondary"}
          onClick={() => { const next = !showAdd; closeForm(); setShowAdd(next) }}
        >
          <Plus size={14} aria-hidden /> Add model
        </Button>
      </PageHeader>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard title="Total tokens" value={(totals.total_tokens ?? 0).toLocaleString()} subtitle={`${callCount.toLocaleString()} calls`} icon={<Cpu size={18} />} />
        <StatsCard title="Prompt tokens" value={(totals.prompt_tokens ?? 0).toLocaleString()} icon={<Cpu size={18} />} />
        <StatsCard title="Completion tokens" value={(totals.completion_tokens ?? 0).toLocaleString()} icon={<Cpu size={18} />} />
        <StatsCard
          title="Errors"
          value={errorCount.toLocaleString()}
          tone={errorCount > 0 ? "danger" : "ok"}
          subtitle={callCount > 0 ? `${((errorCount / (callCount + errorCount)) * 100).toFixed(1)}% of attempts` : "no calls yet"}
          icon={<AlertCircle size={18} />}
        />
      </div>

      {/* Models */}
      <Card>
        <CardHeader
          title="Models"
          hint="One is active at a time. The rest stay configured and ready to switch to."
        />

        {(showAdd || editId) && (
          <div className="border-b border-line bg-surface-2 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-medium text-fg">{editId ? "Edit model" : "Add a model"}</h3>
              <IconButton label="Close form" onClick={closeForm}><X size={15} aria-hidden /></IconButton>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Display name">
                <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="GPT-4o mini" className={inputClass} />
              </Field>
              <Field label="Model name" hint="Exactly as the provider expects it.">
                <input type="text" value={form.model_name} onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                  placeholder="gpt-4o-mini" className={`${inputClass} tnum`} />
              </Field>
              <Field label="Base URL">
                <input type="text" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://api.openai.com/v1" className={`${inputClass} tnum`} />
              </Field>
              <Field label="API key" hint={editId ? "Stored keys are never sent back to the browser." : undefined}>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder={editId ? keyPlaceholder(keyMask) : "sk-…"}
                  autoComplete="new-password"
                  className={inputClass}
                />
              </Field>
            </div>
            <div className="mt-3 flex gap-2">
              <Button
                variant="primary"
                onClick={editId ? handleUpdate : handleAdd}
                disabled={!formValid || (!editId && !form.api_key.trim()) || addMut.isPending || updateMut.isPending}
              >
                {(addMut.isPending || updateMut.isPending) && <Loader2 size={14} className="animate-spin" aria-hidden />}
                {editId ? "Save changes" : "Add model"}
              </Button>
              <Button onClick={closeForm}>Cancel</Button>
            </div>
          </div>
        )}

        {models.length === 0 ? (
          <EmptyState
            title="No models configured"
            hint={`Extraction is using the .env credentials${active.model ? ` (${active.model})` : ""}. Add a model here to manage it from the console and switch without a redeploy.`}
            action={<Button variant="primary" onClick={() => setShowAdd(true)}><Plus size={14} aria-hidden /> Add model</Button>}
          />
        ) : (
          <ul className="divide-y divide-line">
            {models.map((m) => {
              const isActive = m.id === activeModelId
              const tr = testResults[m.id]
              return (
                <li key={m.id} className={`flex flex-wrap items-start gap-3 p-4 ${isActive ? "bg-accent-soft/40" : ""}`}>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-fg">{m.name}</span>
                      {isActive && <Badge tone="accent">In use</Badge>}
                    </div>
                    <p className="tnum mt-0.5 truncate text-xs text-subtle">{m.model_name} · {m.base_url}</p>
                    {m.stats && (
                      <p className="tnum mt-0.5 text-xs text-subtle">
                        {(m.stats.call_count || 0).toLocaleString()} calls ·{" "}
                        {(m.stats.total_tokens || 0).toLocaleString()} tokens
                        {m.stats.error_count ? <span className="text-danger"> · {m.stats.error_count} errors</span> : null}
                      </p>
                    )}
                    {tr && !tr.loading && (
                      <p className={`mt-1 flex items-center gap-1 text-xs ${tr.ok ? "text-ok" : "text-danger"}`}>
                        {tr.ok ? <CheckCircle2 size={12} aria-hidden /> : <AlertCircle size={12} aria-hidden />}
                        {tr.ok ? `Responded in ${tr.latency_ms}ms` : `Test failed: ${tr.error}`}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <IconButton label={`Test ${m.name}`} disabled={tr?.loading} onClick={() => handleTest(m.id)}>
                      {tr?.loading ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Play size={15} aria-hidden />}
                    </IconButton>
                    {!isActive && (
                      <IconButton
                        label={`Use ${m.name} for extraction`}
                        disabled={activateMut.isPending}
                        onClick={() => handleActivate(m.id, m.name)}
                        className="hover:text-ok"
                      >
                        <Zap size={15} aria-hidden />
                      </IconButton>
                    )}
                    <IconButton label={`Edit ${m.name}`} onClick={() => startEdit(m)} className="hover:text-accent">
                      <Pencil size={15} aria-hidden />
                    </IconButton>
                    <IconButton
                      label={`Delete ${m.name}`}
                      disabled={deleteMut.isPending}
                      onClick={() => handleDelete(m.id, m.name)}
                      className="hover:text-danger"
                    >
                      <Trash2 size={15} aria-hidden />
                    </IconButton>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title="Currently extracting" hint="What the scraper calls for every article." />
        <dl className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
          <Metric label="Model" value={active.model || "—"} />
          <Metric label="Endpoint" value={active.base_url || "—"} />
          <Metric label="Label" value={active.name || "—"} />
          <Metric label="Input limit" value={active.max_input_chars ? `${active.max_input_chars.toLocaleString()} chars` : "—"} />
        </dl>
      </Card>

      {tokenTimeline.length > 0 && (
        <Card>
          <CardHeader title="Token use over time" hint="Hourly totals from the last 100 calls." />
          {/* overflow-hidden: recharts leaves its hidden tooltip wrapper parked
              off-screen, which widens the document on narrow viewports. */}
          <div className="overflow-hidden p-4 pt-2">
            <ResponsiveContainer width="100%" height={230}>
              <AreaChart data={tokenTimeline} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 11, fill: c.muted }} stroke={c.line} />
                <YAxis tick={{ fontSize: 11, fill: c.muted }} stroke={c.line} width={56}
                  tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v)} />
                <Tooltip
                  contentStyle={{ background: c.surface, border: `1px solid ${c.line}`, borderRadius: 8, fontSize: 12, color: c.fg }}
                  labelStyle={{ color: c.muted }}
                  formatter={(v) => Number(v).toLocaleString()}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: c.muted }} />
                <Area type="monotone" dataKey="prompt" stackId="1" stroke={c.accent} fill={c.accent} fillOpacity={0.5} name="Prompt" />
                <Area type="monotone" dataKey="completion" stackId="1" stroke={c.ok} fill={c.ok} fillOpacity={0.35} name="Completion" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {errorTimeline.length > 0 && (
        <Card>
          <CardHeader title="Errors in the last 24 hours" hint="Grouped by the stage that failed." />
          {/* overflow-hidden: recharts leaves its hidden tooltip wrapper parked
              off-screen, which widens the document on narrow viewports. */}
          <div className="overflow-hidden p-4 pt-2">
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={errorTimeline} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 11, fill: c.muted }} stroke={c.line} />
                <YAxis tick={{ fontSize: 11, fill: c.muted }} stroke={c.line} allowDecimals={false} width={40} />
                <Tooltip
                  contentStyle={{ background: c.surface, border: `1px solid ${c.line}`, borderRadius: 8, fontSize: 12, color: c.fg }}
                  labelStyle={{ color: c.muted }}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: c.muted }} />
                <Bar dataKey="llm" stackId="a" fill={c.danger} name="Model" />
                <Bar dataKey="scrape" stackId="a" fill={c.warn} name="Scrape" />
                <Bar dataKey="cron" stackId="a" fill={c.muted} name="Cycle" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {calls.length > 0 && (
        <Card>
          <CardHeader title="Recent calls" hint={`${calls.length} most recent, newest first.`} />
          <TableScroll className="max-h-80 overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-surface-2">
                <tr>
                  <th scope="col" className={thClass}>Time</th>
                  <th scope="col" className={`${thClass} text-right`}>Prompt</th>
                  <th scope="col" className={`${thClass} text-right`}>Completion</th>
                  <th scope="col" className={`${thClass} text-right`}>Total</th>
                  <th scope="col" className={`${thClass} text-right`}>Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(d?.recent_calls || []).map((call: any, i: number) => (
                  <tr key={i} className="hover:bg-surface-2">
                    <td className={`${tdClass} tnum whitespace-nowrap text-muted`}>
                      {new Date(call.timestamp * 1000).toLocaleString("vi-VN")}
                    </td>
                    <td className={`${tdClass} tnum text-right`}>{call.prompt_tokens.toLocaleString()}</td>
                    <td className={`${tdClass} tnum text-right`}>{call.completion_tokens.toLocaleString()}</td>
                    <td className={`${tdClass} tnum text-right font-medium`}>{call.total_tokens.toLocaleString()}</td>
                    <td className={`${tdClass} tnum text-right text-muted`}>{(call.latency_ms / 1000).toFixed(1)}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}

      {errorEvents.length > 0 && (
        <Card>
          <CardHeader title="Recent errors" hint={`${errorEvents.length} in the last 24 hours.`} />
          <TableScroll className="max-h-72 overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-surface-2">
                <tr>
                  <th scope="col" className={thClass}>Time</th>
                  <th scope="col" className={thClass}>Stage</th>
                  <th scope="col" className={thClass}>Source</th>
                  <th scope="col" className={thClass}>Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {errorEvents.slice(0, 50).map((e: any, i: number) => (
                  <tr key={i} className="hover:bg-surface-2">
                    <td className={`${tdClass} tnum whitespace-nowrap text-muted`}>
                      {new Date(e.ts * 1000).toLocaleString("vi-VN")}
                    </td>
                    <td className="px-4 py-2">
                      <Badge tone={e.category === "llm" ? "danger" : e.category === "scrape" ? "warn" : "neutral"}>
                        {e.category}
                      </Badge>
                    </td>
                    <td className={`${tdClass} text-muted`}>{e.source || "—"}</td>
                    <td className={`${tdClass} max-w-md truncate text-muted`} title={e.message}>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      )}
    </div>
  )
}
