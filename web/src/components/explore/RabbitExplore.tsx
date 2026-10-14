// "Let Rabbit explore": one tap -> RunSignup around you + Rabbit's web research for notable
// races, merged into one ranked row with a one-line "why" on every card.
import { useRef, useState } from 'react'
import { Rabbit, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { letRabbitExplore, type RabbitExploreResult, type RaceX } from '@/lib/explore2'
import { PickCard } from './ForYou'

const HOPS = ['Sniffing out start lines…', 'Hopping through race calendars…', 'Nibbling on course maps…',
  'Checking the big ones on the web…', 'Lining up tune-ups…']

export function RabbitExploreHero({ onOpen }: { onOpen: (r: RaceX) => void }) {
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
        className="flex w-full items-center gap-3 rounded-2xl bg-(--accent) px-4 py-3.5 text-left text-white shadow-sm active:scale-[0.99]">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-white/15"><Rabbit className="size-6" /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-[0.9412rem] font-semibold leading-snug">Let Rabbit explore</span>
          <span className="block text-[0.7059rem] leading-snug text-white/85">One tap: races near you and notable ones from the web, ranked for you</span>
        </span>
      </button>
    )
  }
  const note = res.web === 'limit' ? "Today's web searches are used up, so these are from race listings only."
    : res.web === 'failed' ? "The web search didn't answer, so these are from race listings only." : null
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-start gap-2 px-1">
        <Rabbit className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
        <p className="min-w-0 flex-1 text-[0.8235rem] leading-snug text-(--text)">{res.intro}</p>
        <Button variant="ghost" size="icon" className="size-11 shrink-0" aria-label="Explore again" onClick={() => void go()}>
          <RefreshCw className="size-4" />
        </Button>
      </div>
      {note && <p className="px-1 text-[0.7059rem] text-(--text-muted)">{note}</p>}
      {res.races.length > 0 && (
        <div className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1">
          {res.races.map((r) => <PickCard key={r.id} r={r} onClick={() => onOpen(r)} />)}
        </div>
      )}
      {res.races.some((r) => r.source === 'web') && (
        <p className="px-1 text-[0.6471rem] text-(--text-muted)">Some were found on the web by Rabbit. Check dates on the official site.</p>
      )}
    </section>
  )
}
