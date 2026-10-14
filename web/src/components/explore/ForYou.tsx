// Explore "For you": personal race picks in horizontal snap-scroll rows (Picked for you, Tune-ups,
// Coming up near you, Your friends are racing, Bucket list). Every card says why it's here.
// Tap a card for the usual RaceDetail (add to races, ask Rabbit, register).
import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Pencil, RefreshCw, Sparkles, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { placeOf, raceDate } from '@/lib/explore'
import {
  fetchBucket, getForYou, hasInterests, interestsSummary,
  type ForYouFeed, type ForYouRace, type ForYouSection, type Interests,
} from '@/lib/foryou'
import { CATEGORY_ICON, HINT_CLS } from './icons'

const ASKED_KEY = 'rabbit.explore.interests.asked'
const SCOUT = ['Scouting races for you…', 'Checking your calendar…', 'Lining up tune-ups…', 'Asking around the start line…']

function asked(): boolean {
  try { return localStorage.getItem(ASKED_KEY) === '1' } catch { return true }
}
function markAsked(): void {
  try { localStorage.setItem(ASKED_KEY, '1') } catch { /* private mode */ }
}

/** Feed state for the For you view (the sheet trigger lives here so the header can share it). */
export function useForYou(active: boolean) {
  const [feed, setFeed] = useState<ForYouFeed | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [bucketBusy, setBucketBusy] = useState(false)
  const [bucketError, setBucketError] = useState<string | null>(null)
  const [askNow, setAskNow] = useState(false)
  const seq = useRef(0)
  const bucketTried = useRef(false)

  const load = useCallback((fresh = false) => {
    const n = ++seq.current
    setLoading(true); setError(null)
    getForYou(fresh).then((f) => {
      if (n !== seq.current) return
      setFeed(f)
      if (!f.has_interests && !asked()) { markAsked(); setAskNow(true) }
    }, (e) => { if (n === seq.current) setError((e as Error).message) })
      .finally(() => { if (n === seq.current) setLoading(false) })
  }, [])

  useEffect(() => { if (active && !feed && !loading && !error) load() }, [active, feed, loading, error, load])

  // Bucket list: the server allows one web search a week; ask once per visit when it's due.
  useEffect(() => {
    if (!feed?.bucket.due || bucketTried.current) return
    bucketTried.current = true
    setBucketBusy(true); setBucketError(null)
    fetchBucket().then(({ section }) => setFeed((f) => f && ({
      ...f, bucket: { ...f.bucket, due: false },
      sections: [...f.sections.filter((s) => s.id !== 'bucket'), ...(section.races.length ? [section] : [])],
    })), (e) => setBucketError((e as Error).message)).finally(() => setBucketBusy(false))
  }, [feed?.bucket.due])

  const saved = (i: Interests) => {
    setFeed((f) => f && { ...f, interests: i, has_interests: hasInterests(i) })
    bucketTried.current = false
    load()
  }
  return { feed, loading, error, load, saved, bucketBusy, bucketError, askNow, clearAsk: () => setAskNow(false) }
}

/** "Your interests" chip summary + edit, for the Explore header. */
export function InterestsStrip({ interests, onEdit }: { interests: Interests | null | undefined; onEdit: () => void }) {
  const chips = interestsSummary(interests)
  return (
    <button type="button" onClick={onEdit}
      className="mx-auto mt-2 flex min-h-11 w-full max-w-xl items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-1.5 text-left active:bg-(--bg-inset)">
      <span className="shrink-0 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Your interests</span>
      <span className="no-scrollbar flex min-w-0 flex-1 gap-1 overflow-x-auto">
        {chips.length ? chips.map((c) => (
          <span key={c} className="shrink-0 rounded-full bg-(--accent-subtle) px-2 py-0.5 text-[0.6471rem] font-medium text-(--accent)">{c}</span>
        )) : <span className="text-[0.7059rem] text-(--text-secondary)">Tell Rabbit what you're into</span>}
      </span>
      <Pencil className="size-3.5 shrink-0 text-(--text-muted)" aria-label="Edit" />
    </button>
  )
}

export function ForYouFeedView({ state, onOpen, onEdit, onSearch }: {
  state: ReturnType<typeof useForYou>
  onOpen: (r: ForYouRace) => void
  onEdit: () => void
  onSearch: () => void
}) {
  const { feed, loading, error, load, bucketBusy, bucketError } = state
  if (!feed && (loading || !error)) {
    return <div className="flex justify-center py-16"><RabbitLoader label="Scouting races for you" cycle={SCOUT} /></div>
  }
  if (!feed) return <ErrorState message={`Couldn't load your picks: ${error}`} onRetry={() => load()} />

  const empty = feed.sections.length === 0
  return (
    <div className={cn('flex flex-col gap-6 transition-opacity', loading && 'opacity-50')} aria-busy={loading}>
      {!feed.has_interests && (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-(--accent) bg-(--accent-subtle) px-4 py-5 text-center">
          <Sparkles className="size-6 text-(--accent)" />
          <p className="text-[0.9412rem] font-medium text-(--text)">Get races picked just for you</p>
          <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-secondary)">
            Four quick taps: what you race, how far, the vibe, and how far you'll travel.
          </p>
          <Button variant="primary" className="h-11 px-5 text-[0.8235rem]" onClick={onEdit}>What are you into? · +50 XP</Button>
        </div>
      )}
      {feed.failed && (
        <div className="flex items-center gap-2 rounded-xl bg-(--warning-subtle) px-3 py-2 text-[0.7059rem] text-(--warning-text)" role="status">
          <span className="flex-1">Race search isn't answering right now, so picks are missing. Showing what we have.</span>
          <button type="button" className="hit-44 inline-flex items-center gap-1 font-medium" onClick={() => load(true)}>
            <RefreshCw className="size-3.5" /> Retry
          </button>
        </div>
      )}
      {feed.has_interests && !feed.zip && (
        <button type="button" onClick={onEdit} className="min-h-11 rounded-xl bg-(--bg-elevated) px-3 py-2 text-left text-[0.7059rem] text-(--text-secondary)">
          Add your home zip to see races near you.
        </button>
      )}
      {feed.sections.map((s) => <Section key={s.id} s={s} onOpen={onOpen} />)}
      {bucketBusy && (
        <section className="flex flex-col gap-2">
          <SectionTitle s={{ id: 'bucket', title: 'Bucket list', races: [], source: 'web' }} />
          <div className="flex justify-center rounded-2xl border border-(--border) py-6">
            <RabbitLoader inline label="Searching the web" cycle={['Looking up legendary races…', 'Checking race dates…', 'Reading course maps…']} />
          </div>
        </section>
      )}
      {bucketError && <p className="px-1 text-[0.7059rem] text-(--text-muted)">Bucket list: {bucketError}</p>}
      {empty && feed.has_interests && !bucketBusy && (
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          <p className="text-[0.9412rem] font-medium text-(--text)">No picks yet</p>
          <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-muted)">
            Try more race types, a longer trip, or browse everything in Search.
          </p>
          <div className="flex gap-2">
            <Button variant="default" className="h-10 text-[0.7647rem]" onClick={onEdit}>Edit interests</Button>
            <Button variant="default" className="h-10 text-[0.7647rem]" onClick={onSearch}>Search races</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function SectionTitle({ s }: { s: ForYouSection }) {
  const icon = s.id === 'friends' ? <Users className="size-3.5" /> : s.id === 'bucket' || s.id === 'picks' ? <Sparkles className="size-3.5" /> : null
  return (
    <h3 className={cn('flex items-center gap-1.5 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest',
      s.id === 'picks' ? 'text-(--accent)' : 'text-(--text-muted)')}>
      {icon}{s.title}
    </h3>
  )
}

function Section({ s, onOpen }: { s: ForYouSection; onOpen: (r: ForYouRace) => void }) {
  return (
    <section className="flex flex-col gap-2">
      <SectionTitle s={s} />
      {s.note && <p className="px-1 text-[0.7059rem] leading-snug text-(--warning-text)">{s.note}</p>}
      <div className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1">
        {s.races.map((r) => <PickCard key={r.id} r={r} onClick={() => onOpen(r)} />)}
      </div>
      {s.source === 'web' && <p className="px-1 text-[0.6471rem] text-(--text-muted)">Found online by Rabbit. Check dates on the official site.</p>}
    </section>
  )
}

function PickCard({ r, onClick }: { r: ForYouRace; onClick: () => void }) {
  const [logoOk, setLogoOk] = useState(true)
  const Icon = CATEGORY_ICON[r.types[0] ?? 'other'] ?? Activity
  const dists = [...new Set(r.events.map((e) => e.distance_label).filter(Boolean))].slice(0, 3)
  const place = placeOf(r)
  return (
    <button type="button" onClick={onClick}
      className="flex w-[78%] max-w-[300px] shrink-0 snap-start flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5 text-left active:bg-(--bg-inset)">
      <span className="flex items-start gap-2.5">
        {r.logo && logoOk ? (
          <img src={r.logo} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setLogoOk(false)}
            className="size-10 shrink-0 rounded-xl border border-(--border) bg-white object-contain p-0.5" />
        ) : (
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)">
            <Icon className="size-5" />
          </span>
        )}
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="line-clamp-2 text-[0.8824rem] font-medium leading-snug text-(--text)">{r.name}</span>
          <span className="truncate text-[0.7059rem] text-(--text-muted)">{raceDate(r.date)}{place ? ` · ${place}` : ''}</span>
        </span>
      </span>
      {dists.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {dists.map((d) => <span key={d} className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-[0.6471rem] text-(--text-secondary)">{d}</span>)}
        </span>
      )}
      {r.why && <span className="line-clamp-2 text-[0.7647rem] font-medium leading-snug text-(--text)">{r.why}</span>}
      <span className="mt-auto flex flex-wrap items-center gap-1.5 text-[0.6471rem]">
        {r.fit && <span className={cn('rounded-full px-2 py-0.5 font-medium', HINT_CLS[r.fit.tone])}>{r.fit.label}</span>}
        {r.registration_open && <span className="font-semibold uppercase tracking-wider text-(--accent)">Open</span>}
        {r.source === 'web' && <span className="text-(--text-muted)">Found online</span>}
      </span>
    </button>
  )
}
