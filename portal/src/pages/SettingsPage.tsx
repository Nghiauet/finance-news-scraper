import { useMemo, useState } from "react"
import { Save, RotateCcw, Trash2, Loader2, AlertTriangle } from "lucide-react"
import { useSettings, useUpdateSettings, useResetSettings, usePurgeCache } from "@/api/hooks"
import { useToast } from "@/lib/toast-context"
import {
  Card, CardHeader, PageHeader, PageSkeleton, ErrorState, Button, Badge,
  TableScroll, thClass, tdClass, inputClass,
} from "@/components/ui"

interface SettingRow {
  name: string
  value: number
  default: number
  source: string
  type: string
  min?: number
}

/** Plain-language name and purpose. The raw key stays visible underneath. */
const COPY: Record<string, { label: string; help: string }> = {
  articles_per_source: {
    label: "Articles per source",
    help: "How many articles each source contributes per scrape cycle.",
  },
  max_total_news: {
    label: "Max articles in API responses",
    help: "Upper bound on the news list. 0 means no limit.",
  },
  llm_call_delay: {
    label: "Delay between LLM calls",
    help: "Seconds to wait between calls, to stay inside provider rate limits.",
  },
  llm_max_input_chars: {
    label: "Max input characters",
    help: "Article text is truncated to this length before being sent to the model.",
  },
  llm_max_output_tokens: {
    label: "Max output tokens",
    help: "Too low and the model returns truncated JSON. Bilingual output needs roughly double.",
  },
  refresh_timeout: {
    label: "Refresh timeout",
    help: "Seconds a full scrape cycle may run before remaining sources are skipped.",
  },
  cache_ttl_hours: {
    label: "Cache lifetime",
    help: "Hours before cached articles, LLM results and news lists expire.",
  },
}

export default function SettingsPage() {
  const { data, isLoading, error, refetch } = useSettings()
  const updateMut = useUpdateSettings()
  const resetMut = useResetSettings()
  const purgeMut = usePurgeCache()
  const toast = useToast()

  /**
   * Only the fields the user has actually touched are held in state; every other
   * input reads straight through to the server value.
   *
   * Mirroring the whole payload into state on load was the source of a real bug:
   * after "Reset to defaults" the copy went stale and kept showing the old
   * overrides. An overlay can't go stale — clearing it *is* showing the truth.
   */
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [invalid, setInvalid] = useState<Set<string>>(new Set())

  const settings: SettingRow[] = useMemo(() => data?.data || [], [data])

  const valueOf = (s: SettingRow) => edits[s.name] ?? String(s.value)
  const isDirty = (s: SettingRow) => edits[s.name] !== undefined && edits[s.name] !== String(s.value)

  const dirty = useMemo(
    () => settings.filter((s) => edits[s.name] !== undefined && edits[s.name] !== String(s.value)),
    [settings, edits],
  )

  if (isLoading) return <PageSkeleton />
  if (error) return <ErrorState title="Couldn't load settings" error={error} onRetry={() => refetch()} />

  function handleSave() {
    // Send only what changed; the API treats the body as a partial update.
    const payload: Record<string, number> = {}
    const bad = new Set<string>()
    for (const s of dirty) {
      const num = s.type === "float" ? parseFloat(edits[s.name]) : parseInt(edits[s.name], 10)
      // A cleared field parses to NaN, which JSON-encodes as null and the API
      // rejects with a type error — catch it here with a pointed message.
      if (!Number.isFinite(num) || (s.min !== undefined && num < s.min)) {
        bad.add(s.name)
        continue
      }
      payload[s.name] = num
    }
    setInvalid(bad)
    if (bad.size > 0) {
      toast.error(`Check the value for: ${[...bad].map((n) => COPY[n]?.label || n).join(", ")}`)
      return
    }
    updateMut.mutate(payload, {
      onSuccess: () => {
        setEdits({})
        toast.success(`Saved ${Object.keys(payload).length} setting${Object.keys(payload).length === 1 ? "" : "s"}`)
      },
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleReset() {
    if (!confirm("Reset every setting to its default? Your overrides will be discarded.")) return
    setInvalid(new Set())
    resetMut.mutate(undefined, {
      onSuccess: () => {
        setEdits({})
        toast.success("Settings reset to defaults")
      },
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleRevert() {
    setEdits({})
    setInvalid(new Set())
  }

  function handlePurge() {
    if (
      !confirm(
        "Delete every cached article, LLM result and news list, then rescrape from scratch?\n\n" +
          "This runs an LLM call for every article and can take a long while.",
      )
    )
      return
    purgeMut.mutate(undefined, {
      onSuccess: (resp) => {
        const p = resp?.data?.purged
        toast.success(
          `Purged ${p?.articles ?? 0} articles, ${p?.summaries ?? 0} LLM results, ${p?.news ?? 0} news lists. Rescrape started.`,
        )
      },
      onError: (err) => toast.error((err as Error).message),
    })
  }

  const saving = updateMut.isPending || resetMut.isPending

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" hint="Runtime configuration. Overrides are stored in Redis and apply to the next cycle.">
        {dirty.length > 0 && (
          <>
            <Badge tone="warn">{dirty.length} unsaved</Badge>
            <Button onClick={handleRevert} disabled={saving}>Revert</Button>
          </>
        )}
        <Button onClick={handleReset} disabled={saving}>
          <RotateCcw size={14} aria-hidden /> Reset to defaults
        </Button>
        <Button variant="primary" onClick={handleSave} disabled={saving || dirty.length === 0}>
          {saving ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Save size={14} aria-hidden />}
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </PageHeader>

      <Card>
        <CardHeader
          title="Runtime configuration"
          hint="A value marked env comes from .env or the built-in default; redis means you've overridden it here."
        />
        <TableScroll>
          <table className="w-full">
            <thead className="bg-surface-2">
              <tr>
                <th scope="col" className={thClass}>Setting</th>
                <th scope="col" className={`${thClass} w-40`}>Value</th>
                <th scope="col" className={`${thClass} w-24 text-right`}>Default</th>
                <th scope="col" className={`${thClass} w-24`}>Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {settings.map((s) => {
                const copy = COPY[s.name]
                const rowDirty = isDirty(s)
                const isBad = invalid.has(s.name)
                return (
                  <tr key={s.name} className="align-top hover:bg-surface-2">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-fg">{copy?.label || s.name}</span>
                        {rowDirty && <span className="h-1.5 w-1.5 rounded-full bg-warn" title="Unsaved change" />}
                      </div>
                      {copy && <p className="mt-0.5 max-w-prose text-xs text-muted">{copy.help}</p>}
                      <p className="tnum mt-1 text-xs text-subtle">
                        {s.name}
                        {s.min !== undefined && ` · min ${s.min}`}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <input
                        type="number"
                        inputMode="decimal"
                        step={s.type === "float" ? "0.1" : "1"}
                        min={s.min}
                        aria-label={copy?.label || s.name}
                        aria-invalid={isBad || undefined}
                        value={valueOf(s)}
                        onChange={(e) => {
                          setEdits((prev) => ({ ...prev, [s.name]: e.target.value }))
                          if (isBad) {
                            setInvalid((prev) => {
                              const next = new Set(prev)
                              next.delete(s.name)
                              return next
                            })
                          }
                        }}
                        className={`${inputClass} tnum ${isBad ? "border-danger" : ""}`}
                      />
                      {isBad && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-danger">
                          <AlertTriangle size={11} aria-hidden />
                          {s.min !== undefined ? `Must be ${s.min} or more` : "Enter a number"}
                        </p>
                      )}
                    </td>
                    <td className={`${tdClass} tnum text-right text-subtle`}>{s.default}</td>
                    <td className="px-4 py-3">
                      <Badge tone={s.source === "redis" ? "accent" : "neutral"}>{s.source}</Badge>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </TableScroll>
      </Card>

      <Card className="border-danger/40">
        <CardHeader title="Purge and rescrape" hint="Only useful when cached output is wrong and you want it rebuilt." />
        <div className="flex flex-wrap items-center justify-between gap-4 p-4">
          <p className="max-w-prose text-sm text-muted">
            Deletes every cached article, LLM result and news list, then immediately rescrapes all
            sources. Every article goes through the model again, so expect a long run and a
            proportional token bill.
          </p>
          <Button variant="danger" onClick={handlePurge} disabled={purgeMut.isPending} className="shrink-0">
            {purgeMut.isPending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Trash2 size={14} aria-hidden />}
            {purgeMut.isPending ? "Purging…" : "Purge and rescrape"}
          </Button>
        </div>
      </Card>
    </div>
  )
}
