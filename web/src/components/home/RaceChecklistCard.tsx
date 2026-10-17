// Home: the next A/B race within 12 weeks and its checklist window (server: /api/checklist/next).
// "Leadville 100 · 52 days · 3 of 8 done this window", the next two items with checkboxes you can
// tick right here, and a tap through to the full checklist. Hidden when there's no race close.
import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronRight, ListChecks } from 'lucide-react'
import { celebrate } from '@/components/fx/motion'
import { cn } from '@/lib/utils'
import {
  CHECKLIST_CHANGED_EVENT, actChecklist, announceChecklist, checklistNext, dueLabel, openChecklist, type ChecklistNext,
} from '@/lib/racechecklist'
import { ProgressRing } from '@/components/events/RaceChecklist'

export function RaceChecklistCard({ refreshKey }: { refreshKey?: number }) {
  const [n, setN] = useState<ChecklistNext | null>(null)
  const load = useCallback(() => { checklistNext().then((r) => setN(r.next), () => {}) }, [])
  useEffect(() => { load() }, [load, refreshKey])
  useEffect(() => {
    window.addEventListener(CHECKLIST_CHANGED_EVENT, load)
    return () => window.removeEventListener(CHECKLIST_CHANGED_EVENT, load)
  }, [load])
  if (!n) return null
  const w = n.window
  const tick = async (id: string, el: Element) => {
    setN((x) => x && { ...x, next: x.next.map((i) => (i.id === id ? { ...i, checked: true } : i)) })
    celebrate(el, 'checkin')
    try { await actChecklist(n.event.id, { action: 'check', item: id }); announceChecklist() } catch { load() }
  }
  return (
    <section aria-label={`Race checklist for ${n.event.name}`} className="mx-4 mt-3 flex shrink-0 flex-col overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      <button type="button" onClick={() => openChecklist(n.event.id)}
        className="flex min-h-14 items-center gap-3 px-3.5 py-3 text-left active:bg-(--bg-inset)">
        <ProgressRing done={n.done} total={n.total} size={44} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
            <ListChecks className="size-3.5" aria-hidden /> Race checklist
          </span>
          <span className="block truncate text-[0.8824rem] font-semibold text-(--text)">
            {n.event.name} · {n.days_out === 0 ? 'today' : n.days_out === 1 ? 'tomorrow' : `${n.days_out} days`}
          </span>
          <span className="block text-[0.7059rem] text-(--text-muted)">{w.label}: {w.done} of {w.total} done</span>
        </span>
        <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
      </button>
      {n.next.length > 0 && (
        <ul className="flex flex-col border-t border-(--border)">
          {n.next.map((i) => (
            <li key={i.id}>
              <button type="button" role="checkbox" aria-checked={i.checked} disabled={i.checked}
                onClick={(e) => void tick(i.id, e.currentTarget)}
                className="flex min-h-11 w-full items-center gap-3 px-3.5 py-2 text-left active:bg-(--bg-inset)">
                <span aria-hidden className={cn('flex size-5 shrink-0 items-center justify-center rounded-full border-2',
                  i.checked ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')}>
                  {i.checked && <Check className="rb-tick size-3" strokeWidth={3} />}
                </span>
                <span className={cn('min-w-0 flex-1 text-[0.7647rem] leading-snug', i.checked ? 'text-(--text-muted) line-through' : 'text-(--text)')}>{i.text}</span>
                <span className="shrink-0 text-[0.6471rem] text-(--text-muted)">{dueLabel(i.due)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
