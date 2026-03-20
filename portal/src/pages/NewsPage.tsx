import { useState, useEffect } from "react"
import { Link } from "react-router-dom"
import { Search, ArrowUpDown, X } from "lucide-react"
import { useNewsList, useAdminSources } from "@/api/hooks"

export default function NewsPage() {
  const [source, setSource] = useState<string>("")
  const [cursor, setCursor] = useState<string | undefined>()
  const [sort, setSort] = useState<string>("newest")
  const [searchInput, setSearchInput] = useState("")
  const [q, setQ] = useState<string | undefined>()
  const { data: sourcesData } = useAdminSources()
  const { data, isLoading, error } = useNewsList(source || undefined, 20, cursor, sort, q)

  const sources: any[] = sourcesData?.data || []
  const articles: any[] = data?.data || []
  const pagination = data?.pagination

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">News</h2>
        <div className="flex items-center gap-2">
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
              <button
                onClick={() => setSearchInput("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Sort */}
          <button
            onClick={() => {
              setSort(sort === "newest" ? "oldest" : "newest")
              setCursor(undefined)
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white hover:bg-gray-50"
            title={`Currently: ${sort}`}
          >
            <ArrowUpDown size={14} />
            {sort === "newest" ? "Newest" : "Oldest"}
          </button>

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
        </div>
      </div>

      {/* Active filters indicator */}
      {(q || source || sort !== "newest") && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>Filters:</span>
          {q && (
            <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
              Search: "{q}"
            </span>
          )}
          {source && (
            <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
              Source: {source}
            </span>
          )}
          {sort === "oldest" && (
            <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
              Oldest first
            </span>
          )}
          <button onClick={resetFilters} className="text-gray-400 hover:text-gray-600 underline">
            Clear all
          </button>
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
                  <Link to={`/news/${a.id}`} className="text-blue-600 hover:underline font-medium">
                    {a.title || "(No title)"}
                  </Link>
                  {a.summary && (
                    <p className="text-xs text-gray-400 mt-0.5 line-clamp-1">{a.summary}</p>
                  )}
                </td>
                <td className="px-4 py-2 text-gray-500">{a.source}</td>
                <td className="px-4 py-2 text-gray-500 text-xs">
                  {a.published_at ? new Date(a.published_at).toLocaleString("vi-VN") : "-"}
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
              <button onClick={() => setCursor(undefined)} className="px-3 py-1 bg-white border rounded-lg hover:bg-gray-50">
                First
              </button>
            )}
            {pagination.has_more && (
              <button onClick={() => setCursor(pagination.next_cursor)} className="px-3 py-1 bg-white border rounded-lg hover:bg-gray-50">
                Next
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
