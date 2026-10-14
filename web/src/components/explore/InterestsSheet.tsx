// "What are you into?": four quick, skippable steps (race types -> distances -> vibe & goals ->
// travel + home zip) that power Explore's "For you" picks. Saved on the athlete profile
// (interests), so Rabbit knows them too. First save earns the "interests" quest XP.
import { useState } from 'react'
import { Check, MapPin } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Screen, StepIntro, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  DISTANCES, GOALS, MONTH_SHORT, RACE_TYPES, TRAVEL, VIBES, hasInterests, saveInterests, type Interests,
} from '@/lib/foryou'

const STEPS = 4

function toggle<T>(list: T[] | undefined, v: T): T[] {
  const l = list ?? []
  return l.includes(v) ? l.filter((x) => x !== v) : [...l, v]
}

/** Big tappable chip (emoji optional). */
function BigChip({ on, onClick, emoji, label, sub }: {
  on: boolean; onClick: () => void; emoji?: string; label: string; sub?: string
}) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={cn('relative flex min-h-14 items-center gap-2.5 rounded-2xl border px-3.5 py-2.5 text-left transition-colors active:scale-[0.98]',
        on ? 'border-(--accent) bg-(--accent-subtle) text-(--text)' : 'border-(--border) bg-(--bg-surface) text-(--text-secondary)')}>
      {emoji && <span aria-hidden className="text-[1.4118rem] leading-none">{emoji}</span>}
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8235rem] font-medium leading-tight">{label}</span>
        {sub && <span className="block text-[0.6471rem] text-(--text-muted)">{sub}</span>}
      </span>
      {on && <Check className="size-4 shrink-0 text-(--accent)" aria-hidden />}
    </button>
  )
}

function Dots({ step }: { step: number }) {
  return (
    <div className="mx-auto mt-2.5 flex justify-center gap-1.5" aria-label={`Step ${step + 1} of ${STEPS}`}>
      {Array.from({ length: STEPS }, (_, i) => (
        <span key={i} className={cn('h-2 rounded-full transition-all duration-300',
          i === step ? 'w-5 bg-(--accent)' : i < step ? 'w-2 bg-(--accent)' : 'w-2 bg-(--bg-elevated)')} />
      ))}
    </div>
  )
}

export function InterestsSheet({ initial, onClose, onSaved }: {
  initial?: Interests | null
  onClose: () => void
  onSaved: (i: Interests) => void
}) {
  const [i, setI] = useState<Interests>(() => ({ ...(initial ?? {}) }))
  const [step, setStep] = useState(0)
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const first = !hasInterests(initial)
  const set = (p: Partial<Interests>) => { setI((x) => ({ ...x, ...p })); setError(null) }
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const zip = (i.home_zip ?? '').trim()
  const zipBad = zip !== '' && !/^\d{5}$/.test(zip)

  async function save() {
    if (zipBad) { setError('Home zip is 5 digits (or leave it empty).'); return }
    setBusy(true); setError(null)
    const clean: Interests = { ...i, home_zip: zip }
    try {
      const r = await saveInterests(clean)
      onSaved(r.interests ?? clean)
      close()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  const next = () => (step < STEPS - 1 ? setStep(step + 1) : void save())
  return (
    <Screen title="What are you into?" subtitle={first ? 'Personal race picks · +50 XP' : 'Your race interests'}
      closing={closing} onClose={close} headerExtra={<Dots step={step} />}
      footer={<>
        {step > 0
          ? <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={() => setStep(step - 1)}>Back</Button>
          : <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={close}>Skip for now</Button>}
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} onClick={next}>
          {step < STEPS - 1 ? 'Next' : 'Show my picks'}
        </Button>
      </>}>
      {step === 0 && (
        <>
          <StepIntro eyebrow="1 of 4 · Race types" title="What do you love to race?">Pick as many as you like.</StepIntro>
          <div className="grid grid-cols-2 gap-2">
            {RACE_TYPES.map(([v, label, emoji]) => (
              <BigChip key={v} on={!!i.race_types?.includes(v)} emoji={emoji} label={label}
                onClick={() => set({ race_types: toggle(i.race_types, v) })} />
            ))}
          </div>
        </>
      )}
      {step === 1 && (
        <>
          <StepIntro eyebrow="2 of 4 · Distances" title="How far?">Distances you'd sign up for this year.</StepIntro>
          <div className="grid grid-cols-2 gap-2">
            {DISTANCES.map(([v, label]) => (
              <BigChip key={v} on={!!i.distances?.includes(v)} label={label}
                onClick={() => set({ distances: toggle(i.distances, v) })} />
            ))}
          </div>
        </>
      )}
      {step === 2 && (
        <>
          <StepIntro eyebrow="3 of 4 · Vibe & goals" title="What makes a race worth it?" />
          <div className="grid grid-cols-2 gap-2">
            {VIBES.map(([v, label, emoji]) => (
              <BigChip key={v} on={!!i.race_vibe?.includes(v)} emoji={emoji} label={label}
                onClick={() => set({ race_vibe: toggle(i.race_vibe, v) })} />
            ))}
          </div>
          <p className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Next 12 months, you want to…</p>
          <div className="grid grid-cols-2 gap-2">
            {GOALS.map(([v, label]) => (
              <BigChip key={v} on={!!i.goals_next_12mo?.includes(v)} label={label}
                onClick={() => set({ goals_next_12mo: toggle(i.goals_next_12mo, v) })} />
            ))}
          </div>
        </>
      )}
      {step === 3 && (
        <>
          <StepIntro eyebrow="4 of 4 · Travel" title="How far will you go?" />
          <div className="flex flex-col gap-2">
            {TRAVEL.map(([v, label, sub]) => (
              <BigChip key={v} on={i.travel === v} label={label} sub={sub}
                onClick={() => set({ travel: i.travel === v ? undefined : v })} />
            ))}
          </div>
          <label className="flex flex-col gap-1.5 px-1">
            <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Home zip (optional)</span>
            <span className="relative">
              <MapPin className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-(--text-muted)" />
              <input className={cn(inputCls, 'pl-9')} value={i.home_zip ?? ''} inputMode="numeric" maxLength={5}
                autoComplete="postal-code" placeholder="e.g. 80204" aria-invalid={zipBad}
                onChange={(e) => set({ home_zip: e.target.value.replace(/\D/g, '').slice(0, 5) })} />
            </span>
            <span className="text-[0.7059rem] text-(--text-muted)">Used to find races near you. Leave empty to use your profile's home.</span>
          </label>
          <div className="flex flex-col gap-1.5 px-1">
            <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Months to skip</span>
            <div className="grid grid-cols-6 gap-1.5">
              {MONTH_SHORT.map((m, idx) => {
                const on = !!i.months_avoid?.includes(idx + 1)
                return (
                  <button key={m} type="button" aria-pressed={on} onClick={() => set({ months_avoid: toggle(i.months_avoid, idx + 1) })}
                    className={cn('hit-44 h-10 rounded-xl border text-[0.7059rem] font-medium',
                      on ? 'border-(--warning) bg-(--warning-subtle) text-(--warning-text) line-through' : 'border-(--border) text-(--text-secondary)')}>
                    {m}
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}
      {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
    </Screen>
  )
}
