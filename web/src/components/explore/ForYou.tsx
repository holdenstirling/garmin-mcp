// Explore "For you": personal race picks in horizontal snap-scroll rows (Picked for you, Tune-ups,
// Coming up near you, Your friends are racing, Bucket list). Every card says why it's here.
// Tap a card for the usual RaceDetail (add to races, ask Rabbit, register).
// Never empty (explore v2): with no interests the server ranks with ones inferred from your
// training, goal or a balanced mix (a dismissible "Based on your training" chip says so); with no
// location it shows races coming up across the US (labelled) and asks for a zip or "Use my
// location" inline. "Near you" (places + groups) follows the races.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Carrot, MountainSnow, Pencil, RefreshCw, Users, X } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { placeOf, raceDate } from '@/lib/explore'
import {
  fetchBucket, getForYou, hasInterests, interestsSummary,
  type ForYouFeed, type ForYouRace, type ForYouSection, type Interests,
} from '@/lib/foryou'
import { MONTH_LONG, saveZipLocation, type RaceX } from '@/lib/explore2'
import { CATEGORY_ICON, HINT_CLS } from './icons'
import { EstimateLine } from './Estimate'
import { LocationPrompt } from './LocationPrompt'
import { useAreaChanged } from '@/components/local/AreaBar'
import { NearYouSection } from './LocalActivities'
import { FeaturedStrip } from '@/components/community/Featured'

const CHIP_KEY = 'rabbit.explore.inferred.dismissed'
const SCOUT = ['Scouting races for you…', 'Sniffing out start lines…', 'Checking your calendar…', 'Lining up tune-ups…']

function chipDismissed(): boolean {
  try { return localStorage.getItem(CHIP_KEY) === '1' } catch { return false }
}

/** Feed state for the For you view (the sheet trigger lives here so the header can share it). */
export function useForYou(active: boolean) {
  const [feed, setFeed] = useState<ForYouFeed | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [bucketBusy, setBucketBusy] = useState(false)
  const [bucketError, setBucketError] = useState<string | null>(null)
  const seq = useRef(0)

  const load = useCallback((fresh = false) => {
    const n = ++seq.current
    setLoading(true); setError(null)
    getForYou(fresh).then((f) => {
      if (n !== seq.current) return
      setFeed(f)
    }, (e) => { if (n === seq.current) setError((e as Error).message) })
      .finally(() => { if (n === seq.current) setLoading(false) })
  }, [])

  useEffect(() => { if (active && !feed && !loading && !error) load() }, [active, feed, loading, error, load])

  // Bucket list: a web search (one of the daily allowance), only when the athlete taps
  // "Find bucket-list races" (never automatically on open). The server reuses a week's result.
  const findBucket = useCallback(() => {
    setBucketBusy(true); setBucketError(null)
    fetchBucket().then(({ section }) => setFeed((f) => f && ({
      ...f, bucket: { ...f.bucket, due: false },
      sections: [...f.sections.filter((s) => s.id !== 'bucket'), ...(section.races.length ? [section] : [])],
    })), (e) => setBucketError((e as Error).message)).finally(() => setBucketBusy(false))
  }, [])

  const saved = (i: Interests) => {
    setFeed((f) => f && { ...f, interests: i, has_interests: hasInterests(i) })
    load()
  }
  /** A zip typed into the inline location ask becomes the saved ("manual") location. */
  const saveZip = async (zip: string) => { await saveZipLocation(zip) }
  return { feed, loading, error, load, saved, saveZip, bucketBusy, bucketError, findBucket }
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

export function ForYouFeedView({ state, onOpen, onEdit, onSearch, onAsk, imperial, explore }: {
  state: ReturnType<typeof useForYou>
  /** "Let Rabbit explore", shown under the first row of picks */
  explore?: React.ReactNode
  onOpen: (r: ForYouRace) => void
  onEdit: () => void
  onSearch: () => void
  onAsk: (text: string) => void
  imperial: boolean
}) {
  const { feed, loading, error, load, saveZip, bucketBusy, bucketError, findBucket } = state
  const [hideChip, setHideChip] = useState(chipDismissed)
  const [locKey, setLocKey] = useState(0)
  const changed = () => { setLocKey((k) => k + 1); load(true) }
  useAreaChanged(useCallback(() => { setLocKey((k) => k + 1); load(true) }, [load])) // eslint-disable-line react-hooks/exhaustive-deps
  if (!feed && (loading || !error)) {
    return <div className="flex justify-center py-16"><RabbitLoader label="Scouting races for you" cycle={SCOUT} /></div>
  }
  if (!feed) return <ErrorState message={`Couldn't load your picks: ${error}`} onRetry={() => load()} />

  const empty = feed.sections.length === 0
  const loc = feed.location
  const dismissChip = () => { setHideChip(true); try { localStorage.setItem(CHIP_KEY, '1') } catch { /* private mode */ } }
  return (
    <div className={cn('flex flex-col gap-6 transition-opacity', loading && 'opacity-50')} aria-busy={loading}>
      {/* First run: no saved location -> "Use my location / zip" is the first card. */}
      {loc && !loc.searchable ? (
        <LocationPrompt title="Add your location for nearby picks" onSaveZip={saveZip} onChanged={changed} />
      ) : null}
      {feed.inferred && !hideChip && (
        <div className="-mb-3 flex items-center gap-1 self-start rounded-full bg-(--accent-subtle) py-0.5 pl-3 text-[0.7059rem] text-(--accent)">
          <Activity className="size-3.5 shrink-0" aria-hidden />
          <button type="button" className="min-h-11 text-left font-medium" onClick={onEdit}>
            Based on your training. <span className="underline underline-offset-2">Tune your interests</span>
          </button>
          <button type="button" className="hit-44 inline-flex size-8 items-center justify-center" aria-label="Dismiss" onClick={dismissChip}>
            <X className="size-3.5" />
          </button>
        </div>
      )}
      {/* Where: Discover's AreaBar above (one place to change it); picks reload when it changes. */}
      {feed.failed && (
        <div className="flex items-center gap-2 rounded-xl bg-(--warning-subtle) px-3 py-2 text-[0.7059rem] text-(--warning-text)" role="status">
          <span className="flex-1">Race search isn't answering right now, so picks are missing. Showing what we have.</span>
          <button type="button" className="hit-44 inline-flex items-center gap-1 font-medium" onClick={() => load(true)}>
            <RefreshCw className="size-3.5" /> Retry
          </button>
        </div>
      )}
      {feed.sections.slice(0, 1).map((s) => <Section key={s.id} s={s} onOpen={onOpen} />)}
      <FeaturedStrip where="explore" />
      {explore}
      {feed.sections.slice(1).map((s) => <Section key={s.id} s={s} onOpen={onOpen} />)}
      {feed.bucket.due && !bucketBusy && (
        <button type="button" onClick={findBucket}
          className="flex min-h-11 items-center gap-3 rounded-xl border border-dashed border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
          <span className="flex shrink-0 text-(--accent)"><RabbitLogo size={16} current /></span>
          <span className="min-w-0 flex-1">
            <span className="block text-[0.7647rem] font-medium text-(--accent)">Find bucket-list races</span>
            <span className="block text-[0.6471rem] text-(--text-muted)">Rabbit searches the web · uses 1 of 5 daily searches</span>
          </span>
        </button>
      )}
      <NearYouSection imperial={imperial} onAsk={onAsk} reloadKey={locKey} />
      {bucketBusy && (
        <section className="flex flex-col gap-2">
          <SectionTitle s={{ id: 'bucket', title: 'Bucket list', races: [], source: 'web' }} />
          <div className="flex justify-center rounded-2xl border border-(--border) py-6">
            <RabbitLoader inline label="Searching the web" cycle={['Looking up legendary races…', 'Checking race dates…', 'Reading course maps…']} />
          </div>
        </section>
      )}
      {bucketError && <p className="px-1 text-[0.7059rem] text-(--text-muted)">Bucket list: {bucketError}</p>}
      {empty && !bucketBusy && (
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
  const icon = s.id === 'friends' ? <Users className="size-3.5" /> : s.id === 'picks' ? <Carrot className="size-3.5" />
    : s.id === 'bucket' || s.id === 'popular' ? <MountainSnow className="size-3.5" /> : null
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
      {s.note && <p className={cn('px-1 text-[0.7059rem] leading-snug', s.id === 'nationwide' ? 'text-(--text-muted)' : 'text-(--warning-text)')}>{s.note}</p>}
      <div className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1">
        {s.races.map((r) => <PickCard key={r.id} r={r} onClick={() => onOpen(r)} />)}
      </div>
      {s.source === 'web' && <p className="px-1 text-[0.6471rem] text-(--text-muted)">Found online by Rabbit. Check dates on the official site.</p>}
      {s.source === 'curated' && <p className="px-1 text-[0.6471rem] text-(--text-muted)">Famous races everyone talks about. Dates move each year, so check the official site.</p>}
    </section>
  )
}

/** "Sat, May 22", "Ongoing · through Dec 31" for a series, or "Usually in April" for a popular
 *  race whose date isn't confirmed. */
export function whenText(r: RaceX): string {
  if (r.check_dates || !r.date) return r.usual_month ? `Usually in ${MONTH_LONG[r.usual_month - 1]}` : 'Date to be announced'
  if (r.ongoing) return r.end_date ? `Ongoing · through ${raceDate(r.end_date)}` : 'Ongoing'
  return raceDate(r.date)
}

export function PickCard({ r, onClick, className, style }: {
  r: ForYouRace | RaceX; onClick: () => void; className?: string; style?: React.CSSProperties
}) {
  const [logoOk, setLogoOk] = useState(true)
  const Icon = CATEGORY_ICON[r.types[0] ?? 'other'] ?? Activity
  const dists = [...new Set(r.events.map((e) => e.distance_label).filter(Boolean))].slice(0, 3)
  const place = placeOf(r)
  return (
    <button type="button" onClick={onClick} style={style}
      className={cn('flex w-[78%] max-w-[300px] shrink-0 snap-start flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5 text-left active:bg-(--bg-inset)', className)}>
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
          <span className="truncate text-[0.7059rem] text-(--text-muted)">{whenText(r)}{place ? ` · ${place}` : ''}</span>
        </span>
      </span>
      {dists.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {dists.map((d) => <span key={d} className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-[0.6471rem] text-(--text-secondary)">{d}</span>)}
        </span>
      )}
      {r.why && <span className="line-clamp-2 text-[0.7647rem] font-medium leading-snug text-(--text)">{r.why}</span>}
      {r.estimate && <EstimateLine e={r.estimate} />}
      <span className="mt-auto flex flex-wrap items-center gap-1.5 text-[0.6471rem]">
        {'fit' in r && r.fit && <span className={cn('rounded-full px-2 py-0.5 font-medium', HINT_CLS[r.fit.tone])}>{r.fit.label}</span>}
        {r.registration_open && <span className="font-semibold uppercase tracking-wider text-(--accent)">Open</span>}
        {r.check_dates && <span className="rounded-full bg-(--warning-subtle) px-2 py-0.5 font-medium text-(--warning-text)">Check dates</span>}
        {r.source === 'web' && <span className="text-(--text-muted)">Found online</span>}
      </span>
    </button>
  )
}
