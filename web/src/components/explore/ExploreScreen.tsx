// Explore races: upcoming races near you from RunSignup, grouped by month, with quick fit
// hints against your main race. "Find more with Rabbit" searches the web for big races that
// aren't on RunSignup. Tap a race for details, "Add to my events", or to ask Rabbit about it.
// "For you" (default) shows personal picks from the athlete's interests (ForYou.tsx), or ones
// inferred from training, then Near you; "Let Rabbit explore" (one tap) is a small card under
// the first row. Search with no filters uses your location, 50 mi, all types; with no location
// it's nationwide and says so. Places and groups live in For you's "Near you" only.
import { EmptyState } from '@/components/ui/EmptyState'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Search } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Chip, Screen, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  CATEGORIES, CATEGORY_LABEL, DISTANCE_CHIPS, MONTHS, RADII, exploreDefaults, feeFrom, findWithRabbit, loadFilters,
  monthLabel, placeOf, raceDate, saveFilters, searchRaces,
  type ExploreCategory, type ExploreFilters, type ExploreRace,
} from '@/lib/explore'
import { CATEGORY_ICON, HINT_CLS } from './icons'
import { RaceDetail } from './RaceDetail'
import { ForYouFeedView, InterestsStrip, useForYou } from './ForYou'
import { InterestsSheet } from './InterestsSheet'
import { EstimateLine } from './Estimate'
import { LocationPrompt } from './LocationPrompt'
import { AreaBar, useAreaChanged } from '@/components/local/AreaBar'
import type { LocationState } from '@/lib/explore2'
import { LetRabbitExplore } from './RabbitExplore'
import { SponsoredCard } from '@/components/community/Partners'
import type { RaceX } from '@/lib/explore2'

type Mode = 'foryou' | 'search'
const MODE_KEY = 'rabbit.explore.mode'
function readMode(): Mode {
  try { return localStorage.getItem(MODE_KEY) === 'search' ? 'search' : 'foryou' } catch { return 'foryou' }
}

const EMPTY: ExploreFilters = { near: '', radius: 50, months: 6, types: [], distance: null, q: '' }
const nearOk = (s: string) => s.trim() === '' || /^\d{5}$/.test(s.trim()) || /^[A-Za-z]{2}$/.test(s.trim())

function restore(): ExploreFilters | null {
  const v = loadFilters()
  if (!v) return null
  return {
    near: typeof v.near === 'string' ? v.near.slice(0, 5) : '',
    radius: typeof v.radius === 'number' && RADII.includes(v.radius) ? v.radius : 50,
    months: typeof v.months === 'number' && MONTHS.includes(v.months) ? v.months : 6,
    types: Array.isArray(v.types) ? v.types.filter((t): t is ExploreCategory => CATEGORIES.includes(t)) : [],
    distance: DISTANCE_CHIPS.some(([d]) => d === v.distance) ? (v.distance ?? null) : null,
    q: typeof v.q === 'string' ? v.q.slice(0, 60) : '',
  }
}

export function ExploreScreen({ onClose, onAsk, onChanged, imperial = true }: {
  /** none when it is the Events tab page (no X) */
  onClose?: () => void
  onAsk: (text: string) => void
  onChanged?: () => void
  imperial?: boolean
}) {
  const [closing, setClosing] = useState(false)
  const [filters, setFilters] = useState<ExploreFilters | null>(restore)
  const [home, setHome] = useState('')
  const [races, setRaces] = useState<ExploreRace[] | null>(null)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [capped, setCapped] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [wide, setWide] = useState<string | null>(null)
  const [web, setWeb] = useState<ExploreRace[] | null>(null)
  const [webBusy, setWebBusy] = useState(false)
  const [webError, setWebError] = useState<string | null>(null)
  const [detail, setDetail] = useState<ExploreRace | null>(null)
  const seq = useRef(0)
  const [mode, setModeState] = useState<Mode>(readMode)
  const setMode = (m: Mode) => { setModeState(m); try { localStorage.setItem(MODE_KEY, m) } catch { /* private mode */ } }
  const fy = useForYou(mode === 'foryou')
  const [editing, setEditing] = useState(false)

  // Defaults (your resolved location, 50 mi, all types) fill in the filters the first time.
  const loadDefaults = useCallback(() => {
    exploreDefaults().then((d) => {
      setHome(d.near)
      setFilters((f) => f ? (f.near ? f : { ...f, near: d.near }) : { ...EMPTY, near: d.near, types: d.types, radius: d.radius, months: d.months })
    }, () => setFilters((f) => f ?? EMPTY))
  }, [])
  useEffect(() => { loadDefaults() }, [loadDefaults])
  // My area changed (AreaBar): search from there, at least as wide as my radius.
  useAreaChanged(useCallback((st: LocationState) => {
    const near = st.saved?.zip || st.resolved.zip || (st.resolved.state?.length === 2 ? st.resolved.state : '')
    const want = st.radius_mi ?? 10
    const radius = RADII.find((r) => r >= want) ?? RADII[RADII.length - 1]!
    setHome(near)
    setFilters((f) => ({ ...(f ?? EMPTY), ...(near ? { near } : {}), radius }))
  }, []))

  const run = useCallback((f: ExploreFilters, p: number) => {
    const n = ++seq.current
    if (p === 1) { setLoading(true); setWeb(null); setWebError(null) } else setLoadingMore(true)
    setError(null)
    searchRaces(f, p).then((r) => {
      if (n !== seq.current) return
      setRaces((prev) => (p === 1 || !prev ? r.races : [...prev, ...r.races.filter((x) => !prev.some((y) => y.id === x.id))]))
      setPage(r.page); setHasMore(r.has_more); setCapped(r.capped); setWide(r.nationwide ? r.note ?? '' : null)
    }, (e) => { if (n === seq.current) setError((e as Error).message) })
      .finally(() => { if (n === seq.current) { setLoading(false); setLoadingMore(false) } })
  }, [])

  // Search when the filters change (typing is debounced; a half-typed zip waits).
  useEffect(() => {
    if (!filters) return
    saveFilters(filters)
    if (mode !== 'search' || !nearOk(filters.near)) return
    const t = setTimeout(() => run(filters, 1), 350)
    return () => clearTimeout(t)
  }, [filters, run, mode])

  const set = (p: Partial<ExploreFilters>) => setFilters((f) => ({ ...(f ?? EMPTY), ...p }))
  const close = onClose && (() => { setClosing(true); setTimeout(onClose, 200) })

  async function askWeb() {
    if (!filters) return
    setWebBusy(true); setWebError(null)
    try { setWeb((await findWithRabbit(filters)).races) }
    catch (e) { setWebError((e as Error).message) }
    finally { setWebBusy(false) }
  }

  const f = filters ?? EMPTY
  const zip = /^\d{5}$/.test(f.near.trim())
  const groups: { month: string; races: ExploreRace[] }[] = []
  for (const r of races ?? []) {
    const m = monthLabel(r.date)
    const g = groups[groups.length - 1]
    if (g && g.month === m) g.races.push(r)
    else groups.push({ month: m, races: [r] })
  }

  const modes = (
    <div role="tablist" aria-label="Explore view" className="mx-auto mt-1.5 flex w-full max-w-xl gap-4 px-1">
      {([['foryou', 'For you'], ['search', 'Search']] as const).map(([m, l]) => (
        <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
          className={cn('min-h-11 border-b-2 text-[0.8235rem] font-medium transition-colors',
            mode === m ? 'border-(--accent) text-(--text)' : 'border-transparent text-(--text-muted)')}>{l}</button>
      ))}
    </div>
  )

  const bar = (
    <div className="mx-auto mt-2.5 flex w-full max-w-xl flex-col gap-2">
      <div className="flex gap-2">
        <input className={cn(inputCls, 'h-9 min-w-0 flex-1 text-[0.8235rem]')} value={f.near} maxLength={5}
          inputMode="text" autoComplete="postal-code" aria-label="Zip code or state" placeholder="Zip or state (e.g. 80204, CO)"
          onChange={(e) => set({ near: e.target.value.replace(/[^0-9A-Za-z]/g, '').slice(0, 5) })} />
        <select aria-label="Radius" disabled={!zip} value={f.radius}
          className="h-9 shrink-0 rounded-md border border-input bg-transparent px-2 text-[0.8235rem] text-(--text) disabled:opacity-45"
          onChange={(e) => set({ radius: Number(e.target.value) })}>
          {RADII.map((r) => <option key={r} value={r}>{r} mi</option>)}
        </select>
      </div>
      <div className="no-scrollbar -mx-3 -my-1 flex gap-1.5 overflow-x-auto px-3 py-1">
        {home && f.near !== home && <Chip onClick={() => set({ near: home })}><span className="whitespace-nowrap">Use my home</span></Chip>}
        {MONTHS.map((m) => (
          <Chip key={m} selected={f.months === m} onClick={() => set({ months: m })}><span className="whitespace-nowrap">{m === 12 ? '1 year' : `${m} mo`}</span></Chip>
        ))}
        <span className="mx-0.5 w-px shrink-0 self-stretch bg-(--border)" aria-hidden />
        {CATEGORIES.map((c) => {
          const Icon = CATEGORY_ICON[c]
          const on = f.types.includes(c)
          return (
            <Chip key={c} selected={on} onClick={() => set({ types: on ? f.types.filter((x) => x !== c) : [...f.types, c] })}>
              <span className="inline-flex items-center gap-1 whitespace-nowrap"><Icon className="size-3.5" />{CATEGORY_LABEL[c]}</span>
            </Chip>
          )
        })}
      </div>
      <div className="no-scrollbar -mx-3 -my-1 flex gap-1.5 overflow-x-auto px-3 py-1">
        <Chip selected={!f.distance} onClick={() => set({ distance: null })}><span className="whitespace-nowrap">Any distance</span></Chip>
        {DISTANCE_CHIPS.map(([d, label]) => (
          <Chip key={d} selected={f.distance === d} onClick={() => set({ distance: f.distance === d ? null : d })}>
            <span className="whitespace-nowrap">{label}</span>
          </Chip>
        ))}
      </div>
    </div>
  )

  const askCta = (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-(--border) px-4 py-4 text-center">
      <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
        Not seeing your race? Big ones like Ironman or Leadville aren't listed here.
      </p>
      <Button variant="default" className="h-9 gap-1.5 text-[0.7647rem]" loading={webBusy} onClick={() => void askWeb()}>
        <RabbitLogo size={16} current /> Ask Rabbit to search the web
      </Button>
      {webError && <p className="text-[0.7059rem] text-(--danger)" role="alert">{webError}</p>}
    </div>
  )

  return (
    <>
      <Screen title="Explore events" subtitle="Find your next start line" closing={closing} onClose={close}
        headerExtra={<>{modes}{mode === 'search' ? bar : fy.feed && <InterestsStrip interests={fy.feed.interests} onEdit={() => setEditing(true)} />}</>}>
        <AreaBar imperial={imperial} what="races, group runs and meetups" />
        {/* One disclosed sponsored partner when this area (or the zip searched below) is a partner's. */}
        {mode === 'foryou' ? <SponsoredCard placement="discover" /> : <SponsoredCard placement="explore" zip={zip ? f.near.trim() : undefined} />}
        {mode === 'foryou' ? (
          <ForYouFeedView state={fy} onOpen={setDetail} onEdit={() => setEditing(true)} onSearch={() => setMode('search')}
            onAsk={onAsk} imperial={imperial}
            explore={<LetRabbitExplore onOpen={(r) => setDetail(r)} onAsk={onAsk} imperial={imperial} />} />
        ) : <>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-(--text-muted)" />
          <input className={cn(inputCls, 'pl-9')} value={f.q} maxLength={60} placeholder="Search by race name"
            aria-label="Search by race name" onChange={(e) => set({ q: e.target.value })} />
        </div>
        {!nearOk(f.near) && <p className="px-1 text-[0.7059rem] text-(--text-muted)">Enter a 5-digit zip code or a two-letter state.</p>}
        {wide !== null && !f.near.trim() && (
          <LocationPrompt title={wide || 'Upcoming races across the US'} onChanged={() => {
            exploreDefaults().then((d) => { setHome(d.near); if (d.near) set({ near: d.near }) }, () => {})
            fy.load(true)
          }} />
        )}
        {(loading || filters === null) && races === null ? (
          <div className="flex justify-center py-16">
            <RabbitLoader label="Finding races" cycle={['Scouting start lines…', 'Checking the calendar…', 'Reading course maps…']} />
          </div>
        ) : error ? (
          <ErrorState message={`Couldn't load races: ${error}`} onRetry={() => filters && run(filters, 1)} />
        ) : races && races.length === 0 && !loading ? (
          <EmptyState title="No races match yet"
            body="Try a wider radius, a longer window or fewer filters. Or let Rabbit look around the web for you."
            action={web ? undefined : 'Ask Rabbit to search the web'} onAction={() => void askWeb()} />
        ) : (
          <div className={cn('flex flex-col gap-5 transition-opacity', loading && 'opacity-50')} aria-busy={loading}>
            {capped && <p className="px-1 text-[0.7059rem] text-(--text-muted)">Showing the first few kinds you picked. Pick fewer for a complete list.</p>}
            {groups.map((g) => (
              <section key={g.month} className="flex flex-col gap-2">
                <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{g.month}</h2>
                {g.races.map((r) => <RaceCard key={r.id} r={r} onClick={() => setDetail(r)} />)}
              </section>
            ))}
            {hasMore && (
              <Button variant="default" className="h-10 text-[0.7647rem]" loading={loadingMore}
                onClick={() => filters && run(filters, page + 1)}>Load more</Button>
            )}
          </div>
        )}
        {web && (
          <section className="flex flex-col gap-2">
            <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">Found on the web by Rabbit</h2>
            {web.length === 0 ? (
              <p className="px-1 text-[0.7647rem] text-(--text-muted)">Rabbit didn't find anything else that fits. Try different filters.</p>
            ) : web.map((r) => <RaceCard key={r.id} r={r} onClick={() => setDetail(r)} />)}
            {web.length > 0 && <p className="px-1 text-[0.6471rem] text-(--text-muted)">Found online. Check dates and details on the official site.</p>}
          </section>
        )}
        {filters !== null && askCta}
        </>}
      </Screen>
      {detail && (
        <RaceDetail race={detail} imperial={imperial} onClose={() => setDetail(null)} onAsk={onAsk} onAdded={onChanged} />
      )}
      {editing && (
        <InterestsSheet initial={fy.feed?.interests} onClose={() => setEditing(false)} onSaved={fy.saved} />
      )}
    </>
  )
}

function RaceCard({ r, onClick }: { r: ExploreRace; onClick: () => void }) {
  const [logoOk, setLogoOk] = useState(true)
  const Icon = CATEGORY_ICON[r.types[0] ?? 'other'] ?? Activity
  const fee = feeFrom(r)
  const dists = [...new Set(r.events.map((e) => e.distance_label).filter(Boolean))].slice(0, 4)
  const more = new Set(r.events.map((e) => e.distance_label).filter(Boolean)).size - dists.length
  const hint = r.hints?.[0]
  return (
    <button type="button" onClick={onClick}
      className="flex w-full items-start gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
      {r.logo && logoOk ? (
        <img src={r.logo} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setLogoOk(false)}
          className="size-11 shrink-0 rounded-xl border border-(--border) bg-white object-contain p-0.5" />
      ) : (
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)">
          <Icon className="size-5" />
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="line-clamp-2 text-[0.9412rem] font-medium leading-snug text-(--text)">{r.name}</span>
        <span className="truncate text-[0.7059rem] text-(--text-muted)">
          {r.ongoing ? `Ongoing${r.end_date ? ` · through ${raceDate(r.end_date)}` : ''}` : raceDate(r.date)}{placeOf(r) ? ` · ${placeOf(r)}` : ''}
        </span>
        {(dists.length > 0 || r.registration_open || fee || hint) && (
          <span className="flex flex-wrap items-center gap-1">
            {dists.map((d) => (
              <span key={d} className="rounded-full bg-(--bg-elevated) px-2 py-0.5 text-[0.6471rem] text-(--text-secondary)">{d}</span>
            ))}
            {more > 0 && <span className="text-[0.6471rem] text-(--text-muted)">+{more}</span>}
            {hint && <span className={cn('rounded-full px-2 py-0.5 text-[0.6471rem] font-medium', HINT_CLS[hint.tone])}>{hint.label}</span>}
          </span>
        )}
        {(r as RaceX).estimate && <EstimateLine e={(r as RaceX).estimate!} />}
        {(r.registration_open || fee) && (
          <span className="flex items-center gap-2 text-[0.6471rem]">
            {r.registration_open && <span className="font-semibold uppercase tracking-wider text-(--accent)">Registration open</span>}
            {fee && <span className="text-(--text-muted)">from {fee}</span>}
          </span>
        )}
      </span>
    </button>
  )
}
