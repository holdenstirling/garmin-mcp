// "Clubs & leagues near you" -> Map: a light, dependency-free plot of geocoded public meet
// spots around the metro centre (SVG, no tiles, nothing leaves the app), a list of the mapped
// groups as real buttons (the accessible way to pick one), and for the picked group its card
// plus an opt-in OpenStreetMap street map (one iframe, loaded only on tap; CSP frame-src allows
// www.openstreetmap.org). The List view stays the primary view.
import { useMemo, useState } from 'react'
import { ExternalLink, Map as MapIcon, MapPin } from 'lucide-react'
import { cn } from '@/lib/utils'
import { nextLabel, osmEmbedUrl, osmLink, type DirListing } from '@/lib/clubdir'

type Pt = { l: DirListing; x: number; y: number }

const W = 320
const H = 220
const PAD = 22

function project(listings: DirListing[], center: { lat: number; lon: number } | null | undefined): { pts: Pt[]; c: { x: number; y: number } | null } {
  const mapped = listings.filter((l) => typeof l.lat === 'number' && typeof l.lon === 'number')
  const all = [...mapped.map((l) => [l.lat as number, l.lon as number] as const), ...(center ? [[center.lat, center.lon] as const] : [])]
  if (!all.length) return { pts: [], c: null }
  const lat0 = all.reduce((a, p) => a + p[0], 0) / all.length
  const k = Math.cos((lat0 * Math.PI) / 180)
  const xs = all.map((p) => p[1] * k)
  const ys = all.map((p) => -p[0])
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys)
  const span = Math.max(maxX - minX, (maxY - minY) * ((W - 2 * PAD) / (H - 2 * PAD)), 0.01)
  const s = (W - 2 * PAD) / span
  const ox = (W - (maxX - minX) * s) / 2, oy = (H - (maxY - minY) * s) / 2
  const at = (lat: number, lon: number) => ({ x: ox + (lon * k - minX) * s, y: oy + (-lat - minY) * s })
  return {
    pts: mapped.map((l) => ({ l, ...at(l.lat as number, l.lon as number) })),
    c: center ? at(center.lat, center.lon) : null,
  }
}

export function DirectoryMap({ listings, center, metroLabel, renderCard }: {
  listings: DirListing[]; center?: { lat: number; lon: number } | null; metroLabel: string
  renderCard: (l: DirListing) => React.ReactNode
}) {
  const { pts, c } = useMemo(() => project(listings, center), [listings, center])
  const [sel, setSel] = useState<string | null>(null)
  const [street, setStreet] = useState(false)
  const picked = pts.find((p) => p.l.id === sel)?.l ?? null
  const unmapped = listings.length - pts.length

  function pick(id: string) { setSel(id === sel ? null : id); setStreet(false) }

  if (!pts.length) {
    return <p className="px-1 text-[0.7059rem] text-(--text-muted)">No meet spots on the map yet. The list has every group.</p>
  }
  return (
    <div className="flex flex-col gap-2">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Map of ${pts.length} meet spots around ${metroLabel}. Pick a group from the list below the map.`}
        className="w-full rounded-2xl border border-(--border) bg-(--bg-inset)">
        {[1, 2, 3].map((i) => (
          <g key={i} stroke="var(--border)" strokeWidth={1}>
            <line x1={(W / 4) * i} y1={0} x2={(W / 4) * i} y2={H} />
            {i < 3 && <line x1={0} y1={(H / 3) * i} x2={W} y2={(H / 3) * i} />}
          </g>
        ))}
        {c && (
          <g aria-hidden>
            <circle cx={c.x} cy={c.y} r={5} fill="none" stroke="var(--text-muted)" strokeWidth={1.5} />
            <text x={c.x + 8} y={c.y + 4} fontSize={12} fill="var(--text-muted)">{metroLabel.split(',')[0]}</text>
          </g>
        )}
        {pts.map((p) => {
          const on = p.l.id === sel
          return (
            <g key={p.l.id} onClick={() => pick(p.l.id)} className="cursor-pointer" aria-hidden>
              <circle cx={p.x} cy={p.y} r={20} fill="transparent" />
              <path d={`M ${p.x} ${p.y} l -6 -11 a 7 7 0 1 1 12 0 z`} fill={on ? 'var(--brand)' : 'var(--accent)'}
                stroke="var(--bg-surface)" strokeWidth={1.5} transform={on ? `translate(${p.x} ${p.y}) scale(1.3) translate(${-p.x} ${-p.y})` : undefined} />
            </g>
          )
        })}
      </svg>
      <ul className="flex flex-col gap-1" aria-label="Groups on the map">
        {pts.map(({ l }) => (
          <li key={l.id}>
            <button type="button" aria-pressed={l.id === sel} onClick={() => pick(l.id)}
              className={cn('flex min-h-11 w-full items-center gap-2 rounded-xl border px-3 py-2 text-left',
                l.id === sel ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
              <MapPin className="size-4 shrink-0 text-(--accent)" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8235rem] text-(--text)">{l.name}</span>
                <span className="block truncate text-[0.7059rem] text-(--text-muted)">
                  {[nextLabel(l.next), l.meet_spot].filter(Boolean).join(' · ')}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {unmapped > 0 && (
        <p className="px-1 text-[0.6471rem] text-(--text-muted)">
          {unmapped} more {unmapped === 1 ? 'group has' : 'groups have'} no mapped meet spot. They're in the list.
        </p>
      )}
      {picked && typeof picked.lat === 'number' && typeof picked.lon === 'number' && (
        <div className="flex flex-col gap-2" aria-live="polite">
          {renderCard(picked)}
          {street ? (
            <iframe title={`Street map: ${picked.meet_spot || picked.name}`} src={osmEmbedUrl(picked.lat, picked.lon)}
              loading="lazy" referrerPolicy="no-referrer" sandbox="allow-scripts allow-same-origin allow-popups"
              className="h-56 w-full rounded-2xl border border-(--border)" />
          ) : (
            <button type="button" onClick={() => setStreet(true)}
              className="inline-flex min-h-11 items-center gap-1.5 self-start text-[0.7647rem] font-medium text-(--accent)">
              <MapIcon className="size-3.5" aria-hidden /> Show street map
            </button>
          )}
          <a href={osmLink(picked.lat, picked.lon)} target="_blank" rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-1.5 self-start text-[0.7059rem] text-(--text-secondary)">
            Open in OpenStreetMap <ExternalLink className="size-3.5" aria-hidden />
          </a>
          <p className="text-[0.6471rem] text-(--text-muted)">Map © OpenStreetMap contributors. Meet spots are approximate.</p>
        </div>
      )}
    </div>
  )
}
