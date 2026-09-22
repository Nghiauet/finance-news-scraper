import type { ReactNode } from "react"
import { Card } from "@/components/ui"

interface Props {
  title: string
  value: string | number
  icon: ReactNode
  subtitle?: string
  /** Tint the figure when it carries a state, e.g. errors above zero. */
  tone?: "default" | "ok" | "warn" | "danger"
}

const TONE_TEXT = {
  default: "text-fg",
  ok: "text-ok",
  warn: "text-warn",
  danger: "text-danger",
} as const

export default function StatsCard({ title, value, icon, subtitle, tone = "default" }: Props) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium tracking-wide text-subtle uppercase">{title}</span>
        <span className="shrink-0 text-subtle" aria-hidden>{icon}</span>
      </div>
      <p className={`tnum mt-2 text-2xl leading-none font-semibold ${TONE_TEXT[tone]}`}>{value}</p>
      {subtitle && <p className="mt-1.5 text-xs text-subtle">{subtitle}</p>}
    </Card>
  )
}
