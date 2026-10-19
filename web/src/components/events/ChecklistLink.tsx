// Links into the race checklist (components/events/RaceChecklist): a row for race cards and a
// button for the event page, race pack and race week. Counts come from /api/checklist/summary
// (one call shared by every link on screen; refreshed when a checklist changes).
import { useEffect, useState } from 'react'
import { ChevronRight, ListChecks } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { CHECKLIST_CHANGED_EVENT, checklistSummary, openChecklist } from '@/lib/racechecklist'

type Counts = Record<string, { done: number; total: number }>
let cache: { at: number; p: Promise<Counts> } | null = null
function counts(fresh = false): Promise<Counts> {
  if (!cache || fresh || Date.now() - cache.at > 30_000) {
    cache = { at: Date.now(), p: checklistSummary().then((r) => r.events, () => ({})) }
  }
  return cache.p
}

/** {done, total} for one event, or null while loading / when it has no checklist. */
export function useChecklistCount(eventId: string | null | undefined): { done: number; total: number } | null {
  const [c, setC] = useState<{ done: number; total: number } | null>(null)
  useEffect(() => {
    if (!eventId) return
    let live = true
    const load = (fresh: boolean) => { void counts(fresh).then((m) => { if (live) setC(m[eventId] ?? null) }) }
    load(false)
    const on = () => load(true)
    window.addEventListener(CHECKLIST_CHANGED_EVENT, on)
    return () => { live = false; window.removeEventListener(CHECKLIST_CHANGED_EVENT, on) }
  }, [eventId])
  return c
}

const label = (c: { done: number; total: number } | null) => `Race checklist${c ? ` · ${c.done}/${c.total}` : ''}`

/** A full-width row under a race card. */
export function ChecklistRow({ eventId }: { eventId: string }) {
  const c = useChecklistCount(eventId)
  if (!c) return null
  return (
    <button type="button" onClick={() => openChecklist(eventId)}
      className="flex min-h-11 w-full items-center gap-1.5 border-t border-(--border) px-3.5 py-2 text-left text-meta font-medium text-(--accent) active:bg-(--bg-inset)">
      <ListChecks className="size-4" aria-hidden /> {label(c)}
      <ChevronRight className="ml-auto size-4 text-(--text-muted)" aria-hidden />
    </button>
  )
}

/** A button for the event page, race pack and race week screens. */
export function ChecklistButton({ eventId, className, onBefore }: { eventId: string; className?: string; onBefore?: () => void }) {
  const c = useChecklistCount(eventId)
  if (!c) return null
  return (
    <Button variant="default" className={cn('h-11 w-full gap-1.5 text-body', className)}
      onClick={() => { onBefore?.(); openChecklist(eventId) }}>
      <ListChecks className="size-5" aria-hidden /> {label(c)}
    </Button>
  )
}
