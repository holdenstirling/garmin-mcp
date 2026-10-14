// "Let Rabbit explore": one tap, no typing. A small card under the first row of For you picks.
// The tap asks for two parts in parallel (same tap id, so it costs one of the day's web
// searches): races (For you listings + an AI web scout, run together on the server) and near
// you (places + groups). Each section shows its own loader and stage label and pops in as soon
// as it lands (.ex-* in styles/rabbit.css; reduced motion just fades).
import { useRef, useState } from 'react'
import { Check, Rabbit, RefreshCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import {
  newTap, rabbitExploreNear, rabbitExploreRaces, type RabbitNear, type RabbitRaces, type RaceX,
} from '@/lib/explore2'
import { PickCard } from './ForYou'
import { CardRow, GroupCard, PlaceCard, WEB_NOTE } from './LocalActivities'

const RACE_HOPS = ['Sniffing out start lines…', 'Hopping through race calendars…', 'Checking the big ones on the web…', 'Lining up tune-ups…']
const NEAR_HOPS = ['Peeking at courts and tracks nearby…', 'Asking around for group runs…', 'Checking the map…']

type Part<T> = { state: 'busy' } | { state: 'ok'; data: T } | { state: 'error'; message: string }

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{children}</h3>
}

function Stage({ label, cycle }: { label: string; cycle: string[] }) {
  return (
    <div className="flex justify-center rounded-2xl border border-(--border) bg-(--bg-surface) py-4" aria-busy>
      <RabbitLoader inline label={label} cycle={cycle} />
    </div>
  )
}

/** "Races ✓ · Near you …": which parts have landed. */
function Stages({ races, near }: { races: Part<unknown> | null; near: Part<unknown> | null }) {
  const one = (label: string, p: Part<unknown> | null) => (
    <span className="inline-flex items-center gap-1">
      {p?.state === 'busy' ? <RabbitLoader inline decorative size={14} /> : p?.state === 'ok' ? <Check className="size-3.5 text-(--accent)" /> : <X className="size-3.5 text-(--danger)" />}
      {label}
    </span>
  )
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 px-1 text-[0.6471rem] text-(--text-muted)" aria-live="polite">
      {one('Races', races)}{one('Near you', near)}
    </p>
  )
}

export function LetRabbitExplore({ onOpen, onAsk, imperial }: {
  onOpen: (r: RaceX) => void
  onAsk: (text: string) => void
  imperial: boolean
}) {
  const [races, setRaces] = useState<Part<RabbitRaces> | null>(null)
  const [near, setNear] = useState<Part<RabbitNear> | null>(null)
  const seq = useRef(0)

  function go() {
    const n = ++seq.current
    const tap = newTap()
    setRaces({ state: 'busy' }); setNear({ state: 'busy' })
    rabbitExploreRaces(tap).then((data) => { if (n === seq.current) setRaces({ state: 'ok', data }) },
      (e) => { if (n === seq.current) setRaces({ state: 'error', message: (e as Error).message }) })
    rabbitExploreNear(tap).then((data) => { if (n === seq.current) setNear({ state: 'ok', data }) },
      (e) => { if (n === seq.current) setNear({ state: 'error', message: (e as Error).message }) })
  }
  const hide = () => { seq.current++; setRaces(null); setNear(null) }

  if (!races && !near) {
    return (
      <button type="button" onClick={go}
        className="ex-cta flex min-h-11 w-full items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3 py-2.5 text-left">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--accent) text-white"><Rabbit className="ex-hop size-5" /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-[0.8235rem] font-semibold leading-snug text-(--accent)">Let Rabbit explore</span>
          <span className="block text-[0.6471rem] leading-snug text-(--text-muted)">Races, notable events and things to do near you · uses 1 of 5 daily searches</span>
        </span>
      </button>
    )
  }

  const r = races?.state === 'ok' ? races.data : null
  const nb = near?.state === 'ok' ? near.data : null
  const done = races?.state !== 'busy' && near?.state !== 'busy'
  const count = (r?.races.length ?? 0) + (nb?.places.length ?? 0) + (nb?.groups.length ?? 0)
  const note = r?.web === 'limit' ? "Today's web searches are used up, so races come from listings only."
    : r?.web === 'failed' ? "The web search didn't answer, so races come from listings only." : null
  let i = 0  // stagger index across every revealed card
  const delay = () => ({ '--i': Math.min(i++, 12) } as React.CSSProperties)
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-start gap-2 px-1">
        <span className="ex-count flex size-9 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-white"><Rabbit className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="ex-count text-[0.9412rem] font-semibold leading-snug text-(--text)">
            {done ? (count ? `Rabbit found ${count} thing${count === 1 ? '' : 's'} for you` : 'Rabbit is back') : 'Rabbit is exploring…'}
          </p>
          {r?.intro && <p className="text-[0.7059rem] leading-snug text-(--text-muted)">{r.intro}</p>}
        </div>
        <Button variant="ghost" size="icon" className="size-11 shrink-0" aria-label="Explore again" disabled={!done} onClick={go}>
          <RefreshCw className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-11 shrink-0" aria-label="Hide" onClick={hide}>
          <X className="size-4" />
        </Button>
      </div>
      {!done && <Stages races={races} near={near} />}

      {races?.state === 'busy' && <Stage label="Finding races" cycle={RACE_HOPS} />}
      {races?.state === 'error' && <ErrorState compact message={`Races: ${races.message}`} onRetry={go} />}
      {note && <p className="px-1 text-[0.7059rem] text-(--text-muted)">{note}</p>}
      {r?.nationwide && r.location.note && <p className="px-1 text-[0.7059rem] text-(--text-muted)">{r.location.note}</p>}
      {r && r.races.length > 0 && (
        <div className="flex flex-col gap-2">
          <Heading>Races</Heading>
          <CardRow>{r.races.map((x) => <PickCard key={x.id} r={x} onClick={() => onOpen(x)} className="ex-pop" style={delay()} />)}</CardRow>
          {r.races.some((x) => x.source === 'web') && (
            <p className="px-1 text-[0.6471rem] text-(--text-muted)">Some were found on the web by Rabbit. Check dates on the official site.</p>
          )}
        </div>
      )}

      {near?.state === 'busy' && <Stage label="Looking nearby" cycle={NEAR_HOPS} />}
      {near?.state === 'error' && <ErrorState compact message={`Near you: ${near.message}`} onRetry={go} />}
      {nb && nb.groups.length > 0 && (
        <div className="flex flex-col gap-2">
          <Heading>Groups near you</Heading>
          <CardRow>{nb.groups.map((a) => <GroupCard key={a.id} a={a} onAsk={onAsk} className="ex-pop" style={delay()} />)}</CardRow>
          <p className="px-1 text-[0.6471rem] text-(--text-muted)">{WEB_NOTE}</p>
        </div>
      )}
      {nb && nb.places.length > 0 && (
        <div className="flex flex-col gap-2">
          <Heading>Places to play</Heading>
          <CardRow>{nb.places.map((p) => <PlaceCard key={p.id} p={p} imperial={imperial} onAsk={onAsk} className="ex-pop" style={delay()} />)}</CardRow>
        </div>
      )}
      {nb?.places_state === 'busy' && (
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">The map is busy right now. Tap explore again in a few seconds for places.</p>
      )}
      {nb?.places_state === 'needs_location' && (
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">Add your location to see courts, tracks and groups near you too.</p>
      )}
    </section>
  )
}
