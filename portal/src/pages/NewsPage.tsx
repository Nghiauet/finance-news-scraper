import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  Search, X, Eye, RefreshCw, ChevronDown, ChevronRight, ChevronLeft,
  Loader2, ExternalLink,
} from "lucide-react"
import {
  useNewsList, useAdminSources, usePreviewScrape, useRefreshSource,
  type Language,
} from "@/api/hooks"
import { useToast } from "@/lib/toast-context"
import {
  Card, CardHeader, PageHeader, ErrorState, EmptyState, Button, Badge,
  IconButton, Field, inputClass, SkeletonRows, TableScroll, thClass, tdClass,
} from "@/components/ui"

const PAGE_SIZE = 20

const selectClass =
  "rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-fg focus:border-accent focus:outline-none"

export default function NewsPage() {
  const [source, setSource] = useState("")
  const [sort, setSort] = useState("newest")
  const [searchInput, setSearchInput] = useState("")
  const [q, setQ] = useState<string | undefined>()
  const [language, setLanguage] = useState<Language>(
    () => (localStorage.getItem("news.language") as Language) || "vi",
  )

  // The API paginates forward only, so remember the cursor for each page to make
  // Previous possible. Index 0 is the first page (no cursor).
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined])
  const [page, setPage] = useState(0)

  const [showPreview, setShowPreview] = useState(false)
  const [previewSource, setPreviewSource] = useState("")
  const [previewLimit, setPreviewLimit] = useState(5)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const toast = useToast()
  const { data: sourcesData } = useAdminSources()
  const { data, isLoading, isFetching, error, refetch } = useNewsList(
    source || undefined, PAGE_SIZE, cursors[page], sort, q, language,
  )
  const previewMut = usePreviewScrape()
  const refreshMut = useRefreshSource()

  const sources: { name: string; domain: string }[] = sourcesData?.data || []
  const articles: any[] = data?.data || []
  const pagination = data?.pagination
  const previewArticles: any[] = previewMut.data?.data || []

  function resetPaging() {
    setCursors([undefined])
    setPage(0)
  }

  // Debounce the search box, and restart paging whenever the query changes.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(searchInput.trim() || undefined)
      resetPaging()
    }, 400)
    return () => clearTimeout(timer)
  }, [searchInput])

  function goNext() {
    const next = pagination?.next_cursor
    if (!next) return
    setCursors((prev) => {
      const copy = prev.slice(0, page + 1)
      copy.push(next)
      return copy
    })
    setPage((p) => p + 1)
  }

  function resetFilters() {
    setSource("")
    setSort("newest")
    setSearchInput("")
    setQ(undefined)
    resetPaging()
  }

  function handlePreview() {
    if (!previewSource) return
    setExpanded(new Set())
    previewMut.mutate(
      { source: previewSource, limit: previewLimit },
      {
        onSuccess: (resp) => {
          const n = resp?.data?.length ?? 0
          if (n === 0) toast.warn(`${previewSource} returned no articles. Its page layout may have changed.`)
          else toast.success(`Previewed ${n} article${n === 1 ? "" : "s"} from ${previewSource}. Nothing was cached.`)
        },
        onError: (err) => toast.error((err as Error).message),
      },
    )
  }

  function handleRefreshSource() {
    if (!previewSource) return
    if (!confirm(`Scrape "${previewSource}" and write the results to the cache?`)) return
    refreshMut.mutate(previewSource, {
      onSuccess: (resp) => toast.success(`${previewSource}: ${resp?.data?.count ?? 0} articles cached.`),
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function toggleExpand(idx: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const total = pagination?.total ?? 0
  const rangeStart = total === 0 ? 0 : page * PAGE_SIZE + 1
  const rangeEnd = page * PAGE_SIZE + articles.length
  const filtered = !!q || !!source || sort !== "newest"

  return (
    <div className="space-y-4">
      <PageHeader title="News" hint="Articles currently served by the API.">
        <Button onClick={() => setShowPreview((v) => !v)} variant={showPreview ? "primary" : "secondary"}>
          <Eye size={14} aria-hidden /> Preview a source
        </Button>
      </PageHeader>

      {/* Toolbar — wraps to its own rows on narrow screens instead of overflowing */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Search size={14} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-subtle" aria-hidden />
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search title, summary or ticker"
            aria-label="Search articles"
            className={`${inputClass} pl-8`}
          />
          {searchInput && (
            <button
              onClick={() => setSearchInput("")}
              aria-label="Clear search"
              className="absolute top-1/2 right-2 -translate-y-1/2 text-subtle hover:text-fg"
            >
              <X size={14} aria-hidden />
            </button>
          )}
        </div>

        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value); resetPaging() }}
          aria-label="Sort order"
          className={selectClass}
        >
          <option value="newest">Newest published</option>
          <option value="oldest">Oldest published</option>
          <option value="recent">Recently scraped</option>
        </select>

        <select
          value={source}
          onChange={(e) => { setSource(e.target.value); resetPaging() }}
          aria-label="Filter by source"
          className={selectClass}
        >
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.name} value={s.name}>{s.name}</option>
          ))}
        </select>

        <select
          value={language}
          onChange={(e) => {
            const next = e.target.value as Language
            setLanguage(next)
            localStorage.setItem("news.language", next)
            resetPaging()
          }}
          aria-label="Response language"
          className={selectClass}
        >
          <option value="vi">Tiếng Việt</option>
          <option value="en">English</option>
        </select>

        {filtered && (
          <Button variant="ghost" onClick={resetFilters}>Clear filters</Button>
        )}
      </div>

      {/* Preview panel */}
      {showPreview && (
        <Card>
          <CardHeader
            title="Preview a source"
            hint="Scrapes live and shows what the model extracts, without writing to the cache."
          />
          <div className="space-y-4 p-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[200px] flex-1">
                <Field label="Source">
                  <select
                    value={previewSource}
                    onChange={(e) => setPreviewSource(e.target.value)}
                    className={`${inputClass} appearance-none`}
                  >
                    <option value="">Choose a source…</option>
                    {sources.map((s) => (
                      <option key={s.name} value={s.name}>{s.name} — {s.domain}</option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="w-24">
                <Field label="Articles">
                  <input
                    type="number" min={1} max={10} value={previewLimit}
                    onChange={(e) => setPreviewLimit(Math.min(10, Math.max(1, parseInt(e.target.value) || 1)))}
                    className={`${inputClass} tnum`}
                  />
                </Field>
              </div>
              <div className="flex gap-2">
                <Button variant="primary" onClick={handlePreview} disabled={!previewSource || previewMut.isPending}>
                  {previewMut.isPending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Eye size={14} aria-hidden />}
                  {previewMut.isPending ? "Scraping…" : "Preview"}
                </Button>
                <Button onClick={handleRefreshSource} disabled={!previewSource || refreshMut.isPending}>
                  <RefreshCw size={14} className={refreshMut.isPending ? "animate-spin" : ""} aria-hidden />
                  {refreshMut.isPending ? "Scraping…" : "Scrape and cache"}
                </Button>
              </div>
            </div>

            {previewMut.isPending && <SkeletonRows rows={3} />}

            {previewArticles.length > 0 && (
              <div className="divide-y divide-line overflow-hidden rounded-lg border border-line">
                {previewArticles.map((a, idx) => {
                  const open = expanded.has(idx)
                  return (
                    <div key={idx}>
                      <button
                        onClick={() => toggleExpand(idx)}
                        aria-expanded={open}
                        className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-surface-2"
                      >
                        <span className="mt-0.5 shrink-0 text-subtle" aria-hidden>
                          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium text-fg">{a.title || "(no title)"}</span>
                            {a.is_relevant === false && <Badge tone="warn">Not finance</Badge>}
                          </span>
                          {a.summary && <span className="mt-0.5 line-clamp-2 block text-xs text-muted">{a.summary}</span>}
                          <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-subtle">
                            <span>{a.source}</span>
                            {a.published_at && <span className="tnum">{new Date(a.published_at).toLocaleString("vi-VN")}</span>}
                            {(a.tickers || []).map((t: string) => (
                              <Badge key={t} tone="accent">{t}</Badge>
                            ))}
                          </span>
                        </span>
                      </button>
                      {open && (
                        <div className="px-3 pb-3 pl-10">
                          <pre className="max-h-72 overflow-auto rounded-lg bg-surface-2 p-3 text-xs whitespace-pre-wrap text-fg">
                            {a.content || "(no content)"}
                          </pre>
                          {a.url && (
                            <a
                              href={a.url} target="_blank" rel="noopener noreferrer"
                              className="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                            >
                              Open original <ExternalLink size={11} aria-hidden />
                            </a>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </Card>
      )}

      {error ? (
        <ErrorState title="Couldn't load articles" error={error} onRetry={() => refetch()} />
      ) : (
        <Card>
          <CardHeader
            title="Articles"
            hint={total > 0 ? `Showing ${rangeStart}–${rangeEnd} of ${total}` : undefined}
            actions={isFetching ? <Loader2 size={14} className="animate-spin text-subtle" aria-label="Refreshing" /> : undefined}
          />
          {isLoading ? (
            <div className="p-4"><SkeletonRows rows={8} /></div>
          ) : articles.length === 0 ? (
            <EmptyState
              title={q ? `Nothing matches “${q}”` : "No articles cached"}
              hint={
                q
                  ? "Try a shorter query, or clear the filters."
                  : language === "en"
                    ? "English translations appear once the scraper has re-processed each article. Try Tiếng Việt."
                    : "Run a scrape from the Dashboard to populate the feed."
              }
              action={filtered ? <Button onClick={resetFilters}>Clear filters</Button> : undefined}
            />
          ) : (
            <TableScroll>
              <table className="w-full">
                <thead className="bg-surface-2">
                  <tr>
                    <th scope="col" className={thClass}>Title</th>
                    <th scope="col" className={`${thClass} w-32`}>Source</th>
                    <th scope="col" className={`${thClass} w-36`}>Published</th>
                    <th scope="col" className={`${thClass} w-32`}>Tickers</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {articles.map((a) => (
                    <tr key={a.id} className="hover:bg-surface-2">
                      <td className="px-4 py-2.5">
                        <Link
                          to={`/news/${a.id}${language !== "vi" ? `?language=${language}` : ""}`}
                          className="text-sm font-medium text-accent hover:underline"
                        >
                          {a.title || "(no title)"}
                        </Link>
                        {a.summary && <p className="mt-0.5 line-clamp-1 text-xs text-subtle">{a.summary}</p>}
                      </td>
                      <td className={`${tdClass} text-muted`}>{a.source}</td>
                      <td className={`${tdClass} tnum text-xs text-muted`}>
                        {a.published_at
                          ? new Date(a.published_at).toLocaleString(language === "en" ? "en-US" : "vi-VN")
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {(a.tickers || []).map((t: string) => (
                            <Badge key={t} tone="accent">{t}</Badge>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          )}

          {articles.length > 0 && (
            <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3">
              <p className="tnum text-xs text-subtle">
                Page {page + 1}
                {total > 0 && ` · ${rangeStart}–${rangeEnd} of ${total}`}
              </p>
              <div className="flex items-center gap-2">
                <IconButton
                  label="Previous page"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  className="border border-line"
                >
                  <ChevronLeft size={15} aria-hidden />
                </IconButton>
                <IconButton
                  label="Next page"
                  disabled={!pagination?.has_more}
                  onClick={goNext}
                  className="border border-line"
                >
                  <ChevronRight size={15} aria-hidden />
                </IconButton>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
