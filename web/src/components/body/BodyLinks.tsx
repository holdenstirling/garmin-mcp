// Progress: one card with the two body logs (body.py): what fueling works for you, and niggles.
import { Bandage, ChevronRight, Utensils } from 'lucide-react'
import { IconTile } from '@/components/ui/brand'
import { openBody } from '@/lib/body'

export function BodyLinks() {
  const row = (icon: React.ReactNode, title: string, sub: string, onClick: () => void) => (
    <button type="button" onClick={onClick} className="flex min-h-16 w-full items-center gap-3.5 px-4 py-3.5 text-left active:bg-(--bg-inset)">
      <IconTile>{icon}</IconTile>
      <span className="min-w-0 flex-1">
        <span className="block text-body-lg font-medium leading-snug text-(--text)">{title}</span>
        <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">{sub}</span>
      </span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
  return (
    <section aria-label="Body logs" className="flex flex-col divide-y divide-(--border) overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      {row(<Utensils className="size-5" />, 'Fueling', 'Carbs per hour that work for you, vs your race target', () => openBody({ view: 'fueling' }))}
      {row(<Bandage className="size-5" />, 'Body & niggles', 'Track aches; rabbt eases the plan around them', () => openBody({ view: 'niggles' }))}
    </section>
  )
}
