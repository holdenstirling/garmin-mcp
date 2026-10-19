// Explore "Near you": places to play within ~5 miles (OpenStreetMap: courts, tracks, pools,
// climbing, bike parks, trailheads, fitness stations) and group activities from the web
// (rec leagues, group runs and rides, pickup volleyball, open swims; "From the web — check
// details"). Every card: kind icon, distance or schedule, Open map / Website, Ask Rabbit.
// NearYouSection (For you) never spends a web search; LocalActivities (the "Local" chip in
// Search) runs the weekly per-city group search when it isn't cached yet.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Bike, CircleDot, Dumbbell, ExternalLink, Flower2, Footprints, Map as MapIcon, MapPin, MessageCircle,
  Mountain, Signpost, Users, Volleyball, Waves,
} from 'lucide-react'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Chip } from '@/components/plan/ui'
import { fmtDist } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  getLocal, getNearby, type LocalActivity, type LocalCategory, type LocalResult, type Place, type PlaceKind,
} from '@/lib/explore2'
import { LocationPrompt } from './LocationPrompt'

const GROUP_ICON: Record<LocalCategory, typeof Bike> = {
  run: Footprints, ride: Bike, swim: Waves, social_sports: Volleyball, yoga: Flower2, climb: Mountain, other: Users,
}
const PLACE_ICON: Record<PlaceKind, typeof Bike> = {
  volleyball: Volleyball, track: Footprints, pool: Waves, climbing: Mountain, bike_park: Bike, trailhead: Signpost,
  fitness: Dumbbell, pickleball: CircleDot, tennis: CircleDot,
}
const GROUP_ORDER: LocalCategory[] = ['run', 'ride', 'swim', 'social_sports', 'yoga', 'climb']
const LOOKING = ['Asking around the park…', 'Finding the Tuesday run club…', 'Checking group ride routes…', 'Hopping between rec leagues…']
export const WEB_NOTE = 'From the web — check details before you go.'

export function placeAsk(p: Place, imperial: boolean): string {
  const what = p.named ? `${p.name} (${p.kind_label.toLowerCase()})` : `a ${p.kind_label.toLowerCase()}`
  return `There's ${what} ${fmtDist(p.distance_km, imperial)} from me. Would a session there fit my plan this week?`
}
export function groupAsk(a: LocalActivity): string {
  const when = a.schedule || a.when
  return `Would "${a.name}"${when ? ` (${when})` : ''} fit my plan?`
}

const linkCls = 'inline-flex min-h-11 items-center gap-1.5 text-small font-medium'
const cardCls = 'flex w-[78%] max-w-[300px] shrink-0 snap-start flex-col gap-2 rounded-2xl border border-(--border) bg-(--bg-surface) p-3.5'

export function PlaceCard({ p, imperial, onAsk, className, style }: {
  p: Place; imperial: boolean; onAsk: (text: string) => void; className?: string; style?: React.CSSProperties
}) {
  const Icon = PLACE_ICON[p.kind] ?? MapPin
  const extra = [p.tags.lit === 'yes' ? 'Lit at night' : '', p.tags.surface ? p.tags.surface.replace(/_/g, ' ') : '']
    .filter(Boolean).join(' · ')
  return (
    <article className={cn(cardCls, className)} style={style}>
      <div className="flex items-start gap-2.5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)"><Icon className="size-6" /></span>
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-body-lg font-medium leading-snug text-(--text)">{p.name}</p>
          <p className="truncate text-meta text-(--text-muted)">
            {p.named ? `${p.kind_label} · ` : ''}{fmtDist(p.distance_km, imperial)} away
          </p>
        </div>
      </div>
      {extra && <p className="text-meta leading-snug text-(--text-secondary)">{extra}</p>}
      <div className="mt-auto flex flex-col">
        <a href={p.osm_url} target="_blank" rel="noopener noreferrer" className={cn(linkCls, 'text-(--accent)')}>
          <MapIcon className="size-4" /> Open map
        </a>
        <button type="button" className={cn(linkCls, 'text-left text-(--text-secondary)')} onClick={() => onAsk(placeAsk(p, imperial))}>
          <MessageCircle className="size-4" /> Ask rabbt
        </button>
      </div>
    </article>
  )
}

export function GroupCard({ a, onAsk, className, style }: {
  a: LocalActivity; onAsk: (text: string) => void; className?: string; style?: React.CSSProperties
}) {
  const Icon = GROUP_ICON[a.kind ?? a.category] ?? Users
  const when = a.schedule || a.when
  const meta = [a.area || a.where, a.cost && (a.cost === 'free' ? 'Free' : a.cost)].filter(Boolean).join(' · ')
  return (
    <article className={cn(cardCls, className)} style={style}>
      <div className="flex items-start gap-2.5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)"><Icon className="size-6" /></span>
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-body-lg font-medium leading-snug text-(--text)">{a.name}</p>
          {a.organizer && a.organizer !== a.name && <p className="truncate text-meta text-(--text-muted)">{a.organizer}</p>}
        </div>
      </div>
      {when && <p className="text-small font-medium leading-snug text-(--text)">{when}</p>}
      {meta && <p className="text-meta leading-snug text-(--text-secondary)">{meta}</p>}
      <span className="w-fit rounded-full bg-(--bg-elevated) px-2 py-0.5 text-caption text-(--text-secondary)">From the web</span>
      <div className="mt-auto flex flex-col">
        <a href={a.url} target="_blank" rel="noopener noreferrer" className={cn(linkCls, 'text-(--accent)')}>
          Website <ExternalLink className="size-4" />
        </a>
        <button type="button" className={cn(linkCls, 'text-left text-(--text-secondary)')} onClick={() => onAsk(groupAsk(a))}>
          <MessageCircle className="size-4" /> Ask rabbt
        </button>
      </div>
    </article>
  )
}

export function CardRow({ children }: { children: React.ReactNode }) {
  return <div className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1">{children}</div>
}

function Title({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="flex items-center gap-1.5 px-1 text-caption font-semibold text-(--text-muted)">
      <MapPin className="size-4" />{children}
    </h2>
  )
}

/** For you: "Near you" (no web search; renders nothing when local picks are off or empty). */
export function NearYouSection({ imperial, onAsk, reloadKey = 0 }: { imperial: boolean; onAsk: (text: string) => void; reloadKey?: number }) {
  const [res, setRes] = useState<LocalResult | null>(null)
  useEffect(() => {
    let live = true
    getNearby().then((r) => { if (live) setRes(r) }, () => { if (live) setRes(null) })
    return () => { live = false }
  }, [reloadKey])
  if (!res || res.disabled || (!res.places.length && !res.items.length)) return null
  const where = [res.city, res.state].filter(Boolean).join(', ')
  return (
    <section className="flex flex-col gap-2">
      <Title>Near you{where ? ` · ${where}` : ''}</Title>
      <CardRow>
        {res.items.slice(0, 4).map((a) => <GroupCard key={a.id} a={a} onAsk={onAsk} />)}
        {res.places.slice(0, 8).map((p) => <PlaceCard key={p.id} p={p} imperial={imperial} onAsk={onAsk} />)}
      </CardRow>
      <p className="px-1 text-caption text-(--text-muted)">
        Places from OpenStreetMap.{res.items.length ? ` Groups: ${WEB_NOTE.toLowerCase()}` : ''}
      </p>
    </section>
  )
}

/** Search -> "Local" chip: places and groups near you, filterable by kind. */
export function LocalActivities({ onAsk, imperial = true, onLocationChanged }: {
  onAsk: (text: string) => void
  imperial?: boolean
  onLocationChanged?: () => void
}) {
  const [res, setRes] = useState<LocalResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [only, setOnly] = useState<LocalCategory | 'places' | null>(null)
  const seq = useRef(0)

  const load = useCallback(() => {
    const n = ++seq.current
    setBusy(true); setError(null)
    getLocal().then((r) => { if (n === seq.current) setRes(r) }, (e) => { if (n === seq.current) setError((e as Error).message) })
      .finally(() => { if (n === seq.current) setBusy(false) })
  }, [])
  useEffect(() => { load() }, [load])

  const chips = useMemo(() => {
    if (!res) return []
    const present = new Set(res.items.map((a) => a.kind ?? a.category))
    const first = res.suggested.filter((c) => present.has(c))
    return [...first, ...GROUP_ORDER.filter((c) => present.has(c) && !first.includes(c))]
  }, [res])

  if (busy && !res) return <div className="flex justify-center py-14"><RabbitLoader label="Finding things to do near you" cycle={LOOKING} /></div>
  if (error && !res) return <ErrorState message={`Couldn't load things near you: ${error}`} onRetry={load} />
  if (!res) return null
  if (res.disabled) {
    return (
      <p className="rounded-xl bg-(--bg-elevated) px-3.5 py-3 text-small leading-snug text-(--text-secondary)">
        Local picks are off. Turn on "Use my location for local picks" in Settings to see places and groups near you.
      </p>
    )
  }
  if (res.needs_location) {
    return <LocationPrompt title="Where are you? rabbt will find courts, tracks, clubs and groups nearby" onChanged={() => { load(); onLocationChanged?.() }} />
  }
  const groups = only === 'places' ? [] : res.items.filter((a) => !only || (a.kind ?? a.category) === only)
  const places = only && only !== 'places' ? [] : res.places
  const where = [res.city, res.state].filter(Boolean).join(', ')
  const showChips = chips.length + (res.places.length ? 1 : 0) > 1
  return (
    <section className="flex flex-col gap-4">
      {where && (
        <p className="px-1 text-small leading-snug text-(--text-secondary)">
          Things to do around <span className="font-medium text-(--text)">{where}</span>.
        </p>
      )}
      {showChips && (
        <div className="no-scrollbar -mx-3 -my-1 flex gap-1.5 overflow-x-auto px-3 py-1">
          <Chip selected={!only} onClick={() => setOnly(null)}><span className="whitespace-nowrap">All</span></Chip>
          {res.places.length > 0 && (
            <Chip selected={only === 'places'} onClick={() => setOnly(only === 'places' ? null : 'places')}>
              <span className="inline-flex items-center gap-1 whitespace-nowrap"><MapPin className="size-4" />Places</span>
            </Chip>
          )}
          {chips.map((c) => {
            const Icon = GROUP_ICON[c]
            return (
              <Chip key={c} selected={only === c} onClick={() => setOnly(only === c ? null : c)}>
                <span className="inline-flex items-center gap-1 whitespace-nowrap"><Icon className="size-4" />{res.chips[c] ?? c}</span>
              </Chip>
            )
          })}
        </div>
      )}
      {groups.length > 0 && (
        <div className="flex flex-col gap-2">
          <Title>Groups and leagues</Title>
          <CardRow>{groups.map((a) => <GroupCard key={a.id} a={a} onAsk={onAsk} />)}</CardRow>
          <p className="px-1 text-caption text-(--text-muted)">{WEB_NOTE}</p>
        </div>
      )}
      {res.groups_state === 'limit' && res.items.length === 0 && (
        <p className="px-1 text-meta text-(--text-muted)">Today's rabbt web searches are used up. Groups and leagues show up tomorrow.</p>
      )}
      {places.length > 0 && (
        <div className="flex flex-col gap-2">
          <Title>Places to play</Title>
          <CardRow>{places.map((p) => <PlaceCard key={p.id} p={p} imperial={imperial} onAsk={onAsk} />)}</CardRow>
          <p className="px-1 text-caption text-(--text-muted)">From OpenStreetMap. Check access and hours before you go.</p>
        </div>
      )}
      {res.places_state === 'busy' && (
        <p className="px-1 text-meta text-(--text-muted)">Lots of people are looking right now. Try again in a few seconds for places.</p>
      )}
      {res.places_state === 'failed' && (
        <p className="px-1 text-meta text-(--text-muted)">The map service isn't answering, so places are missing for now.</p>
      )}
      {groups.length === 0 && places.length === 0 && res.groups_state !== 'limit' && (
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          <RabbitLoader decorative gentle size={44} />
          <p className="max-w-xs text-small leading-snug text-(--text-muted)">rabbt didn't find anything nearby this week. Check back next week.</p>
        </div>
      )}
    </section>
  )
}
