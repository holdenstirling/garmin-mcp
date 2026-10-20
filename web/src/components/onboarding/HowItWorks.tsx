// "How rabbt works": five short cards (swipe or Next) for anyone who isn't sure where to go.
// Opens from Me, Home's footer link and Settings via openHowItWorks(); HowItWorksHost lives in
// the app shell.
import { useEffect, useRef, useState } from 'react'
import { CalendarDays, MapPin, MessageCircle, Newspaper, ShieldCheck, type LucideIcon } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const EVENT = 'rabbit:how-it-works'
export const openHowItWorks = () => window.dispatchEvent(new Event(EVENT))

const CARDS: { icon: LucideIcon; title: string; body: string; where: string }[] = [
  { icon: MapPin, title: 'Find things to do near you', body: 'Clubs, group runs, leagues and events around you, on a list or a map. Join one, or create your own event and invite people.', where: 'Local tab' },
  { icon: CalendarDays, title: 'Get a plan that fits your life', body: 'Tell rabbt your race or just your goal. Your plan adjusts when you travel, get sick or have a busy week.', where: 'Schedule tab' },
  { icon: Newspaper, title: 'Share with your people', body: 'Your workouts can post to friends automatically. Cheer, comment and tag people with @.', where: 'Feed tab' },
  { icon: MessageCircle, title: 'Ask rabbt anything', body: 'Why is this workout here? What should I eat before my long run? Ask from Home or any workout.', where: 'Home, Chat' },
  { icon: ShieldCheck, title: 'Your data stays yours', body: 'We never sell your data or use it for ads. Download or delete it any time.', where: 'Me, Privacy & legal' },
]

function Guide({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0)
  const track = useRef<HTMLDivElement>(null)
  const go = (n: number) => {
    const el = track.current
    if (!el) return
    el.scrollTo({ left: n * el.clientWidth, behavior: 'smooth' })
  }
  const onScroll = () => {
    const el = track.current
    if (el) setI(Math.round(el.scrollLeft / Math.max(1, el.clientWidth)))
  }
  const last = i >= CARDS.length - 1
  return (
    <Sheet title="How rabbt works" onClose={onClose} portal
      footer={(
        <div className="flex flex-col gap-3">
          <div className="flex justify-center gap-1.5" aria-hidden>
            {CARDS.map((c, n) => <span key={c.title} className={cn('h-1.5 rounded-full transition-all', n === i ? 'w-5 bg-(--accent)' : 'w-1.5 bg-(--border-strong)')} />)}
          </div>
          <Button variant="primary" className="h-12 w-full" onClick={() => (last ? onClose() : go(i + 1))}>{last ? 'Got it' : 'Next'}</Button>
        </div>
      )}>
      <div ref={track} onScroll={onScroll} className="flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain [scrollbar-width:none]"
        role="group" aria-roledescription="carousel" aria-label="How rabbt works">
        {CARDS.map((c, n) => {
          const Icon = c.icon
          return (
            <section key={c.title} aria-label={`${n + 1} of ${CARDS.length}: ${c.title}`}
              className="flex w-full shrink-0 snap-center flex-col items-start gap-3 px-5 py-5">
              <span className="flex size-14 items-center justify-center rounded-2xl bg-(--accent-subtle) text-(--accent)"><Icon className="size-7" aria-hidden /></span>
              <h3 className="font-display text-title-md leading-tight text-(--brand)">{c.title}</h3>
              <p className="text-body-lg leading-snug text-(--text)">{c.body}</p>
              <p className="text-small text-(--text-muted)">Where: {c.where}</p>
            </section>
          )
        })}
      </div>
    </Sheet>
  )
}

export function HowItWorksHost() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const on = () => setOpen(true)
    window.addEventListener(EVENT, on)
    return () => window.removeEventListener(EVENT, on)
  }, [])
  return open ? <Guide onClose={() => setOpen(false)} /> : null
}
