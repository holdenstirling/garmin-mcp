// "Related" footer for detail pages: a short list of where to go next from here (its day, its
// week, the race it builds toward, the people in it, the chat, a link to share), so no page is a
// dead end. Rows with no `onClick` are left out; nothing renders when there are none.
import type { ReactNode } from 'react'
import { useState } from 'react'
import { Check, ChevronRight, Link2 } from 'lucide-react'
import { IconTile, SectionLabel } from '@/components/ui/brand'
import { copyDeepLink, type DeepKind } from '@/lib/people'

export type RelatedItem = { key: string; icon: ReactNode; label: string; sub?: string; onClick?: (() => void) | null }

export function Related({ items, link, title = 'Related' }: {
  items: RelatedItem[]; link?: { kind: DeepKind; id: string; date?: string }; title?: string
}) {
  const [copied, setCopied] = useState(false)
  const rows = items.filter((i) => !!i.onClick)
  if (!rows.length && !link) return null
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <SectionLabel>{title}</SectionLabel>
      <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
        {rows.map((r) => (
          <button key={r.key} type="button" onClick={r.onClick!}
            className="flex min-h-12 w-full items-center gap-3 px-3.5 py-2 text-left active:bg-(--bg-inset)">
            <IconTile size={32}>{r.icon}</IconTile>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body font-medium text-(--text)">{r.label}</span>
              {r.sub && <span className="block truncate text-meta text-(--text-muted)">{r.sub}</span>}
            </span>
            <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
          </button>
        ))}
        {link && (
          <button type="button" onClick={() => void copyDeepLink(link.kind, link.id, link.date).then((ok) => { setCopied(ok); window.setTimeout(() => setCopied(false), 2000) })}
            className="flex min-h-12 w-full items-center gap-3 px-3.5 py-2 text-left active:bg-(--bg-inset)">
            <IconTile size={32} tone="neutral">{copied ? <Check className="size-5" /> : <Link2 className="size-5" />}</IconTile>
            <span className="min-w-0 flex-1 text-body font-medium text-(--text)" aria-live="polite">
              {copied ? 'Link copied' : 'Copy a link to this page'}
            </span>
          </button>
        )}
      </div>
    </section>
  )
}
