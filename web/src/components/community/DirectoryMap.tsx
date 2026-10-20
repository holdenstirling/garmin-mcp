// "Clubs & leagues near you" -> Map: a real street map (components/local/SlippyMap, OSM tiles)
// with a pin per group at its public meet spot, colored by activity. Tap a pin for its card;
// after panning, "Search this area" narrows the list under the map to what's in view. The list
// of mapped groups stays below as real buttons: the accessible way to pick one.
import { useMemo, useState } from 'react'
import { ExternalLink, Search } from 'lucide-react'
import { ACTIVITY_ICON } from '@/components/local/ActivityIcon'
import { SlippyMap, type Bounds, type MapPin } from '@/components/local/SlippyMap'
import { cn } from '@/lib/utils'
import { nextLabel, osmLink, type DirListing } from '@/lib/clubdir'
import type { ActivityId } from '@/lib/activity'

const TONE: Record<ActivityId, string> = {
  run: 'run', trail: 'outdoor', ride: 'ride', swim: 'swim', tri: 'water', volleyball: 'other', pickleball: 'other',
  soccer: 'other', basketball: 'other', climbing: 'outdoor', yoga: 'strength', other: 'other',
}

const inside = (b: Bounds, lat: number, lon: number) => lat <= b.north && lat >= b.south && lon >= b.west && lon <= b.east

export function DirectoryMap({ listings, center, metroLabel, renderCard }: {
  listings: DirListing[]; center?: { lat: number; lon: number } | null; metroLabel: string
  renderCard: (l: DirListing) => React.ReactNode
}) {
  const mapped = useMemo(() => listings.filter((l) => typeof l.lat === 'number' && typeof l.lon === 'number'), [listings])
  const [sel, setSel] = useState<string | null>(null)
  const [moved, setMoved] = useState<Bounds | null>(null)
  const [area, setArea] = useState<Bounds | null>(null)
  const picked = mapped.find((l) => l.id === sel) ?? null
  const unmapped = listings.length - mapped.length
  const shown = area ? mapped.filter((l) => inside(area, l.lat as number, l.lon as number)) : mapped

  const pins: MapPin[] = useMemo(() => mapped.map((l) => {
    const act = (l.activity ?? 'other') as ActivityId
    const Icon = ACTIVITY_ICON[act]
    const tone = TONE[act] ?? 'other'
    return {
      id: l.id, lat: l.lat as number, lon: l.lon as number,
      label: `${l.name}${l.meet_spot ? `, meets at ${l.meet_spot}` : ''}`,
      icon: <Icon className="size-[18px]" strokeWidth={2.25} aria-hidden />,
      fg: `var(--sport-${tone}-bg)`, bg: `var(--sport-${tone})`,
    }
  }), [mapped])

  if (!mapped.length) {
    return <p className="px-1 text-meta text-(--text-muted)">No meet spots on the map yet. The list has every group.</p>
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="relative">
        <SlippyMap pins={pins} center={center} selected={sel} onSelect={setSel} onMoved={setMoved} />
        {moved && (
          <button type="button" onClick={() => { setArea(moved); setMoved(null) }}
            className="absolute left-1/2 top-3 inline-flex min-h-11 -translate-x-1/2 items-center gap-2 rounded-full bg-(--bg-surface) px-4 text-small font-semibold text-(--text) shadow-md">
            <Search className="size-4" aria-hidden /> Search this area
          </button>
        )}
      </div>
      <p className="sr-only">Map of {mapped.length} meet spots around {metroLabel}. The list below has the same groups.</p>
      {picked && (
        <div className="flex flex-col gap-2" aria-live="polite">
          {renderCard(picked)}
          <a href={osmLink(picked.lat as number, picked.lon as number)} target="_blank" rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-1.5 self-start text-meta text-(--text-secondary)">
            Open in OpenStreetMap <ExternalLink className="size-4" aria-hidden />
          </a>
        </div>
      )}
      <div className="flex items-center justify-between gap-2 px-1">
        <p className="m-0 text-small text-(--text-secondary)">
          {area ? `${shown.length} in this area` : `${mapped.length} on the map`}
        </p>
        {area && (
          <button type="button" onClick={() => setArea(null)} className="min-h-11 px-2 text-small font-semibold text-(--accent)">Show all</button>
        )}
      </div>
      <ul className="flex flex-col gap-2" aria-label="Groups on the map">
        {shown.map((l) => {
          const I = ACTIVITY_ICON[l.activity ?? 'other']
          const when = nextLabel(l.next)
          return (
            <li key={l.id}>
              <button type="button" aria-pressed={l.id === sel} onClick={() => setSel(l.id === sel ? null : l.id)}
                className={cn('flex min-h-14 w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left',
                  l.id === sel ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
                <I className="size-5 shrink-0 text-(--accent)" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-body leading-snug text-(--text)">{l.name}</span>
                  {when && <span className="block text-meta text-(--text-muted)">{when}</span>}
                  {l.meet_spot && <span className="block text-meta text-(--text-muted)">{l.meet_spot}</span>}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {unmapped > 0 && (
        <p className="px-1 text-caption text-(--text-muted)">
          {unmapped} more {unmapped === 1 ? 'group has' : 'groups have'} no mapped meet spot. They're in the list.
        </p>
      )}
      <p className="px-1 text-caption text-(--text-muted)">Meet spots are approximate.</p>
    </div>
  )
}
