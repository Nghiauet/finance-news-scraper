import { useParams, Link, useSearchParams } from "react-router-dom"
import { ArrowLeft, ExternalLink } from "lucide-react"
import { useNewsDetail, type Language } from "@/api/hooks"
import { Card, ErrorState, Badge, Skeleton, Button } from "@/components/ui"

export default function ArticlePage() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const language: Language = searchParams.get("language") === "en" ? "en" : "vi"
  const { data, isLoading, error, refetch } = useNewsDetail(id!, language)

  function setLanguage(next: Language) {
    const sp = new URLSearchParams(searchParams)
    if (next === "vi") sp.delete("language")
    else sp.set("language", next)
    setSearchParams(sp, { replace: true })
  }

  const backLink = (
    <Link to="/news" className="inline-flex items-center gap-1 text-sm text-accent hover:underline">
      <ArrowLeft size={15} aria-hidden /> Back to news
    </Link>
  )

  const languageSwitch = (
    <div className="inline-flex overflow-hidden rounded-lg border border-line text-xs" role="group" aria-label="Language">
      {(["vi", "en"] as const).map((lang) => (
        <button
          key={lang}
          onClick={() => setLanguage(lang)}
          aria-pressed={language === lang}
          className={`px-3 py-1.5 font-medium transition-colors ${
            language === lang ? "bg-accent text-accent-fg" : "bg-surface text-muted hover:bg-surface-2"
          } ${lang === "en" ? "border-l border-line" : ""}`}
        >
          {lang === "vi" ? "Tiếng Việt" : "English"}
        </button>
      ))}
    </div>
  )

  if (isLoading) {
    return (
      <div className="max-w-3xl space-y-4">
        {backLink}
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-7 w-3/4" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  if (error) {
    const notFound = /404|not available|not found/i.test((error as Error).message)
    return (
      <div className="max-w-3xl space-y-4">
        {backLink}
        <ErrorState
          title={
            notFound && language === "en"
              ? "No English translation for this article yet"
              : "Couldn't load this article"
          }
          error={
            notFound && language === "en"
              ? new Error("The scraper adds translations as it re-processes each article. Switch to Tiếng Việt to read it now.")
              : error
          }
          onRetry={() => refetch()}
        />
        {notFound && language === "en" && (
          <Button variant="primary" onClick={() => setLanguage("vi")}>Read in Tiếng Việt</Button>
        )}
      </div>
    )
  }

  const article = data?.data
  if (!article) {
    return (
      <div className="max-w-3xl space-y-4">
        {backLink}
        <Card className="p-6"><p className="text-sm text-muted">This article is no longer cached.</p></Card>
      </div>
    )
  }

  return (
    <article className="max-w-3xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {backLink}
        {languageSwitch}
      </div>

      {article.thumbnail?.url && (
        <img
          src={article.thumbnail.url}
          alt={article.thumbnail.alt || ""}
          loading="lazy"
          className="max-h-80 w-full rounded-xl border border-line object-cover"
        />
      )}

      <h1 className="text-2xl leading-tight font-semibold tracking-tight text-fg">{article.title}</h1>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-subtle">
        <span className="font-medium text-muted">{article.source}</span>
        {article.published_at && (
          <span className="tnum">
            {new Date(article.published_at).toLocaleString(language === "en" ? "en-US" : "vi-VN")}
          </span>
        )}
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-accent hover:underline"
        >
          Open original <ExternalLink size={12} aria-hidden />
        </a>
      </div>

      {article.tickers?.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {article.tickers.map((t: string) => (
            <Badge key={t} tone="accent">{t}</Badge>
          ))}
        </div>
      )}

      {article.summary && (
        <Card className="bg-surface-2 p-4">
          <p className="text-sm leading-relaxed text-fg">{article.summary}</p>
        </Card>
      )}

      {article.content && (
        <div
          className="article-body text-[0.925rem] leading-relaxed text-fg"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(article.content) }}
        />
      )}
    </article>
  )
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
}

/** Inline spans, applied to already-escaped text. */
function inlineMd(s: string): string {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<code class="rounded bg-surface-2 px-1 py-0.5 text-xs">$1</code>')
}

/** A |---|---| row: only pipes, dashes, colons and spaces, with a real dash run. */
function isTableDivider(line: string): boolean {
  const t = line.trim()
  return t.includes("|") && /-{2,}/.test(t) && /^[|\s:-]+$/.test(t)
}

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim())
}

/**
 * Minimal markdown → HTML for LLM-generated article bodies. The input is escaped
 * first, so the result is safe to inject.
 *
 * Handles headings, pipe tables, blockquotes, bullet lists, bold and inline code.
 * Tables matter because the extraction prompt explicitly asks for them when an
 * article compares figures — without this they rendered as raw "| a | b |" text.
 */
function renderMarkdown(md: string): string {
  const lines = escapeHtml(md).split("\n")
  const out: string[] = []
  let listOpen = false

  function closeList() {
    if (listOpen) {
      out.push("</ul>")
      listOpen = false
    }
  }

  let i = 0
  while (i < lines.length) {
    const line = lines[i].trim()

    if (!line) {
      closeList()
      i++
      continue
    }

    // Table: a header row followed by a divider row
    if (line.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      closeList()
      const head = splitRow(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        rows.push(splitRow(lines[i]))
        i++
      }
      const th = head
        .map((cell) => `<th class="border border-line bg-surface-2 px-2 py-1 text-left font-semibold">${inlineMd(cell)}</th>`)
        .join("")
      const tb = rows
        .map((r) => `<tr>${r.map((cell) => `<td class="tnum border border-line px-2 py-1 align-top">${inlineMd(cell)}</td>`).join("")}</tr>`)
        .join("")
      out.push(
        '<div class="my-3 overflow-x-auto"><table class="w-full border-collapse border border-line text-sm">' +
          `<thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table></div>`,
      )
      continue
    }

    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading) {
      closeList()
      const level = heading[1].length
      const cls =
        level === 1 ? "mt-6 mb-2 text-xl font-semibold"
        : level === 2 ? "mt-5 mb-2 text-lg font-semibold"
        : "mt-4 mb-1 text-base font-semibold"
      out.push(`<h${level} class="${cls}">${inlineMd(heading[2])}</h${level}>`)
      i++
      continue
    }

    // "> quote" — the ">" is already "&gt;" at this point
    const quote = /^&gt;\s?(.*)$/.exec(line)
    if (quote) {
      closeList()
      out.push(
        `<blockquote class="my-2 border-l-2 border-accent pl-3 text-muted italic">${inlineMd(quote[1])}</blockquote>`,
      )
      i++
      continue
    }

    const bullet = /^[-*]\s+(.*)$/.exec(line)
    if (bullet) {
      if (!listOpen) {
        out.push('<ul class="my-2 ml-5 list-disc space-y-1">')
        listOpen = true
      }
      out.push(`<li>${inlineMd(bullet[1])}</li>`)
      i++
      continue
    }

    closeList()
    out.push(`<p class="my-2">${inlineMd(line)}</p>`)
    i++
  }

  closeList()
  return out.join("")
}
