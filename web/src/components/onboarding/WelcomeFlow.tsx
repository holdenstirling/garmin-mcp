// "What brings you to Rabbit?": the welcome on first sign-in (full: hello -> pick -> your Rabbit),
// a lighter sheet once for people who were set up before this existed (lite: pick -> your
// Rabbit), and Settings -> "How you use Rabbit" (edit). Saves athlete.intents (tap order =
// priority) and welcomed_at; skipping also counts as seen. lib/intent.ts has the copy and logic.
//
// Tagline options (no em dashes in copy):
//  1. "Train smarter. Find your people. Never miss the start line."
//     sub: "Rabbit is your coach, your crew and your calendar of what's next."   <- used
//  2. "Your training, your people, your next start line."
//     sub: "Plan it, share it, and find what's next, all in one place."
//  3. "Keep moving, together."
//     sub: "Plans that fit your life, friends who cheer, and events worth showing up for."
// (1) wins: it names all three things Rabbit does (training, social support, events) in the
// owner's order, and the sub-line maps them to coach / crew / calendar.
import { useEffect, useRef, useState } from 'react'
import { useDialog } from '@/hooks/useDialog'
import { CalendarDays, Check, ChevronRight, Compass, Flame, Target, UserRound, Users, X, type LucideIcon } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { RabbitLoader } from '@/components/RabbitLoader'
import { HopIn, burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import type { Me } from '@/lib/api'
import { cn } from '@/lib/utils'
import {
  INTENT_OPTIONS, intentsOf, onOpenWelcome, saveIntents, setCurrentIntents, skipWelcome, welcomeOf, welcomePlan,
  type Intent, type NextStep,
} from '@/lib/intent'

const ICON: Record<Intent, LucideIcon> = {
  train: Target, community: Users, events: CalendarDays, consistent: Flame, coach: UserRound, explore: Compass,
}
const SAVING = ['Tuning Rabbit to you…', 'Sorting your setup…', 'Stretching first…']

type Mode = 'full' | 'lite' | 'edit'
type Step = 'hello' | 'pick' | 'yours'

export function WelcomeFlow({ mode, initial, name, garmin, hasPlan, onFinish }: {
  mode: Mode
  initial: Intent[]
  name?: string
  garmin: boolean
  hasPlan: boolean
  /** saved = the answer (or skip) reached the server; next = where to go now (null: stay) */
  onFinish: (r: { saved: boolean; intents: Intent[] | null; next: NextStep | null }) => void
}) {
  const [step, setStep] = useState<Step>(mode === 'full' ? 'hello' : 'pick')
  const [picks, setPicks] = useState<Intent[]>(initial)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const cta = useRef<HTMLButtonElement>(null)
  const box = useRef<HTMLDivElement>(null)

  const toggle = (id: Intent) => setPicks((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const skip = () => {
    if (mode === 'edit') { onFinish({ saved: false, intents: null, next: null }); return }
    void skipWelcome().catch(() => {}) // best effort: seen either way on this device
    onFinish({ saved: true, intents: null, next: null })
  }
  // Escape / the phone's Back = Skip; on the last step (already saved) it just closes.
  useDialog(box, () => {
    if (saving) return
    if (step === 'yours') onFinish({ saved: true, intents: picks, next: null })
    else skip()
  })
  async function save() {
    setSaving(true); setErr(null)
    try {
      await saveIntents(picks)
      setCurrentIntents(picks)
      setStep('yours')
    } catch (e) { setErr((e as Error).message || "Couldn't save just now.") }
    finally { setSaving(false) }
  }
  // "Here's your Rabbit" lands with a small carrot burst from the main button.
  useEffect(() => {
    if (step !== 'yours') return
    const t = window.setTimeout(() => burst(cta.current, 'quest'), 240)
    return () => window.clearTimeout(t)
  }, [step])

  const plan = welcomePlan(picks, { garmin, hasPlan })
  const first = name?.split(' ')[0]

  const body = step === 'hello' ? (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 px-6 text-center">
      <HopIn as="span" className="logo-tile flex size-24 items-center justify-center rounded-[26px] bg-(--brand) shadow-md">
        <span className="rb-jump inline-flex" style={{ animationDelay: '380ms' }}><RabbitLogo size={78} /></span>
      </HopIn>
      <HopIn index={2} className="flex flex-col gap-3">
        {first && <p className="text-[0.8235rem] font-medium text-(--text-secondary)">Hi {first}, welcome to Rabbit</p>}
        <h1 className="font-display text-[1.8824rem] leading-[1.15] text-(--brand)">
          Train smarter. Find your people. Never miss the start line.
        </h1>
        <p className="text-[0.9412rem] leading-snug text-(--text-secondary)">
          Rabbit is your coach, your crew and your calendar of what's next.
        </p>
      </HopIn>
      <HopIn index={4} className="flex flex-wrap justify-center gap-2" aria-hidden="true">
        {(['Training', 'Social support', 'Events'] as const).map((t) => (
          <span key={t} className="rounded-full border border-(--accent)/30 bg-(--accent-subtle) px-3 py-1 text-[0.7059rem] font-medium text-(--accent)">{t}</span>
        ))}
      </HopIn>
    </div>
  ) : step === 'pick' ? (
    <div className="flex flex-1 flex-col gap-3 px-4 pb-2">
      <div className="px-1">
        <h2 className="font-display text-[1.5294rem] leading-tight text-(--brand)">What brings you to Rabbit?</h2>
        <p className="mt-1 text-[0.8235rem] leading-snug text-(--text-secondary)">
          Pick all that fit. Tap the most important one first.
        </p>
      </div>
      <div className="flex flex-col gap-2" role="group" aria-label="What brings you to Rabbit">
        {INTENT_OPTIONS.map((o, i) => {
          const at = picks.indexOf(o.id)
          const on = at >= 0
          const Icon = ICON[o.id]
          return (
            <HopIn key={o.id} index={i}>
              <button type="button" aria-pressed={on} onClick={() => toggle(o.id)}
                className={cn('flex min-h-[64px] w-full items-center gap-3 rounded-2xl border px-3.5 py-3 text-left transition-colors active:scale-[0.99]',
                  on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
                <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-xl',
                  on ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-inset) text-(--text-secondary)')}>
                  <Icon className="size-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cn('block text-[0.9412rem] font-semibold', on ? 'text-(--accent)' : 'text-(--text)')}>{o.title}</span>
                  <span className="block text-[0.7647rem] leading-snug text-(--text-muted)">{o.help}</span>
                </span>
                <span aria-hidden="true" className={cn('flex size-7 shrink-0 items-center justify-center rounded-full border text-[0.7647rem] font-bold',
                  on ? 'rb-pop border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')} key={on ? `on${at}` : 'off'}>
                  {on ? at + 1 : ''}
                </span>
              </button>
            </HopIn>
          )
        })}
      </div>
      {picks.length > 1 && <p className="px-1 text-[0.7059rem] text-(--text-muted)">Numbers show what matters most. Tap again to change.</p>}
      {err && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{err}</p>}
    </div>
  ) : (
    <div className="flex flex-1 flex-col gap-4 px-5">
      <HopIn className="flex items-center gap-3">
        <span className="logo-tile flex size-12 shrink-0 items-center justify-center rounded-[14px] bg-(--brand) shadow-sm">
          <RabbitLogo size={40} />
        </span>
        <h2 className="font-display text-[1.5294rem] leading-tight text-(--brand)">Here's your Rabbit</h2>
      </HopIn>
      <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">What we'll set up next, made for how you use Rabbit:</p>
      <ul className="flex flex-col gap-2.5">
        {plan.bullets.map((b, i) => (
          <HopIn as="li" key={b} index={i + 1} className="flex items-start gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
            <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)"><Check className="size-3.5" /></span>
            <span className="text-[0.8824rem] leading-snug text-(--text)">{b}</span>
          </HopIn>
        ))}
      </ul>
      <p className="text-[0.7059rem] text-(--text-muted)">Change this any time in Settings, under How you use Rabbit.</p>
    </div>
  )

  const footer = (
    <div className="flex flex-col gap-1 px-4 pb-[max(16px,env(safe-area-inset-bottom))] pt-3">
      {step === 'hello' && (
        <Button variant="primary" className="h-12 w-full text-[0.9412rem]" onClick={() => setStep('pick')}>
          Let's go <ChevronRight className="ml-1 size-4" />
        </Button>
      )}
      {step === 'pick' && (saving ? (
        <div className="flex h-12 items-center justify-center"><RabbitLoader inline size={24} label={SAVING[0]} cycle={SAVING} /></div>
      ) : (
        <Button variant="primary" className="h-12 w-full text-[0.9412rem]" disabled={!picks.length} onClick={() => void save()}>
          {err ? 'Try again' : picks.length ? 'Continue' : 'Pick at least one'}
        </Button>
      ))}
      {step === 'yours' && (
        <Button ref={cta} variant="primary" className="h-12 w-full text-[0.9412rem]"
          onClick={() => onFinish({ saved: true, intents: picks, next: plan.next?.step ?? null })}>
          {plan.next?.label ?? "Let's go"} <ChevronRight className="ml-1 size-4" />
        </Button>
      )}
      {step !== 'yours' || plan.next ? (
        <button type="button" className="min-h-11 text-[0.8235rem] text-(--text-muted) underline-offset-2 active:underline"
          onClick={step === 'yours' ? () => onFinish({ saved: true, intents: picks, next: null }) : skip}>
          {mode === 'edit' && step !== 'yours' ? 'Cancel' : 'Skip for now'}
        </button>
      ) : null}
    </div>
  )

  const dots = mode === 'full' ? ['hello', 'pick', 'yours'] : ['pick', 'yours']
  const progress = (
    <div className="flex justify-center gap-1.5 py-2" aria-hidden="true">
      {dots.map((d) => (
        <span key={d} className={cn('h-1.5 rounded-full transition-all', d === step ? 'w-5 bg-(--accent)' : 'w-1.5 bg-(--border-strong)')} />
      ))}
    </div>
  )

  if (mode === 'full') {
    return (
      <div ref={box} className="fixed inset-0 flex flex-col bg-(--bg) pt-[max(10px,env(safe-area-inset-top))]" style={{ zIndex: 'var(--z-dialog)' }}
        role="dialog" aria-modal="true" aria-label="Welcome to Rabbit">
        <div className="flex items-center justify-between px-2">
          <span className="w-11" />
          {progress}
          {step !== 'yours' ? (
            <button type="button" className="flex size-11 items-center justify-center text-(--text-muted)" aria-label="Skip for now" onClick={skip}>
              <X className="size-5" />
            </button>
          ) : <span className="w-11" />}
        </div>
        <div className="mx-auto flex min-h-0 w-full max-w-md flex-1 flex-col overflow-y-auto">{body}</div>
        <div className="mx-auto w-full max-w-md">{footer}</div>
      </div>
    )
  }
  return (
    <div className="modal-overlay" style={{ zIndex: 'var(--z-dialog)' }} onClick={() => { if (!saving && step !== 'yours') skip() }}>
      <div ref={box} className="modal" role="dialog" aria-modal="true" aria-labelledby="wf-title" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 id="wf-title" className="modal-title">
            {mode === 'lite' ? <><span className="mr-1.5 rounded-full bg-(--accent) px-1.5 py-0.5 text-[0.6471rem] font-bold uppercase text-(--on-fill)">New</span>Tell Rabbit how you use it</>
              : 'How you use Rabbit'}
          </h2>
          <button type="button" className="modal-close" aria-label={mode === 'edit' ? 'Close' : 'Skip for now'}
            onClick={step === 'yours' ? () => onFinish({ saved: true, intents: picks, next: null }) : skip}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col overflow-y-auto pt-3">
          {mode === 'lite' && step === 'pick' && (
            <p className="mb-2 px-5 text-[0.7647rem] leading-snug text-(--text-muted)">
              Rabbit now does training, social support and finding events. Tell us what matters to you and we'll show that first.
            </p>
          )}
          {body}
          {progress}
          {footer}
        </div>
      </div>
    </div>
  )
}

/** Shows the welcome when /me says so (once), and again from Settings -> How you use Rabbit.
 *  Also publishes the current intents for useIntents(). */
export function WelcomeGate({ me, onSaved, onNext }: {
  me: Me
  /** refresh /me after saving */
  onSaved: () => void
  /** route to the chosen next step */
  onNext: (step: NextStep) => void
}) {
  const intents = intentsOf(me)
  useEffect(() => { setCurrentIntents(intents) }, [intents.join()]) // eslint-disable-line react-hooks/exhaustive-deps
  const auto = welcomeOf(me)
  const [done, setDone] = useState(false) // this session: don't re-open before /me catches up
  const [edit, setEdit] = useState(false)
  useEffect(() => onOpenWelcome(() => setEdit(true)), [])
  const mode: Mode | null = edit ? 'edit' : !done && auto && me.role === 'athlete' ? auto : null
  if (!mode) return null
  const hasPlan = !!(me.goal?.plan || me.goal?.plan_source)
  return (
    <WelcomeFlow key={mode} mode={mode} initial={intents} name={me.profile.name} garmin={me.garmin.connected} hasPlan={hasPlan}
      onFinish={(r) => {
        setDone(true); setEdit(false)
        if (r.saved) onSaved()
        if (r.next) onNext(r.next)
      }} />
  )
}
