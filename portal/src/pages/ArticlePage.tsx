import { useParams, Link } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { useNewsDetail } from "@/api/hooks"

export default function ArticlePage() {
  const { id } = useParams<{ id: string }>()
  const { data, isLoading, error } = useNewsDetail(id!)

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-500">Error: {(error as Error).message}</div>

  const article = data?.data
  if (!article) return <div className="text-gray-500">Article not found</div>

  return (
    <div className="max-w-3xl space-y-4">
      <Link to="/news" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline">
        <ArrowLeft size={16} /> Back to news
      </Link>

      {article.thumbnail?.url && (
        <img
          src={article.thumbnail.url}
          alt={article.thumbnail.alt || article.title}
          className="w-full rounded-xl object-cover max-h-80"
        />
      )}

      <h1 className="text-2xl font-bold text-gray-900">{article.title}</h1>

      <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
        <span>{article.source}</span>
        {article.published_at && (
          <span>{new Date(article.published_at).toLocaleString("vi-VN")}</span>
        )}
        <a href={article.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
          Original
        </a>
      </div>

      {article.tickers?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {article.tickers.map((t: string) => (
            <span key={t} className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-sm font-medium">{t}</span>
          ))}
        </div>
      )}

      {article.summary && (
        <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 border border-gray-200">
          {article.summary}
        </div>
      )}

      {article.content && (
        <div
          className="prose prose-sm max-w-none text-gray-800"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(article.content) }}
        />
      )}
    </div>
  )
}

function renderMarkdown(md: string): string {
  return md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.+)$/gm, '<h3 class="text-base font-semibold mt-4 mb-1">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-lg font-semibold mt-5 mb-2">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold mt-6 mb-2">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^&gt; (.+)$/gm, '<blockquote class="border-l-4 border-gray-300 pl-3 italic text-gray-600 my-2">$1</blockquote>')
    .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
    .replace(/\n\n/g, "</p><p class='my-2'>")
    .replace(/\n/g, "<br/>")
}
