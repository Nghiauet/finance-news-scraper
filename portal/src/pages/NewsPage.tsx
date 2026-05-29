import { useState, useEffect } from "react"
import { Link } from "react-router-dom"
import {
  Search, X, Eye, RefreshCw, ChevronDown, ChevronRight,
  CheckCircle, XCircle,
} from "lucide-react"
import {
  useNewsList, useAdminSources, usePreviewScrape, useRefreshSource,
  type Language,
} from "@/api/hooks"

export default function NewsPage() {
  const [source, setSource] = useState<string>("")
  const [cursor, setCursor] = useState<string | undefined>()
  const [sort, setSort] = useState<string>("newest")
  const [searchInput, setSearchInput] = useState("")
  const [q, setQ] = useState<string | undefined>()
  const [language, setLanguage] = useState<Language>(
    () => (localStorage.getItem("news.language") as Language) || "vi",
  )
  const [showPreview, setShowPreview] = useState(false)
  const [previewSource, setPreviewSource] = useState("")
  const [previewLimit, setPreviewLimit] = useState(5)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const { data: sourcesData } = useAdminSources()
  const { data, isLoading, error } = useNewsList(source || undefined, 20, cursor, sort, q, language)
  const previewMut = usePreviewScrape()
  const refreshMut = useRefreshSource()

  const sources: any[] = sourcesData?.data || []
  const articles: any[] = data?.data || []
  const pagination = data?.pagination
  const previewArticles: any[] = previewMut.data?.data || []

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      const trimmed = searchInput.trim()
      setQ(trimmed || undefined)
      setCursor(undefined)
    }, 400)
    return () => clearTimeout(timer)
  }, [searchInput])

  function resetFilters() {
    setSource("")
    setSort("newest")
    setSearchInput("")
    setQ(undefined)
    setCursor(undefined)
  }

  function handlePreview() {
    if (!previewSource) return
    previewMut.mutate({ source: previewSource, limit: previewLimit })
    setExpanded(new Set())
  }

  function handleRefresh() {
    if (!previewSource) return
    if (!confirm(`Refresh "${previewSource}"? This will scrape and write to cache.`)) return
    refreshMut.mutate(previewSource)
  }

  function toggleExpand(idx: number) {
    const next = new Set(expanded)
    if (next.has(idx)) next.delete(idx)
    else next.add(idx)
    setExpanded(next)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">News</h2>
        <div className="flex items-center gap-2">
          {/* Preview toggle */}
          <button
            onClick={() => setShowPreview(!showPreview)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-lg transition-colors ${
              showPreview ? "bg-blue-50 border-blue-300 text-blue-700" : "border-gray-300 hover:bg-gray-50"
            }`}
          >
            <Eye size={14} />
            Preview
          </button>

          {/* Search */}
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search title, ticker..."
              className="pl-8 pr-8 py-1.5 border border-gray-300 rounded-lg text-sm bg-white w-56 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            {searchInput && (
              <button onClick={() => setSearchInput("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                <X size={14} />
              </button>
            )}
          </div>

          {/* Sort */}
          <select
            value={sort}
            onChange={(e) => { setSort(e.target.value); setCursor(undefined) }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white"
          >
            <option value="newest">Newest published</option>
            <option value="oldest">Oldest published</option>
            <option value="recent">Recently scraped</option>
          </select>

          {/* Source filter */}
          <select
            value={source}
            onChange={(e) => { setSource(e.target.value); setCursor(undefined) }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white"
          >
            <option value="">All Sources</option>
            {sources.map((s: any) => (
              <option key={s.name} value={s.name}>{s.name}</option>
            ))}
          </select>

          {/* Language */}
          <select
            value={language}
            onChange={(e) => {
              const next = e.target.value as Language
              setLanguage(next)
              localStorage.setItem("news.language", next)
              setCursor(undefined)
            }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white"
            title="Response language"
          >
            <option value="vi">Tiếng Việt</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>

      {/* Preview Panel */}
      {showPreview && (
        <div className="bg-white rounded-xl border border-blue-200 p-5 space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Source</label>
              <select
                value={previewSource}
                onChange={(e) => setPreviewSource(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select a source...</option>
                {sources.map((s: any) => (
                  <option key={s.name} value={s.name}>{s.name} ({s.domain})</option>
                ))}
              </select>
            </div>
            <div className="w-28">
              <label className="block text-sm font-medium text-gray-700 mb-1">Limit</label>
              <input
                type="number" min={1} max={10} value={previewLimit}
                onChange={(e) => setPreviewLimit(Math.min(10, Math.max(1, parseInt(e.target.value) || 1)))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handlePreview}
                disabled={!previewSource || previewMut.isPending}
                className="flex items-center gap-1.5 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Eye size={14} />
                {previewMut.isPending ? "Scraping..." : "Preview"}
              </button>
              <button
                onClick={handleRefresh}
                disabled={!previewSource || refreshMut.isPending}
                className="flex items-center gap-1.5 px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RefreshCw size={14} className={refreshMut.isPending ? "animate-spin" : ""} />
                {refreshMut.isPending ? "Refreshing..." : "Refresh Source"}
              </button>
            </div>
          </div>

          {previewMut.isError && (
            <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200">
              {(previewMut.error as Error).message}
            </div>
          )}
          {refreshMut.isSuccess && (
            <div className="bg-green-50 text-green-700 text-sm px-4 py-3 rounded-lg border border-green-200 flex items-center gap-2">
              <CheckCircle size={16} />
              Source refreshed! {refreshMut.data?.data?.count ?? 0} articles cached.
            </div>
          )}

          {previewArticles.length > 0 && (
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="p-3 border-b border-gray-200 bg-gray-50">
                <h4 className="text-sm font-semibold text-gray-700">Preview Results ({previewArticles.length} articles)</h4>
              </div>
              <div className="divide-y divide-gray-100 max-h-96 overflow-auto">
                {previewArticles.map((a: any, idx: number) => (
                  <div key={idx}>
                    <div onClick={() => toggleExpand(idx)} className="flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50">
                      <button className="mt-0.5 text-gray-400">
                        {expanded.has(idx) ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </button>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-800 text-sm">{a.title || "(No title)"}</span>
                          {a.is_relevant === false && (
                            <span className="flex items-center gap-0.5 text-xs text-orange-600 bg-orange-50 px-1.5 py-0.5 rounded"><XCircle size={12} /> Not relevant</span>
                          )}
                        </div>
                        {a.summary && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{a.summary}</p>}
                        <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
                          <span>{a.source}</span>
                          {a.published_at && <span>{new Date(a.published_at).toLocaleString("vi-VN")}</span>}
                          {(a.tickers || []).length > 0 && (
                            <div className="flex gap-1">
                              {a.tickers.map((t: string) => (
                                <span key={t} className="bg-blue-50 text-blue-700 px-1 py-0.5 rounded text-xs font-medium">{t}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                    {expanded.has(idx) && (
                      <div className="px-4 pb-4 pl-11">
                        <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 prose prose-sm max-w-none">
                          <pre className="whitespace-pre-wrap font-sans text-sm">{a.content || "(No content)"}</pre>
                        </div>
                        {a.url && (
                          <a href={a.url} target="_blank" rel="noopener noreferrer" className="inline-block mt-2 text-xs text-blue-600 hover:underline">
                            View original article
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Active filters indicator */}
      {(q || source || sort !== "newest") && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>Filters:</span>
          {q && <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">Search: "{q}"</span>}
          {source && <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">Source: {source}</span>}
          {sort !== "newest" && (
            <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
              {sort === "oldest" ? "Oldest first" : "Recently scraped"}
            </span>
          )}
          <button onClick={resetFilters} className="text-gray-400 hover:text-gray-600 underline">Clear all</button>
        </div>
      )}

      {isLoading && <div className="text-gray-500">Loading...</div>}
      {error && <div className="text-red-500">Error: {(error as Error).message}</div>}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-500">
            <tr>
              <th className="px-4 py-2 font-medium">Title</th>
              <th className="px-4 py-2 font-medium w-28">Source</th>
              <th className="px-4 py-2 font-medium w-40">Date</th>
              <th className="px-4 py-2 font-medium w-32">Tickers</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {articles.map((a: any) => (
              <tr key={a.id} className="hover:bg-gray-50">
                <td className="px-4 py-2">
                  <Link
                    to={`/news/${a.id}${language !== "vi" ? `?language=${language}` : ""}`}
                    className="text-blue-600 hover:underline font-medium"
                  >
                    {a.title || "(No title)"}
                  </Link>
                  {a.summary && <p className="text-xs text-gray-400 mt-0.5 line-clamp-1">{a.summary}</p>}
                </td>
                <td className="px-4 py-2 text-gray-500">{a.source}</td>
                <td className="px-4 py-2 text-gray-500 text-xs">
                  {a.published_at ? new Date(a.published_at).toLocaleString(language === "en" ? "en-US" : "vi-VN") : "-"}
                </td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-1">
                    {(a.tickers || []).map((t: string) => (
                      <span key={t} className="bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-xs font-medium">{t}</span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
            {!isLoading && articles.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-400">
                {q ? `No articles matching "${q}"` : "No articles"}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {pagination && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Total: {pagination.total}</span>
          <div className="flex gap-2">
            {cursor && (
              <button onClick={() => setCursor(undefined)} className="px-3 py-1 bg-white border rounded-lg hover:bg-gray-50">First</button>
            )}
            {pagination.has_more && (
              <button onClick={() => setCursor(pagination.next_cursor)} className="px-3 py-1 bg-white border rounded-lg hover:bg-gray-50">Next</button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
