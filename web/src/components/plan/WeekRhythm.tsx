// "Your week": a set weekly rhythm (lib/rhythm.ts), e.g. lift Mon, Wed, Fri and bike Tue, Thu,
// Sat. One row per day of tappable chips: Any (rabbt picks), Run, Bike, Swim, Lift, Rest. Up to
// two sports a day, Rest stands alone. Lift needs the strength opt-in first (StrengthOptInSheet):
// rabbt never schedules lifting until the athlete says yes.
//   * RhythmGrid: the controlled grid (plan setup keeps it in its draft)
//   * WeekRhythmSection: Plan -> Edit plan, loads and saves itself and rebuilds the plan
import { useEffect, useState } from 'react'
import { Bike, Dumbbell, Footprints, Moon, Sparkles, Waves } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { Section } from '@/components/ui/section'
import { Switch } from '@/components/settings/Grouped'
import { confirmAsk } from '@/lib/confirm'
import { cn } from '@/lib/utils'
import type { BuiltPlan } from '@/lib/plan'
import {
  DAYS, SPORT_LABEL, clean, getRhythm, hasStrength, putRhythm, sameRhythm, summary, toggle,
  type Day, type RhythmSport, type RhythmState, type WeekRhythm,
} from '@/lib/rhythm'
import { Card } from './ui'

const CHIPS: [RhythmSport | 'any', string, typeof Bike | null][] = [
  ['any', 'Any', null], ['run', 'Run', Footprints], ['bike', 'Bike', Bike], ['swim', 'Swim', Waves],
  ['strength', 'Lift', Dumbbell], ['rest', 'Rest', Moon],
]

/** The 7-day grid. ``onNeedOptIn`` is called when Lift is tapped before strength is opted in. */
export function RhythmGrid({ value, onChange, strengthOptIn, onNeedOptIn, disabled }: {
  value: WeekRhythm
  onChange: (r: WeekRhythm) => void
  strengthOptIn: boolean | null | undefined
  onNeedOptIn: (day: Day) => void
  disabled?: boolean
}) {
  const line = summary(value)
  return (
    <div className="flex flex-col gap-3">
      <ul className="m-0 flex list-none flex-col gap-2.5 p-0" aria-label="Your week, day by day">
        {DAYS.map(([d, short, long]) => {
          const cur = value[d] ?? []
          return (
            <li key={d} className="flex flex-col gap-1.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5">
              <p className="m-0 flex items-baseline justify-between gap-2">
                <span className="text-body font-semibold text-(--text)"><span aria-hidden>{short}</span><span className="sr-only">{long}</span></span>
                <span className="text-meta text-(--text-muted)">{cur.length ? cur.map((s) => SPORT_LABEL[s]).join(' + ') : 'rabbt picks'}</span>
              </p>
              <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5" role="group" aria-label={`${long}: pick up to two`}>
                {CHIPS.map(([sp, label, Ico]) => {
                  const on = sp === 'any' ? cur.length === 0 : cur.includes(sp)
                  return (
                    <button key={sp} type="button" disabled={disabled} aria-pressed={on}
                      aria-label={`${long}: ${label}`}
                      onClick={() => {
                        if (sp === 'strength' && !on && strengthOptIn !== true) { onNeedOptIn(d); return }
                        onChange(toggle(value, d, sp))
                      }}
                      className={cn('plan-chip inline-flex min-h-11 items-center gap-1.5', on && 'plan-chip--on')}>
                      {Ico && <Ico className="size-4" aria-hidden />}{label}
                    </button>
                  )
                })}
              </div>
            </li>
          )
        })}
      </ul>
      <p className="m-0 px-1 text-small leading-snug text-(--text-secondary)" aria-live="polite">
        {line ?? 'Every day is Any: rabbt picks what goes where.'}
      </p>
    </div>
  )
}

/** "Add strength workouts?": the opt-in. Nothing with weights is scheduled until Yes. */
export function StrengthOptInSheet({ busy, onYes, onNo }: { busy?: boolean; onYes: () => void; onNo: () => void }) {
  return (
    <Sheet title="Add strength workouts?" onClose={onNo} portal label="Strength workouts"
      footer={<>
        <Button variant="default" className="h-12 flex-1 text-body" disabled={busy} onClick={onNo}>Not now</Button>
        <Button variant="primary" className="h-12 flex-1 gap-1.5 text-body" loading={busy} onClick={onYes}>
          <Dumbbell className="size-5" aria-hidden /> Yes, add strength
        </Button>
      </>}>
      <div className="flex flex-col gap-3 px-1 pb-2">
        <span className="flex size-14 items-center justify-center rounded-2xl bg-(--accent-subtle) text-(--accent)" aria-hidden>
          <Dumbbell className="size-7" />
        </span>
        <p className="m-0 text-body leading-relaxed text-(--text)">
          rabbt will schedule strength sessions on your lifting days, with the exercises, sets, reps and rest for each one.
        </p>
        <ul className="m-0 flex list-none flex-col gap-2 p-0 text-small leading-snug text-(--text-secondary)">
          <li className="flex gap-2"><Sparkles className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />Built for endurance athletes: legs, hips, core and a little upper body.</li>
          <li className="flex gap-2"><Sparkles className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />45 to 60 minutes, lighter before big sessions and in race weeks.</li>
          <li className="flex gap-2"><Sparkles className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />Turn it off any time in Your week.</li>
        </ul>
      </div>
    </Sheet>
  )
}

/** Plan -> Edit plan: "Your week". Saving rebuilds the plan from today. */
export function WeekRhythmSection({ onPlan, readOnly }: { onPlan?: (p: BuiltPlan) => void; readOnly?: boolean }) {
  const [st, setSt] = useState<RhythmState | null>(null)
  const [draft, setDraft] = useState<WeekRhythm>({})
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState<Day | 'switch' | 'note' | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let live = true
    getRhythm().then((r) => { if (live) { setSt(r); setDraft(clean(r.week_rhythm)) } }, () => { if (live) setFailed(true) })
    return () => { live = false }
  }, [])
  if (failed) return null  // the server doesn't offer it yet: nothing to show
  if (!st) return null

  const on = st.strength_opt_in === true || (st.strength_opt_in == null && st.strength_on === true)
  const dirty = !sameRhythm(draft, st.week_rhythm)

  async function save(patch: { week_rhythm?: WeekRhythm; strength_opt_in?: boolean }, done: string) {
    setBusy(true); setErr(null); setMsg(null); setWarnings([])
    try {
      const r = await putRhythm(patch)
      setSt(r); setDraft(clean(r.week_rhythm)); setWarnings(r.warnings ?? [])
      if (r.plan) onPlan?.(r.plan)
      setMsg(done)
      return r
    } catch (e) {
      setErr((e as Error).message || "Couldn't save just now. Try again.")
      return null
    } finally { setBusy(false) }
  }

  async function optIn() {
    const day = asking
    const r = await save({ strength_opt_in: true }, 'Strength workouts are on.')
    setAsking(null)
    if (r && day && day !== 'switch' && day !== 'note') setDraft((cur) => toggle(cur, day, 'strength'))
  }

  async function strengthSwitch(v: boolean) {
    if (v) { setAsking('switch'); return }
    const lifting = hasStrength(draft)
    const ok = await confirmAsk('Turn off strength workouts?', {
      confirm: 'Turn off', danger: true,
      detail: lifting ? 'Your lifting days go back to Any and future weeks have no strength sessions.' : 'Future weeks won\'t have strength sessions.',
    })
    if (!ok) return
    let next = draft
    for (const [d] of DAYS) if (next[d]?.includes('strength')) next = toggle(next, d, 'strength')
    await save({ strength_opt_in: false, week_rhythm: clean(next) }, 'Strength workouts are off. Plan updated.')
  }

  return (
    <Section title="Your week" description="Pick what goes on which day, like lifting Mon, Wed, Fri. Any lets rabbt choose.">
      {st.needs_strength_opt_in && !on && (
        <div role="note" className="flex items-start gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-3">
          <Dumbbell className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <p className="m-0 text-small leading-snug text-(--text)">Your week has lifting days, but strength workouts are off, so rabbt leaves them open.</p>
            <Button variant="default" className="h-11 self-start px-4 text-body" disabled={readOnly || busy} onClick={() => setAsking('note')}>Add strength workouts</Button>
          </div>
        </div>
      )}
      <RhythmGrid value={draft} onChange={(r) => { setDraft(r); setMsg(null) }} strengthOptIn={on ? true : st.strength_opt_in}
        onNeedOptIn={(d) => setAsking(d)} disabled={readOnly || busy} />
      <Card>
        <div className="flex min-h-14 items-center gap-3 px-4 py-3">
          <Dumbbell className="size-5 shrink-0 text-(--text-secondary)" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="m-0 text-body text-(--text)">Strength workouts</p>
            <p className="m-0 text-meta text-(--text-muted)">{on ? 'On: exercises, sets and reps on lifting days' : 'Off: rabbt never schedules lifting'}</p>
          </div>
          <Switch label="Strength workouts" checked={on} disabled={readOnly || busy} onChange={(v) => void strengthSwitch(v)} />
        </div>
      </Card>
      {warnings.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3" aria-label="Heads up">
          {warnings.map((w) => <li key={w} className="text-small leading-snug text-(--warning-text)">{w}</li>)}
        </ul>
      )}
      {err && <p className="m-0 px-1 text-small text-(--danger)" role="alert">{err}</p>}
      {msg && !dirty && <p className="m-0 px-1 text-small text-(--accent)" role="status">{msg}</p>}
      {!readOnly && dirty && (
        <div className="flex gap-2">
          <Button variant="ghost" className="h-12 px-4 text-body" disabled={busy} onClick={() => setDraft(clean(st.week_rhythm))}>Undo changes</Button>
          <Button variant="primary" className="h-12 flex-1 text-body" loading={busy}
            onClick={() => void save({ week_rhythm: clean(draft) }, 'Plan updated.')}>Save my week</Button>
        </div>
      )}
      {asking && <StrengthOptInSheet busy={busy} onYes={() => void optIn()} onNo={() => setAsking(null)} />}
    </Section>
  )
}
