// The Feed's Map view: every workout in the feed that has a route, drawn on one map, one color per
// person, with a pin at each start. Tap a pin (or a name in the list) to bring that route forward
// and see a small card; "Open" opens the workout exactly like its feed card does. Workouts with no
// map (indoor, Apple Watch, Oura, or a friend who keeps maps private) are listed under the map.
// Friends' lines only arrive when they share maps (community.route_shown); the server marks the
// rest ``map_private`` so the list can say so instead of leaving a mystery gap.
import { useMemo, useState } from 'react'
import { ChevronRight, EyeOff, MapPinOff } from 'lucide-react'
import { SlippyMap, type MapPath, type MapPin } from '@/components/local/SlippyMap'
import { EmptyRabbit } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { SportTile } from '@/components/ui/SportTile'
import { FAMILY_NAME, famDist, sportFamily } from '@/lib/sportstats'
import type { Post, PostWorkout } from '@/lib/community'
import { cn } from '@/lib/utils'

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-7)', 'var(--chart-5)',
  'var(--chart-4)', 'var(--chart-8)', 'var(--chart-6)']
const famOf = (w: PostWorkout) => sportFamily(w.family || w.sport, w.family ? null : w.kind)
const SOURCE: Record<string, string> = { apple: 'Apple Watch', oura: 'Oura', whoop: 'WHOOP', coros: 'COROS', strava: 'Strava' }

function dayLabel(d: string): string {
  const day = new Date(`${d.slice(0, 10)}T12:00:00`)
  const today = new Date(); today.setHours(12, 0, 0, 0)
  const diff = Math.round((today.getTime() - day.getTime()) / 86_400_000)
  if (diff === 0) return 'today'
  if (diff === 1) return 'yesterday'
  return day.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

function line(p: Post, imperial: boolean): string {
  const w = p.workout!
  const fam = famOf(w)
  const bits = [FAMILY_NAME[fam]]
  if (w.km) bits.push(famDist(w.km, fam, imperial))
  if (w.date) bits.push(dayLabel(w.date))
  return bits.join(' · ')
}

/** Why a workout has no line on the map, in plain words. */
function noMapWhy(p: Post): string {
  const w = p.workout!
  if (p.mine && w.route_hidden) return 'Your maps are off (Sharing settings)'
  if (w.map_private) return `${p.user?.name?.split(' ')[0] ?? 'They'} keeps their map private`
  const src = SOURCE[String(w.source ?? '').toLowerCase()]
  return src ? `From ${src}: no GPS line` : 'Indoors or no GPS'
}

export function FeedMap({ items, imperial, onOpen }: {
  items: Post[]; imperial: boolean
  /** open a workout the same way its feed card does */
  onOpen: (p: Post) => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const workouts = useMemo(() => items.filter((p) => p.workout), [items])
  const mapped = useMemo(() => workouts.filter((p) => (p.workout!.route?.length ?? 0) >= 2), [workouts])
  const unmapped = useMemo(() => workouts.filter((p) => (p.workout!.route?.length ?? 0) < 2), [workouts])

  // one color per person, in the order they first appear (newest first)
  const colorOf = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of mapped) if (!m.has(p.author)) m.set(p.author, COLORS[m.size % COLORS.length]!)
    return m
  }, [mapped])

  const paths: MapPath[] = useMemo(() => mapped.map((p) => ({ id: p.id, line: p.workout!.route!, color: colorOf.get(p.author)! })), [mapped, colorOf])
  const pins: MapPin[] = useMemo(() => mapped.map((p) => {
    const [lat, lon] = p.workout!.route![0]!
    const who = p.mine ? 'You' : p.user?.name ?? 'Friend'
    return {
      id: p.id, lat, lon, label: `${who}: ${line(p, imperial)}`,
      icon: <span className="text-small font-bold leading-none">{(p.mine ? 'Me' : who).charAt(0).toUpperCase()}</span>,
      fg: 'var(--on-fill)', bg: colorOf.get(p.author)!,
    }
  }), [mapped, colorOf, imperial])
  const sel = mapped.find((p) => p.id === selected) ?? null

  if (workouts.length === 0) {
    return (
      <EmptyRabbit hero size={60} mode="peek" className="rounded-2xl border border-(--border) bg-(--bg-surface) px-5 py-6"
        title="No routes yet"
        body="When you or a friend finish a run or ride outside, the line lands here. Go draw the first one." />
    )
  }

  return (
    <section aria-label="Map of workouts in your feed" className="flex flex-col gap-3">
      {mapped.length > 0 ? (
        <div className="relative">
          <SlippyMap pins={pins} paths={paths} selected={selected} onSelect={setSelected} locate={false}
            height={380} label={`Map of ${mapped.length} ${mapped.length === 1 ? 'route' : 'routes'} from your feed`} />
          {sel && (
            <div className="absolute inset-x-2 bottom-7 z-20 flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3 shadow-md">
              <span className="size-3 shrink-0 rounded-full" style={{ background: colorOf.get(sel.author) }} aria-hidden />
              <SportTile sport={sel.workout!.sport} family={famOf(sel.workout!)} size={36} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-body font-semibold text-(--text)">{sel.mine ? 'You' : sel.user?.name ?? 'Friend'}</span>
                <span className="block truncate text-meta text-(--text-muted)">{line(sel, imperial)}</span>
              </span>
              <Button variant="primary" className="h-10 shrink-0 px-3 text-small" onClick={() => onOpen(sel)}>Open</Button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 py-4">
          <MapPinOff className="size-6 shrink-0 text-(--text-muted)" aria-hidden />
          <p className="m-0 text-body text-(--text-secondary)">No map lines in these workouts yet. Outdoor runs and rides with GPS show up here.</p>
        </div>
      )}

      {mapped.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-label="Routes on the map">
          {mapped.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => setSelected(p.id === selected ? null : p.id)} aria-pressed={p.id === selected}
                className={cn('flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2 text-left active:bg-(--bg-inset)',
                  p.id === selected ? 'bg-(--bg-inset)' : 'bg-transparent')}>
                <span className="size-3 shrink-0 rounded-full" style={{ background: colorOf.get(p.author) }} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body font-semibold text-(--text)">{p.mine ? 'You' : p.user?.name ?? 'Friend'}</span>
                  <span className="block truncate text-meta text-(--text-muted)">{line(p, imperial)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {unmapped.length > 0 && (
        <section aria-label="Workouts with no map" className="flex flex-col gap-1">
          <h3 className="section-label m-0 px-1">No map for these</h3>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {unmapped.map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => onOpen(p)}
                  className="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2 text-left active:bg-(--bg-inset)">
                  <SportTile sport={p.workout!.sport} family={famOf(p.workout!)} size={32} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body font-semibold text-(--text)">{p.mine ? 'You' : p.user?.name ?? 'Friend'} · {line(p, imperial)}</span>
                    <span className="flex items-center gap-1 truncate text-meta text-(--text-muted)">
                      {(p.workout!.map_private || p.workout!.route_hidden) && <EyeOff className="size-3.5 shrink-0" aria-hidden />}
                      {noMapWhy(p)}
                    </span>
                  </span>
                  <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  )
}
