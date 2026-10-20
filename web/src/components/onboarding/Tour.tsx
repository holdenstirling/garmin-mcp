// First-run tour: six quick coach marks over the tab bar and search (about a minute). A
// spotlight rings the real control and a small card explains it; Next / Back / Skip, Escape
// and the phone's Back close it (useDialog), focus stays in the card. Shown once per account
// on this device, after nothing else is open (welcome flow, setup, sheets); again from
// Me > Take the tour (lib/tour startTour). Targets are `[data-tour=...]` attributes.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { useDialog } from '@/hooks/useDialog'
import { openOverlayCount, prefersReducedMotion } from '@/lib/overlays'
import { TOUR_EVENT, markTourDone, tourDone } from '@/lib/tour'

type Step = { target: string; title: string; body: string }
const STEPS: Step[] = [
  { target: 'tab-rabbit', title: 'Today', body: "What to do today: your workout, runs near you tonight and your next step. Tap Ask rabbt at the bottom to ask your coach anything." },
  { target: 'tab-plan', title: 'Plan', body: 'Your training plan and your calendar. Tap a day for the full workout; move it if life gets in the way.' },
  { target: 'tab-feed', title: 'Friends', body: "What your friends and groups are up to. Make a group with just a few people." },
  { target: 'tab-clubs', title: 'Near me', body: 'Runs, clubs, leagues and events near you, on a list or a map. Post a run for others to join.' },
  { target: 'tab-progress', title: 'Progress', body: 'How your fitness is trending, in plain words.' },
  { target: 'chat', title: 'Messages', body: 'Messages with friends and your coach. To ask rabbt, use the Ask rabbt bar on Today.' },
  { target: 'search', title: 'Search', body: 'Find people, clubs, races and workouts (planned or done) from any screen.' },
]
const PAD = 6

function findTarget(name: string): HTMLElement | null {
  const all = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`))
  return all.find((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 }) ?? null
}

export function Tour({ userId, auto, onStart }: {
  userId: string
  /** may start on its own (signed in, an athlete, not mid-setup) */
  auto: boolean
  /** close pages/sheets so the tab bar is visible */
  onStart?: () => void
}) {
  const [step, setStep] = useState<number | null>(null)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const card = useRef<HTMLDivElement>(null)

  const finish = useCallback(() => { markTourDone(userId); setStep(null) }, [userId])
  const begin = useCallback(() => { onStart?.(); setStep(0) }, [onStart])

  // Manual start (Me > Take the tour).
  useEffect(() => {
    const on = () => window.setTimeout(begin, 350) // let the page close first
    window.addEventListener(TOUR_EVENT, on)
    return () => window.removeEventListener(TOUR_EVENT, on)
  }, [begin])

  // First run: once nothing else is on screen for a moment.
  useEffect(() => {
    if (!auto || tourDone(userId) || step !== null) return
    let calm = 0
    const t = window.setInterval(() => {
      const busy = openOverlayCount() > 0 || !!document.querySelector('.page-stack, .modal-overlay') || document.visibilityState !== 'visible'
      calm = busy ? 0 : calm + 1
      if (calm >= 2) { window.clearInterval(t); setStep(0) }
    }, 1000)
    return () => window.clearInterval(t)
  }, [auto, userId, step])

  useLayoutEffect(() => {
    if (step === null) return
    const measure = () => {
      const el = findTarget(STEPS[step]!.target)
      setRect(el ? el.getBoundingClientRect() : null)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [step])

  useDialog(card, step === null ? undefined : finish)
  useEffect(() => { if (step !== null) card.current?.querySelector<HTMLButtonElement>('[data-primary]')?.focus({ preventScroll: true }) }, [step])

  if (step === null) return null
  const s = STEPS[step]!
  const last = step === STEPS.length - 1
  const vh = window.innerHeight
  // Card above the target when it's in the lower half (the tab bar), else below it.
  const below = rect ? rect.top + rect.height / 2 < vh / 2 : false
  const cardPos: React.CSSProperties = !rect ? { top: '50%', transform: 'translateY(-50%)' }
    : below ? { top: Math.min(rect.bottom + PAD + 12, vh - 220) } : { bottom: Math.max(vh - rect.top + PAD + 12, 16) }
  const anim = prefersReducedMotion() ? '' : ' transition-all duration-300'

  return (
    <div className="fixed inset-0" style={{ zIndex: 'var(--z-dialog)' }}>
      {/* Dim everything; the ring's huge shadow leaves the target lit. Tapping outside skips. */}
      <div className="absolute inset-0" onClick={finish} aria-hidden />
      {rect ? (
        <div aria-hidden className={`pointer-events-none absolute rounded-2xl ring-2 ring-(--accent)${anim}`}
          style={{ left: rect.left - PAD, top: rect.top - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
            boxShadow: '0 0 0 9999px rgb(0 0 0 / 0.55)' }} />
      ) : <div aria-hidden className="pointer-events-none absolute inset-0 bg-black/55" />}
      <div ref={card} role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" tabIndex={-1}
        className={`absolute inset-x-5 mx-auto max-w-sm rounded-2xl border border-(--border) bg-(--bg-surface) p-5 shadow-xl${anim}`}
        style={cardPos}>
        <div className="flex items-start gap-3">
          <span aria-hidden className="logo-tile flex size-9 shrink-0 items-center justify-center rounded-xl bg-(--brand)"><RabbitLogo size={28} /></span>
          <div className="min-w-0 flex-1">
            <p className="text-meta font-medium text-(--text-muted)">
              {step + 1} of {STEPS.length}
            </p>
            <h2 id="tour-title" className="font-display text-title leading-tight text-(--text)">{s.title}</h2>
            <p id="tour-body" className="mt-1 text-body leading-snug text-(--text-secondary)">{s.body}</p>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-2">
          <button type="button" onClick={finish} className="min-h-11 px-2 text-body font-medium text-(--text-secondary)">
            {last ? 'Close' : 'Skip tour'}
          </button>
          <span className="flex-1" />
          {step > 0 && (
            <button type="button" onClick={() => setStep(step - 1)}
              className="min-h-11 rounded-full border border-(--border) px-4 text-body font-medium text-(--text)">Back</button>
          )}
          <button type="button" data-primary onClick={() => (last ? finish() : setStep(step + 1))}
            className="min-h-11 rounded-full bg-(--accent) px-5 text-body font-semibold text-(--on-fill)">
            {last ? 'Got it' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
