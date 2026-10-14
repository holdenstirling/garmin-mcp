// "Let Rabbit explore": one tap, no typing. Rabbit runs For you (races around you, or across
// the US), an AI web scout for notable races, and Near you (places + groups), then reveals it
// all with a little hop: "Rabbit found 12 things for you", cards popping in one by one
// (.ex-* in styles/rabbit.css; reduced motion just fades).
import { useRef, useState } from 'react'
import { Rabbit, RefreshCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { letRabbitExplore, type RabbitExploreResult, type RaceX } from '@/lib/explore2'
import { PickCard } from './ForYou'
import { CardRow, GroupCard, PlaceCard, WEB_NOTE } from './LocalActivities'

const HOPS = ['Sniffing out start lines…', 'Hopping through race calendars…', 'Checking the big ones on the web…',
  'Peeking at courts and tracks nearby…', 'Asking around for group runs…', 'Lining up tune-ups…']

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{children}</h3>
}

export function LetRabbitExplore({ onOpen, onAsk, imperial }: {
  onOpen: (r: RaceX) => void
  onAsk: (text: string) => void
  imperial: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<RabbitExploreResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)

  async function go() {
    const n = ++seq.current
    setBusy(true); setError(null)
    try { const r = await letRabbitExplore(); if (n === seq.current) setRes(r) }
    catch (e) { if (n === seq.current) setError((e as Error).message) }
    finally { if (n === seq.current) setBusy(false) }
  }

  if (busy) {
    return (
      <section className="flex justify-center rounded-2xl border border-(--border) bg-(--bg-surface) py-6" aria-busy>
        <RabbitLoader label="Rabbit is exploring" cycle={HOPS} />
      </section>
    )
  }
  if (error) return <ErrorState message={`Rabbit couldn't explore just now: ${error}`} onRetry={() => void go()} />
  if (!res) {
    return (
      <button type="button" onClick={() => void go()}
        className="ex-cta flex w-full items-center gap-3 rounded-2xl bg-(--accent) px-4 py-3.5 text-left text-white shadow-sm">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-white/15"><Rabbit className="ex-hop size-6" /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-[0.9412rem] font-semibold leading-snug">Let Rabbit explore</span>
          <span className="block text-[0.7059rem] leading-snug text-white/85">One tap: races, notable events and things to do near you</span>
        </span>
      </button>
    )
  }

  const note = res.web === 'limit' ? "Today's web searches are used up, so races come from listings only."
    : res.web === 'failed' ? "The web search didn't answer, so races come from listings only." : null
  let i = 0  // stagger index across every revealed card
  const delay = () => ({ '--i': Math.min(i++, 12) } as React.CSSProperties)
  return (
    <section className="flex flex-col gap-3" aria-live="polite">
      <div className="flex items-start gap-2 px-1">
        <span className="ex-count flex size-9 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-white"><Rabbit className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="ex-count text-[0.9412rem] font-semibold leading-snug text-(--text)">{res.summary}</p>
          <p className="text-[0.7059rem] leading-snug text-(--text-muted)">{res.intro}</p>
        </div>
        <Button variant="ghost" size="icon" className="size-11 shrink-0" aria-label="Explore again" onClick={() => void go()}>
          <RefreshCw className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-11 shrink-0" aria-label="Hide" onClick={() => setRes(null)}>
          <X className="size-4" />
        </Button>
      </div>
      {note && <p className="px-1 text-[0.7059rem] text-(--text-muted)">{note}</p>}
      {res.nationwide && res.location.note && <p className="px-1 text-[0.7059rem] text-(--text-muted)">{res.location.note}</p>}
      {res.races.length > 0 && (
        <div className="flex flex-col gap-2">
          <Heading>Races</Heading>
          <CardRow>{res.races.map((r) => <PickCard key={r.id} r={r} onClick={() => onOpen(r)} className="ex-pop" style={delay()} />)}</CardRow>
          {res.races.some((r) => r.source === 'web') && (
            <p className="px-1 text-[0.6471rem] text-(--text-muted)">Some were found on the web by Rabbit. Check dates on the official site.</p>
          )}
        </div>
      )}
      {res.groups.length > 0 && (
        <div className="flex flex-col gap-2">
          <Heading>Groups near you</Heading>
          <CardRow>{res.groups.map((a) => <GroupCard key={a.id} a={a} onAsk={onAsk} className="ex-pop" style={delay()} />)}</CardRow>
          <p className="px-1 text-[0.6471rem] text-(--text-muted)">{WEB_NOTE}</p>
        </div>
      )}
      {res.places.length > 0 && (
        <div className="flex flex-col gap-2">
          <Heading>Places to play</Heading>
          <CardRow>{res.places.map((p) => <PlaceCard key={p.id} p={p} imperial={imperial} onAsk={onAsk} className="ex-pop" style={delay()} />)}</CardRow>
        </div>
      )}
      {res.places_state === 'needs_location' && (
        <p className="px-1 text-[0.7059rem] text-(--text-muted)">Add your location to see courts, tracks and groups near you too.</p>
      )}
    </section>
  )
}
