// "What brings you to Rabbit?": the welcome on first sign-in, a short friendly chat with one
// question per screen (full: hello -> what brings you -> where do you run -> how did you hear ->
// you're set), a lighter sheet once for people who were set up before this existed (lite: pick
// -> area -> set), and Settings -> "How you use Rabbit" (edit: pick -> set). The area step is
// skipped when an area is already saved. Then "Share your workouts with friends?" (the opt-in
// consent, community.py share_workouts; skipped once answered; Not now leaves it unanswered) with
// the map follow-up (MapShareAsk) after a yes. No Garmin here: "Connect a watch" comes later. Saves athlete.intents (tap order =
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
import { CalendarDays, Check, Share2, ChevronDown, ChevronRight, LocateFixed, MapPin, Sparkle, Compass, Flame, Target, UserRound, Users, X, type LucideIcon } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { HopIn, RabbitNap, burst, type RabbitPose } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { MapShareAsk } from '@/components/community/MapShareAsk'
import { inputCls } from '@/components/plan/ui'
import { announceArea, areaLabel } from '@/components/local/AreaBar'
import type { Me } from '@/lib/api'
import { cn } from '@/lib/utils'
import { getLocation, savePlaceLocation, shareDeviceLocation, type LocationState } from '@/lib/explore2'
import { HEARD_OPTIONS, saveHeard, type HeardSource } from '@/lib/traction'
import {
  INTENT_OPTIONS, intentsOf, onOpenWelcome, saveIntents, setCurrentIntents, skipWelcome, welcomeOf, welcomePlan,
  type Intent, type NextStep, QUICK_STARTS,
} from '@/lib/intent'
import { TAGLINE } from '@/lib/legal'
import { getCommunitySettings, putCommunitySettings, SHARE_CONSENT_LINE } from '@/lib/community'

const ICON: Record<Intent, LucideIcon> = {
  train: Target, community: Users, events: CalendarDays, consistent: Flame, coach: UserRound, explore: Compass,
}
const SAVING = ['Tuning rabbt to you…', 'Sorting your setup…', 'Stretching first…']

type Mode = 'full' | 'lite' | 'edit'
type Step = 'hello' | 'pick' | 'area' | 'heard' | 'share' | 'yours'

/** What rabbt says back after "What brings you here?" (shown on the next question). */
function reaction(intents: Intent[]): string {
  const local = intents.includes('events') || intents.includes('community')
  if (intents[0] === 'train' && local) return 'A plan and people to run with. Love it.'
  if (intents[0] === 'train') return 'A plan it is. Nice.'
  if (local) return "Let's find your people."
  return 'Good choice.'
}

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
  const [more, setMore] = useState(false)
  const [loc, setLoc] = useState<LocationState | null>(null)
  const [hadArea, setHadArea] = useState(false)
  const [place, setPlace] = useState('')
  const [areaBusy, setAreaBusy] = useState<'type' | 'locate' | null>(null)
  const [areaErr, setAreaErr] = useState<string | null>(null)
  const [heard, setHeard] = useState<HeardSource | null>(null)
  const [askShare, setAskShare] = useState(false)  // sharing never answered: ask in this flow
  const [share, setShare] = useState<'ask' | 'busy' | 'yes'>('ask')
  const [shareErr, setShareErr] = useState<string | null>(null)
  const cta = useRef<HTMLButtonElement>(null)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (mode === 'edit') return
    getLocation().then((l) => { setLoc(l); if (l.saved) setHadArea(true) }, () => {})
    getCommunitySettings().then((r) => {
      const s = r.settings
      setAskShare((s.sharing_source ?? (s.share_workouts == null ? 'unanswered' : 'yes')) === 'unanswered' && !s.share_prompted)
    }, () => {})  // not an athlete yet / offline: no share step
  }, [mode])

  const steps: Step[] = [
    ...(mode === 'full' ? ['hello' as const] : []),
    'pick',
    ...(mode !== 'edit' && !hadArea ? ['area' as const] : []),
    ...(mode === 'full' ? ['heard' as const] : []),
    ...(mode !== 'edit' && (askShare || step === 'share') ? ['share' as const] : []),
    'yours',
  ]
  const after = (s: Step): Step => steps[Math.min(steps.indexOf(s) + 1, steps.length - 1)]

  const toggle = (id: Intent) => setPicks((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const skip = () => {
    if (mode === 'edit') { onFinish({ saved: false, intents: null, next: null }); return }
    void skipWelcome().catch(() => {}) // best effort: seen either way on this device
    onFinish({ saved: true, intents: null, next: null })
  }
  // Once "What brings you" is saved, closing just finishes (the answer stands).
  const answered = steps.indexOf(step) > steps.indexOf('pick')
  const close = () => (answered ? onFinish({ saved: true, intents: picks, next: null }) : skip())
  useDialog(box, () => { if (!saving) close() })

  async function save(list: Intent[] = picks) {
    setSaving(true); setErr(null)
    try {
      await saveIntents(list)
      setCurrentIntents(list)
      setPicks(list)
      setStep(after('pick'))
    } catch (e) { setErr((e as Error).message || "Couldn't save just now.") }
    finally { setSaving(false) }
  }
  async function setArea(kind: 'type' | 'locate') {
    setAreaBusy(kind); setAreaErr(null)
    try {
      const l = kind === 'locate' ? await shareDeviceLocation() : await savePlaceLocation(place)
      setLoc(l)
      announceArea(l)
    } catch (e) { setAreaErr((e as Error).message || "Couldn't find that. Try a zip code.") }
    finally { setAreaBusy(null) }
  }
  function pickHeard(src: HeardSource) {
    setHeard(src)
    void saveHeard(src).catch(() => {}) // optional and best effort
    window.setTimeout(() => setStep(after('heard')), 280) // a beat to see the tick
  }
  async function answerShare(yes: boolean) {
    setShare('busy'); setShareErr(null)
    try {
      // "Not now" isn't a no: sharing stays unanswered, so the Home card can ask again later.
      await putCommunitySettings(yes ? { share_workouts: true, share_prompted: true } : { share_prompted: true })
      if (yes) setShare('yes')
      else { setShare('ask'); setStep(after('share')) }
    } catch (e) { setShareErr((e as Error).message || "Couldn't save just now."); setShare('ask') }
  }
  // The last screen lands with a small carrot burst from the main button.
  useEffect(() => {
    if (step !== 'yours') return
    const t = window.setTimeout(() => burst(cta.current, 'quest'), 240)
    return () => window.clearTimeout(t)
  }, [step])

  const plan = welcomePlan(picks, { garmin, hasPlan })
  const first = name?.split(' ')[0]
  const where = loc?.saved ? areaLabel(loc) : ''
  const typed = place.trim()
  const canType = /^\d{5}$/.test(typed) || /,\s*[a-z]{2,}/i.test(typed)

  const pose: RabbitPose = step === 'hello' ? 'wave' : step === 'pick' ? 'think'
    : step === 'area' ? (where ? 'cheer' : 'peek') : step === 'heard' ? (heard ? 'cheer' : 'wave')
      : step === 'share' ? (share === 'yes' ? 'cheer' : 'wave') : 'cheer'
  const art = (
    <span className="flex justify-center pt-5" key={`${step}-${pose}`}>
      <RabbitNap size={step === 'hello' ? 88 : 60} mode={pose} />
    </span>
  )
  const ask = (title: string, sub?: string, lead?: string) => (
    <HopIn className="flex flex-col items-center gap-1.5 px-1 text-center">
      {lead && <p className="text-body font-semibold text-(--accent)">{lead}</p>}
      <h2 className="font-display text-display-sm leading-tight text-(--brand)">{title}</h2>
      {sub && <p className="text-body leading-snug text-(--text-secondary)">{sub}</p>}
    </HopIn>
  )

  const body = step === 'hello' ? (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 px-6 text-center">
      <HopIn as="span">{art}</HopIn>
      <HopIn index={2} className="flex flex-col gap-3">
        <p className="text-body font-medium text-(--text-secondary)">{first ? `Hi ${first}! I'm rabbt.` : "Hi! I'm rabbt."}</p>
        <h1 className="font-display text-display leading-[1.15] text-(--brand)">{TAGLINE}</h1>
        <p className="text-lead leading-snug text-(--text-secondary)">A few quick taps and you're in.</p>
      </HopIn>
    </div>
  ) : step === 'pick' ? (
    <div className="flex flex-1 flex-col gap-4 px-5 pb-2">
      {art}
      {ask('What brings you here?', 'Pick one to start. You can do it all later.')}
      <div className="flex flex-col gap-2.5" role="group" aria-label="Start with">
        {QUICK_STARTS.map((q, i) => {
          const Icon = q.id === 'local' ? MapPin : q.id === 'plan' ? CalendarDays : Sparkle
          return (
            <HopIn key={q.id} index={i}>
              <button type="button" disabled={saving} onClick={() => void save(q.intents)}
                className={cn('flex min-h-[76px] w-full items-center gap-3.5 rounded-2xl border px-4 py-3.5 text-left active:scale-[0.98]',
                  q.id === 'both' ? 'border-(--border) bg-(--bg-surface)' : 'border-(--accent)/40 bg-(--accent-subtle)')}>
                <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-(--on-fill)">
                  <Icon className="size-6" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-lead font-semibold text-(--text)">{q.title}</span>
                  <span className="mt-0.5 block text-small leading-snug text-(--text-muted)">{q.help}</span>
                </span>
                <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
              </button>
            </HopIn>
          )
        })}
      </div>
      <button type="button" aria-expanded={more} onClick={() => setMore((m) => !m)}
        className="flex min-h-11 items-center gap-1.5 self-center px-1 text-body font-semibold text-(--accent)">
        Something else <ChevronDown className={cn('size-5 transition-transform', more && 'rotate-180')} aria-hidden />
      </button>
      {more && (
      <div className="flex flex-col gap-2.5" role="group" aria-label="What brings you to rabbt">
        <p className="px-1 text-small text-(--text-muted)">Pick all that fit. Tap the most important one first.</p>
        {INTENT_OPTIONS.map((o, i) => {
          const at = picks.indexOf(o.id)
          const on = at >= 0
          const Icon = ICON[o.id]
          return (
            <HopIn key={o.id} index={i}>
              <button type="button" aria-pressed={on} onClick={() => toggle(o.id)}
                className={cn('flex min-h-[68px] w-full items-center gap-3.5 rounded-2xl border px-4 py-3.5 text-left transition-colors active:scale-[0.99]',
                  on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
                <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-xl',
                  on ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-inset) text-(--text-secondary)')}>
                  <Icon className="size-6" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cn('block text-lead font-semibold', on ? 'text-(--accent)' : 'text-(--text)')}>{o.title}</span>
                  <span className="mt-0.5 block text-small leading-snug text-(--text-muted)">{o.help}</span>
                </span>
                <span aria-hidden="true" className={cn('flex size-7 shrink-0 items-center justify-center rounded-full border text-small font-bold',
                  on ? 'rb-pop border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')} key={on ? `on${at}` : 'off'}>
                  {on ? at + 1 : ''}
                </span>
              </button>
            </HopIn>
          )
        })}
      </div>
      )}
      {err && <p className="px-1 text-small text-(--danger)" role="alert">{err}</p>}
    </div>
  ) : step === 'area' ? (
    <div className="flex flex-1 flex-col gap-4 px-5 pb-2">
      {art}
      {where ? (
        <>
          {ask(`Near ${where}. Nice!`, "Near me will show runs, clubs and meetups around there. Change it any time.")}
        </>
      ) : (
        <>
          {ask('Where do you run?', 'Your city or zip, so Near me fills up with runs and clubs.', reaction(picks))}
          <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (canType) void setArea('type') }}>
            <label className="sr-only" htmlFor="wf-place">City and state, or zip code</label>
            <input id="wf-place" className={cn(inputCls, 'h-14 text-center text-lead')} autoComplete="address-level2"
              placeholder="Denver, CO or 80204" value={place} enterKeyHint="go"
              onChange={(e) => { setPlace(e.target.value.slice(0, 60)); setAreaErr(null) }} />
            <Button type="submit" variant="primary" className="h-12 w-full text-lead" disabled={!canType} loading={areaBusy === 'type'}>
              That's me
            </Button>
            {typed && !canType && <p className="m-0 -mt-1 text-center text-small text-(--text-secondary)">Add the state too, like Denver, CO</p>}
            <Button type="button" variant="default" className="h-12 w-full gap-2 text-body" loading={areaBusy === 'locate'}
              onClick={() => void setArea('locate')}>
              <LocateFixed className="size-5 text-(--accent)" aria-hidden /> Use my location
            </Button>
          </form>
          {areaErr && <p className="text-center text-small text-(--danger)" role="alert">{areaErr}</p>}
          <p className="text-center text-small text-(--text-muted)">rabbt keeps only a rough spot (about 1 km), never your exact location.</p>
        </>
      )}
    </div>
  ) : step === 'heard' ? (
    <div className="flex flex-1 flex-col gap-4 px-5 pb-2">
      {art}
      {ask(steps.includes('share') ? 'How did you hear about rabbt?' : 'Last one! How did you hear about rabbt?', 'Totally optional. It helps us find more runners like you.')}
      <div className="grid grid-cols-1 gap-2 min-[380px]:grid-cols-2" role="group" aria-label="How did you hear about rabbt">
        {HEARD_OPTIONS.map((o, i) => (
          <HopIn key={o.id} index={i}>
            <button type="button" aria-pressed={heard === o.id} disabled={heard !== null} onClick={() => pickHeard(o.id)}
              className={cn('flex min-h-14 w-full items-center justify-between gap-2 rounded-2xl border px-4 py-3 text-left text-body font-semibold active:scale-[0.98]',
                heard === o.id ? 'border-(--accent) bg-(--accent-subtle) text-(--accent)' : 'border-(--border) bg-(--bg-surface) text-(--text)')}>
              {o.label}
              {heard === o.id && <Check className="rb-pop size-5 shrink-0" aria-hidden />}
            </button>
          </HopIn>
        ))}
      </div>
    </div>
  ) : step === 'share' ? (
    <div className="flex flex-1 flex-col gap-4 px-5 pb-2">
      {art}
      {share === 'yes'
        ? ask('Your crew will see you move!', 'Your last few days are on the Feed now, and new workouts follow after each sync.', 'Sharing is on.')
        : ask('Share your workouts with friends?', SHARE_CONSENT_LINE, 'Last one!')}
      {share === 'yes' ? (
        <HopIn index={1}><MapShareAsk /></HopIn>
      ) : (
        <div className="flex flex-col gap-2.5" role="group" aria-label="Share your workouts with friends">
          <HopIn index={1}>
            <button type="button" disabled={share === 'busy'} onClick={() => void answerShare(true)}
              className="flex min-h-[76px] w-full items-center gap-3.5 rounded-2xl border border-(--accent)/40 bg-(--accent-subtle) px-4 py-3.5 text-left active:scale-[0.98] disabled:opacity-60">
              <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-(--on-fill)">
                <Share2 className="size-6" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-lead font-semibold text-(--text)">Yes, share</span>
                <span className="mt-0.5 block text-small leading-snug text-(--text-muted)">Friends cheer your runs on the Feed. Turn it off any time.</span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
            </button>
          </HopIn>
          <p className="m-0 px-1 text-center text-small text-(--text-muted)">Only people who follow you. Never your heart rate, never sold.</p>
        </div>
      )}
      {shareErr && <p className="px-1 text-center text-small text-(--danger)" role="alert">{shareErr}</p>}
    </div>
  ) : (
    <div className="flex flex-1 flex-col gap-4 px-5">
      {art}
      {ask(first ? `You're all set, ${first}!` : "You're all set!", "Here's what rabbt has ready for you:")}
      <ul className="flex flex-col gap-2.5">
        {plan.bullets.map((b, i) => (
          <HopIn as="li" key={b} index={i + 1} className="flex items-start gap-3.5 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
            <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)"><Check className="size-4" /></span>
            <span className="text-body-lg leading-snug text-(--text)">{b}</span>
          </HopIn>
        ))}
      </ul>
      <p className="text-center text-small text-(--text-muted)">Change this any time in Me, under How you use rabbt.</p>
    </div>
  )

  const footer = (
    <div className="flex flex-col gap-1 px-5 pb-[max(16px,env(safe-area-inset-bottom))] pt-3">
      {step === 'hello' && (
        <Button variant="primary" className="h-12 w-full text-lead" onClick={() => setStep('pick')}>
          Let's go <ChevronRight className="ml-1 size-5" />
        </Button>
      )}
      {step === 'pick' && (saving ? (
        <div className="flex h-12 items-center justify-center"><RabbitLoader inline size={24} label={SAVING[0]} cycle={SAVING} /></div>
      ) : more ? (
        <Button variant="primary" className="h-12 w-full text-lead" disabled={!picks.length} onClick={() => void save()}>
          {err ? 'Try again' : picks.length ? 'Continue' : 'Pick at least one'}
        </Button>
      ) : null)}
      {step === 'area' && where && (
        <Button variant="primary" className="h-12 w-full text-lead" onClick={() => setStep(after('area'))}>
          Next <ChevronRight className="ml-1 size-5" />
        </Button>
      )}
      {step === 'share' && share === 'yes' && (
        <Button variant="primary" className="h-12 w-full text-lead" onClick={() => setStep(after('share'))}>
          Next <ChevronRight className="ml-1 size-5" />
        </Button>
      )}
      {step === 'yours' && (
        <Button ref={cta} variant="primary" className="h-12 w-full text-lead"
          onClick={() => onFinish({ saved: true, intents: picks, next: plan.next?.step ?? null })}>
          {plan.next?.label ?? "Let's go"} <ChevronRight className="ml-1 size-5" />
        </Button>
      )}
      {step === 'area' && !where ? (
        <button type="button" className="min-h-11 text-body text-(--text-muted) underline-offset-2 active:underline"
          onClick={() => setStep(after('area'))}>Not now</button>
      ) : step === 'share' ? (share === 'yes' ? null : (
        <button type="button" className="min-h-11 text-body text-(--text-muted) underline-offset-2 active:underline"
          disabled={share === 'busy'} onClick={() => void answerShare(false)}>Not now</button>
      )) : step === 'heard' ? (
        <button type="button" className="min-h-11 text-body text-(--text-muted) underline-offset-2 active:underline"
          disabled={heard !== null} onClick={() => setStep(after('heard'))}>Skip</button>
      ) : step === 'yours' ? (plan.next ? (
        <button type="button" className="min-h-11 text-body text-(--text-muted) underline-offset-2 active:underline"
          onClick={() => onFinish({ saved: true, intents: picks, next: null })}>Look around first</button>
      ) : null) : step !== 'area' ? (
        <button type="button" className="min-h-11 text-body text-(--text-muted) underline-offset-2 active:underline" onClick={skip}>
          {mode === 'edit' ? 'Cancel' : 'Skip for now'}
        </button>
      ) : null}
    </div>
  )

  const at = steps.indexOf(step)
  const progress = (
    <div className="flex items-center justify-center gap-1.5 py-2" role="progressbar" aria-label="Setup"
      aria-valuemin={1} aria-valuemax={steps.length} aria-valuenow={at + 1}>
      {steps.map((d, i) => (
        <span key={d} className={cn('h-1.5 rounded-full transition-all duration-200',
          d === step ? 'w-6 bg-(--accent)' : i < at ? 'w-1.5 bg-(--accent)' : 'w-1.5 bg-(--border-strong)')} />
      ))}
    </div>
  )

  if (mode === 'full') {
    return (
      <div ref={box} className="fixed inset-0 flex flex-col bg-(--bg) pt-[max(10px,env(safe-area-inset-top))]" style={{ zIndex: 'var(--z-dialog)' }}
        role="dialog" aria-modal="true" aria-label="Welcome to rabbt">
        <div className="flex items-center justify-between px-2">
          <span className="w-11" />
          {progress}
          {step !== 'yours' ? (
            <button type="button" className="flex size-11 items-center justify-center text-(--text-muted)" aria-label={answered ? 'Finish later' : 'Skip for now'} onClick={close}>
              <X className="size-6" />
            </button>
          ) : <span className="w-11" />}
        </div>
        <div className="mx-auto flex min-h-0 w-full max-w-md flex-1 flex-col overflow-y-auto" key={step}>{body}</div>
        <div className="mx-auto w-full max-w-md">{footer}</div>
      </div>
    )
  }
  return (
    <div className="modal-overlay" style={{ zIndex: 'var(--z-dialog)' }} onClick={() => { if (!saving) close() }}>
      <div ref={box} className="modal" role="dialog" aria-modal="true" aria-labelledby="wf-title" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 id="wf-title" className="modal-title">
            {mode === 'lite' ? <><span className="mr-2 rounded-full bg-(--accent) px-2 py-0.5 text-caption font-semibold text-(--on-fill)">New</span>Tell rabbt how you use it</>
              : 'How you use rabbt'}
          </h2>
          <button type="button" className="modal-close" aria-label={mode === 'edit' ? 'Close' : 'Skip for now'} onClick={close}><X className="size-5" /></button>
        </div>
        <div className="modal-body flex flex-col overflow-y-auto pt-3">
          {mode === 'lite' && step === 'pick' && (
            <p className="mb-3 px-6 text-small leading-snug text-(--text-muted)">
              rabbt now helps you find runs and clubs near you, and follow a plan. Tell us what matters most and we'll show that first.
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
