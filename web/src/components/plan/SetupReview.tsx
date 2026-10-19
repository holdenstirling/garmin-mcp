// The setup wizard's "Your plan" step, summary first and details on tap:
//   * one line on the plan (weeks, hours, first workout) and a note when there is one;
//   * Phases | Calendar. Phases are rows you tap: a sheet says what the phase is for in plain
//     words, its weeks and dates, the workouts that define it (each explained), and the levers to
//     change it, with Undo. Calendar shows every week as a row of day dots; tap a week for its days.
//   * "Words in your plan": every workout type the plan uses, in one sentence each.
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Undo2 } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Segmented } from '@/components/nav/Segmented'
import { Button } from '@/components/ui/button'
import { SportTile } from '@/components/ui/SportTile'
import { cn } from '@/lib/utils'
import { GLOSSARY, KIND_GLOSSARY } from '@/lib/glossary'
import { KIND_LABEL, PHASE_LABEL } from '@/lib/plan'
import { hoursLine, type CalendarWeek, type Levers, type Phase, type PlanSummary } from '@/lib/planflow'
import { LeverFields } from './PlanFlow'

const day = (d: string, o: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }) =>
  new Date(`${d}T12:00:00`).toLocaleDateString([], o)
const fmtMin = (m: number) => (m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${String(m % 60).padStart(2, '0')}m` : ''}` : `${m} min`)
const hrs = (h: number) => `${Math.round(h * 10) / 10}h`

/** What each phase is for, in plain words (race plans and training blocks). */
function phaseAbout(p: Phase['phase'], noRace?: boolean): string {
  if (p === 'race') return noRace ? 'A lighter week to soak up the work and finish fresh.' : 'Race week: short, sharp sessions and rest, so you feel ready on the day.'
  const t = (GLOSSARY as Record<string, { text: string }>)[p]?.text
  return t ?? ''
}
const phaseName = (p: Phase['phase'], noRace?: boolean) => (p === 'race' && noRace ? 'Last week' : PHASE_LABEL[p])

// The builder's focus reads "Base: build aerobic endurance..."; the sheet already names the phase.
const focusText = (f: string) => { const s = f.replace(/^[A-Za-z ]+:\s*/, ''); return s.charAt(0).toUpperCase() + s.slice(1) }

export function SetupReview({ s, levers, setLevers, start, setStart, minStart, maxStart }: {
  s: PlanSummary
  levers: Levers; setLevers: (p: Partial<Levers>) => void
  start: string; setStart: (d: string) => void; minStart: string; maxStart?: string
}) {
  const [view, setView] = useState<'phases' | 'calendar'>('phases')
  const [open, setOpen] = useState<number | null>(null)
  const kinds = useMemo(() => {
    const seen = new Set<string>()
    for (const w of s.calendar ?? []) for (const d of w.days) for (const x of d.sessions) if (x.kind && KIND_GLOSSARY[x.kind]) seen.add(x.kind)
    return [...seen]
  }, [s.calendar])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5 px-1">
        <p className="text-lead font-semibold leading-snug text-(--text)">
          {s.weeks} weeks, {hoursLine(s.start_hours, s.peak_hours)}
        </p>
        {s.first_session && (
          <p className="text-body text-(--text-secondary)">
            Starts {day(s.first_session.date, { weekday: 'long', month: 'short', day: 'numeric' })} with {s.first_session.title}, {fmtMin(s.first_session.minutes)}.
          </p>
        )}
        {s.note && <p className="text-body text-(--text-secondary)">{s.note}</p>}
      </div>

      <Segmented label="Show the plan as" value={view} onChange={setView}
        options={[['phases', 'Phases'], ['calendar', 'Calendar']] as const} />

      {view === 'phases' ? (
        <ol className="flex flex-col gap-2" aria-label="Phases of your plan">
          {s.phases.map((p, i) => (
            <li key={i}>
              <button type="button" onClick={() => setOpen(i)}
                className="flex w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3.5 text-left active:bg-(--bg-inset)">
                <span className={cn('size-3 shrink-0 rounded-full', `phase-${p.phase}`)} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-body-lg font-semibold text-(--text)">
                    {phaseName(p.phase, s.no_race)}
                  </span>
                  <span className="block text-small text-(--text-secondary)">
                    {p.weeks} {p.weeks === 1 ? 'week' : 'weeks'}, {day(p.from)} to {day(p.to)}
                  </span>
                  <span className="block text-small text-(--text-muted)">
                    {p.hours_from === p.hours_to ? `About ${hrs(p.hours_from)} a week` : `${hrs(p.hours_from)} to ${hrs(p.hours_to)} a week`}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1 text-meta font-semibold text-(--accent)">
                  Details<ChevronRight className="size-5" aria-hidden />
                </span>
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <PlanCalendarList weeks={s.calendar ?? []} noRace={s.no_race} />
      )}

      {kinds.length > 0 && (
        <details className="rounded-xl border border-(--border) bg-(--bg-surface)">
          <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-4 text-body font-semibold text-(--text) [&::-webkit-details-marker]:hidden">
            <span className="flex-1">Words in your plan</span>
            <ChevronDown className="size-5 text-(--text-muted)" aria-hidden />
          </summary>
          <dl className="flex flex-col gap-3 border-t border-(--border) px-4 py-3">
            {kinds.map((k) => (
              <div key={k}>
                <dt className="text-body font-semibold text-(--text)">{KIND_LABEL[k] ?? KIND_GLOSSARY[k]!.title}</dt>
                <dd className="m-0 text-small leading-snug text-(--text-secondary)">{KIND_GLOSSARY[k]!.what} {KIND_GLOSSARY[k]!.why}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      {open != null && s.phases[open] && (
        <PhaseSheet p={s.phases[open]!} noRace={s.no_race} onClose={() => setOpen(null)}
          levers={levers} setLevers={setLevers} start={start} setStart={setStart} minStart={minStart} maxStart={maxStart} />
      )}
    </div>
  )
}

function PhaseSheet({ p, noRace, onClose, levers, setLevers, start, setStart, minStart, maxStart }: {
  p: Phase; noRace?: boolean; onClose: () => void
  levers: Levers; setLevers: (p: Partial<Levers>) => void
  start: string; setStart: (d: string) => void; minStart: string; maxStart?: string
}) {
  // Undo puts back the answers from when the sheet opened (nothing is saved until the plan starts).
  const [before] = useState({ levers, start })
  const changed = JSON.stringify(before.levers) !== JSON.stringify(levers) || before.start !== start
  const [adjust, setAdjust] = useState(false)
  return (
    <Sheet title={phaseName(p.phase, noRace)} onClose={onClose} portal
      footer={<Button variant="primary" className="h-12 w-full text-body-lg" onClick={onClose}>Done</Button>}>
      <div className="flex flex-col gap-5">
        <p className="m-0 text-body-lg leading-snug text-(--text)">{phaseAbout(p.phase, noRace)}</p>
        <dl className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-(--bg-inset) px-3.5 py-3">
            <dt className="text-meta text-(--text-muted)">When</dt>
            <dd className="m-0 text-body font-semibold text-(--text)">{day(p.from)} to {day(p.to)}</dd>
            <dd className="m-0 text-small text-(--text-secondary)">{p.weeks} {p.weeks === 1 ? 'week' : 'weeks'}</dd>
          </div>
          <div className="rounded-xl bg-(--bg-inset) px-3.5 py-3">
            <dt className="text-meta text-(--text-muted)">Training a week</dt>
            <dd className="m-0 text-body font-semibold text-(--text)">
              {p.hours_from === p.hours_to ? `About ${hrs(p.hours_from)}` : `${hrs(p.hours_from)} to ${hrs(p.hours_to)}`}
            </dd>
            {!!p.longest_minutes && <dd className="m-0 text-small text-(--text-secondary)">Longest workout {fmtMin(p.longest_minutes)}</dd>}
          </div>
        </dl>
        {p.focus && <p className="m-0 text-body text-(--text-secondary)"><b className="font-semibold text-(--text)">Focus:</b> {focusText(p.focus)}</p>}
        {(p.key_kinds ?? []).length > 0 && (
          <section aria-labelledby="phase-key" className="flex flex-col gap-2">
            <h3 id="phase-key" className="m-0 text-body-lg font-semibold text-(--text)">The workouts that shape it</h3>
            <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
              {p.key_kinds!.map((k) => {
                const g = KIND_GLOSSARY[k]
                return (
                  <li key={k} className="rounded-xl border border-(--border) px-3.5 py-3">
                    <span className="block text-body font-semibold text-(--text)">{KIND_LABEL[k] ?? g?.title ?? k}</span>
                    {g && <span className="block text-small leading-snug text-(--text-secondary)">{g.what} {g.why}</span>}
                  </li>
                )
              })}
            </ul>
          </section>
        )}
        <section aria-labelledby="phase-adjust" className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h3 id="phase-adjust" className="m-0 flex-1 text-body-lg font-semibold text-(--text)">Adjust</h3>
            {changed && (
              <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => { setLevers(before.levers); setStart(before.start) }}>
                <Undo2 className="size-4" aria-hidden /> Undo
              </Button>
            )}
          </div>
          <p className="m-0 text-small leading-snug text-(--text-secondary)">
            Changes apply to the whole plan and you see them as soon as you close this. A later start date gives{' '}
            {noRace ? 'a shorter block' : 'base a shorter runway'}; an earlier one gives it more weeks.
          </p>
          {adjust ? (
            <LeverFields v={levers} set={setLevers} start={start} setStart={setStart} minStart={minStart} maxStart={maxStart} />
          ) : (
            <Button variant="default" className="h-11" onClick={() => setAdjust(true)}>Change days, hours or start date</Button>
          )}
        </section>
      </div>
    </Sheet>
  )
}

/** Every week as a row: dates, phase, hours and one dot per day (filled = a workout). Tap a week
 *  to list its days. */
function PlanCalendarList({ weeks, noRace }: { weeks: CalendarWeek[]; noRace?: boolean }) {
  const [openWeek, setOpenWeek] = useState<string | null>(weeks[0]?.start ?? null)
  if (!weeks.length) return null
  return (
    <ol className="flex flex-col gap-2" aria-label="Your plan, week by week">
      {weeks.map((w, i) => {
        const isOpen = openWeek === w.start
        const byDay = new Map(w.days.map((d) => [d.date, d.sessions]))
        const dates = Array.from({ length: 7 }, (_, k) => {
          const d = new Date(`${w.start}T12:00:00`); d.setDate(d.getDate() + k)
          return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        })
        return (
          <li key={w.start} className="rounded-xl border border-(--border) bg-(--bg-surface)">
            <button type="button" aria-expanded={isOpen} onClick={() => setOpenWeek(isOpen ? null : w.start)}
              className="flex w-full flex-col gap-2 px-4 py-3 text-left">
              <span className="flex w-full items-baseline gap-2">
                <span className="text-body font-semibold text-(--text)">Week {i + 1}</span>
                <span className="text-small text-(--text-muted)">{day(w.start)}</span>
                <span className="ml-auto text-small text-(--text-secondary)">
                  {phaseName(w.phase, noRace)}{w.recovery ? ', lighter' : ''}, {hrs(w.hours)}
                </span>
              </span>
              <span className="grid w-full grid-cols-7 gap-1" aria-hidden>
                {dates.map((d) => {
                  const ss = byDay.get(d) ?? []
                  return (
                    <span key={d} className="flex flex-col items-center gap-1">
                      <span className="text-meta text-(--text-muted)">{new Date(`${d}T12:00:00`).toLocaleDateString([], { weekday: 'narrow' })}</span>
                      <span className={cn('size-3 rounded-full', ss.length ? `phase-${w.phase}` : 'border border-(--border)')} />
                    </span>
                  )
                })}
              </span>
            </button>
            {isOpen && (
              <ul className="m-0 flex list-none flex-col border-t border-(--border) p-0">
                {dates.map((d) => {
                  const ss = byDay.get(d) ?? []
                  return (
                    <li key={d} className="flex items-start gap-3 border-b border-(--border) px-4 py-2.5 last:border-b-0">
                      <span className="w-12 shrink-0 pt-1 text-small text-(--text-muted)">{day(d, { weekday: 'short' })}</span>
                      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                        {ss.length ? ss.map((x, k) => (
                          <span key={k} className="flex items-center gap-2.5">
                            <SportTile sport={x.sport} size={28} />
                            <span className="min-w-0 flex-1 text-body leading-snug text-(--text)">{x.title}</span>
                            <span className="shrink-0 text-small tabular-nums text-(--text-secondary)">{fmtMin(x.minutes)}</span>
                          </span>
                        )) : <span className="pt-1 text-small text-(--text-muted)">Rest</span>}
                      </span>
                    </li>
                  )
                })}
              </ul>
            )}
          </li>
        )
      })}
    </ol>
  )
}
