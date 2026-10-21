// The one Getting started checklist (Today and Me): three steps built on the two reasons people
// come, set your area, do one thing near you, get a plan. Replaces the old setup ring, the
// "Get started 3 of 6" card and the Progress setup line (their data still exists; quests and XP
// are unchanged). The area is asked right here, no navigation. When all three are done it says
// so once with a little cheer and offers the optional extras, then folds away.
import { useEffect, useRef, useState } from 'react'
import { Check, ChevronRight, X } from 'lucide-react'
import { RabbitNap, burst } from '@/components/anim'
import { AreaInline } from '@/components/local/AreaInline'
import { cn } from '@/lib/utils'
import { hideChecklist, useNewcomer } from '@/lib/newcomer'

type Step = { id: 'area' | 'job' | 'plan'; title: string; line: string; action: string }
const STEPS: Step[] = [
  { id: 'area', title: 'Set your area', line: 'Your city or zip, so Near me fills in.', action: 'Set' },
  { id: 'job', title: 'Do one thing near you', line: 'Say you are going to a run, or post one.', action: 'Find a run' },
  { id: 'plan', title: 'Get a plan', line: 'About 3 minutes. It moves when life does.', action: 'Get a plan' },
]

export function GettingStarted({ onJob, onPlan, onWatch, onFriends, watch, className }: {
  onJob: () => void; onPlan: () => void
  /** the optional extras, shown once the three steps are done */
  onWatch: () => void; onFriends: () => void; watch: boolean
  className?: string
}) {
  const n = useNewcomer()
  const [areaOpen, setAreaOpen] = useState(false)
  const done = n ? STEPS.filter((s) => n.steps[s.id]).length : 0
  const all = done === STEPS.length
  const cheer = useRef<HTMLDivElement>(null)
  const wasAll = useRef(all)
  useEffect(() => {
    if (all && !wasAll.current) burst(cheer.current, 'quest')
    wasAll.current = all
  }, [all])
  useEffect(() => { if (n?.steps.area) setAreaOpen(false) }, [n?.steps.area])
  if (!n || n.checklist_hidden || (n.since === 'existing' && all)) return null
  const next = STEPS.find((s) => !n.steps[s.id])

  return (
    <section aria-labelledby="gs-title" className={cn('flex flex-col gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) p-4', className)}>
      <div ref={cheer} className="flex items-center gap-3">
        <RabbitNap size={36} mode={all ? 'cheer' : 'run'} />
        <div className="min-w-0 flex-1">
          <h2 id="gs-title" className="m-0 text-lead font-semibold text-(--text)">{all ? "You're set up!" : 'Getting started'}</h2>
          <p className="m-0 text-small text-(--text-secondary)">
            {all ? 'Nice work. A few extras if you like:' : `${done} of 3 done. ${done === 2 ? 'One to go!' : done === 1 ? 'Off to a good start.' : 'Three quick ones.'}`}
          </p>
        </div>
        <button type="button" className="flex size-11 shrink-0 items-center justify-center text-(--text-muted)"
          aria-label={all ? 'Done, hide this' : 'Hide Getting started'} onClick={() => void hideChecklist()}>
          <X className="size-5" aria-hidden />
        </button>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-(--bg-inset)" aria-hidden>
        <span className="h-full rounded-full bg-(--accent) transition-[width] duration-300" style={{ width: `${(100 * done) / 3}%` }} />
      </div>
      {!all && (
        <ol className="m-0 flex list-none flex-col gap-1 p-0">
          {STEPS.map((s, i) => {
            const ok = n.steps[s.id]
            const isNext = s === next
            const act = s.id === 'area' ? () => setAreaOpen((v) => !v) : s.id === 'job' ? onJob : onPlan
            return (
              <li key={s.id}>
                <button type="button" disabled={ok} onClick={act} aria-expanded={s.id === 'area' ? areaOpen : undefined}
                  className={cn('flex min-h-14 w-full items-center gap-3 rounded-xl px-2 py-2 text-left', !ok && 'active:bg-(--bg-inset)')}>
                  <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-full border text-small font-bold',
                    ok ? 'rb-pop border-(--accent) bg-(--accent) text-(--on-fill)' : isNext ? 'border-(--accent) text-(--accent)' : 'border-(--border-strong) text-(--text-muted)')}>
                    {ok ? <Check className="size-4" aria-hidden /> : i + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cn('block text-body font-semibold leading-snug', ok ? 'text-(--text-muted) line-through' : 'text-(--text)')}>
                      {s.title}{ok && <span className="sr-only">, done</span>}
                    </span>
                    {!ok && <span className="block text-small leading-snug text-(--text-secondary)">{s.line}</span>}
                    {isNext && <span className="mt-1 flex items-center gap-0.5 text-small font-semibold text-(--accent)">{s.action}<ChevronRight className="size-4" aria-hidden /></span>}
                  </span>
                  {!ok && !isNext && <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />}
                </button>
                {s.id === 'area' && areaOpen && !ok && <AreaInline className="mt-1" title="Where do you run?" line="Type a city and state, or a zip." />}
              </li>
            )
          })}
        </ol>
      )}
      {!all && next?.id === 'plan' && (
        <button type="button" className="min-h-11 self-start px-2 text-small font-medium text-(--text-muted)" onClick={() => void hideChecklist()}>
          No plan for me, I just want to show up
        </button>
      )}
      {all && (
        <div className="flex flex-wrap gap-2">
          {!watch && <Extra onClick={onWatch}>Connect a watch</Extra>}
          <Extra onClick={onFriends}>Find friends</Extra>
        </div>
      )}
    </section>
  )
}

function Extra({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="flex min-h-11 items-center gap-1 rounded-full border border-(--border) bg-(--bg) px-4 text-small font-semibold text-(--text) active:bg-(--bg-inset)">
      {children}<ChevronRight className="size-4 text-(--text-muted)" aria-hidden />
    </button>
  )
}
