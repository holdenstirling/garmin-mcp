// Route maps for outdoor GPS workouts (server: routes.py). The line is already trimmed at both ends
// (the owner's 200 / 400 / 800 m setting) and simplified on the server, so these draw exactly what
// they're given. RouteMini: a static, non-interactive picture on a Feed card (same OSM tiles and
// dark-mode treatment as the Local map). RouteMap: the pannable, zoomable map on a workout's page.
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { SlippyMap, TILE_URL, worldX, worldY } from '@/components/local/SlippyMap'
import { cn } from '@/lib/utils'

export type RouteLine = [number, number][]
const TILE = 256

/** The highest zoom (up to 16) at which the whole line fits w x h with ``pad`` px on every side. */
function fit(line: RouteLine, w: number, h: number, pad: number): number {
  for (let z = 16; z >= 3; z--) {
    const xs = line.map((p) => worldX(p[1], z)), ys = line.map((p) => worldY(p[0], z))
    if (Math.max(...xs) - Math.min(...xs) <= w - 2 * pad && Math.max(...ys) - Math.min(...ys) <= h - 2 * pad) return z
  }
  return 3
}

export function RouteMini({ line, height = 132, className, label = 'Route map' }: {
  line: RouteLine; height?: number; className?: string; label?: string
}) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(320)
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const measure = () => setW(el.clientWidth || 320)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const g = useMemo(() => {
    if (line.length < 2) return null
    const z = fit(line, w, height, 18)
    const xs = line.map((p) => worldX(p[1], z)), ys = line.map((p) => worldY(p[0], z))
    const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2
    const left = cx - w / 2, top = cy - height / 2
    const n = 2 ** z
    const tiles: { key: string; src: string; x: number; y: number }[] = []
    for (let tx = Math.floor(left / TILE); tx <= Math.floor((left + w) / TILE); tx++) {
      for (let ty = Math.floor(top / TILE); ty <= Math.floor((top + height) / TILE); ty++) {
        if (ty < 0 || ty >= n) continue
        tiles.push({ key: `${z}/${tx}/${ty}`, src: TILE_URL(z, ((tx % n) + n) % n, ty), x: tx * TILE - left, y: ty * TILE - top })
      }
    }
    const pts = xs.map((x, i) => `${(x - left).toFixed(1)},${(ys[i]! - top).toFixed(1)}`).join(' ')
    const first = { x: xs[0]! - left, y: ys[0]! - top }, last = { x: xs[xs.length - 1]! - left, y: ys[ys.length - 1]! - top }
    return { tiles, pts, first, last }
  }, [line, w, height])

  return (
    <div ref={box} role="img" aria-label={label}
      className={cn('relative overflow-hidden rounded-xl border border-(--border) bg-(--bg-inset)', className)} style={{ height }}>
      {g && (
        <>
          <div className="slippy__tiles absolute inset-0" aria-hidden>
            {g.tiles.map((t) => (
              <img key={t.key} src={t.src} alt="" width={TILE} height={TILE} draggable={false} decoding="async" loading="lazy"
                referrerPolicy="strict-origin-when-cross-origin" className="absolute max-w-none"
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }}
                style={{ left: t.x, top: t.y, width: TILE, height: TILE }} />
            ))}
          </div>
          <svg className="pointer-events-none absolute inset-0" width="100%" height={height} aria-hidden>
            <polyline points={g.pts} fill="none" stroke="var(--route-casing, white)" strokeWidth={6} strokeLinejoin="round" strokeLinecap="round" opacity={0.9} />
            <polyline points={g.pts} fill="none" stroke="var(--route, var(--accent))" strokeWidth={3.5} strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={g.first.x} cy={g.first.y} r={4.5} fill="var(--bg-surface)" stroke="var(--route, var(--accent))" strokeWidth={2.5} />
            <circle cx={g.last.x} cy={g.last.y} r={4.5} fill="var(--route, var(--accent))" stroke="var(--route-casing, white)" strokeWidth={2} />
          </svg>
        </>
      )}
      <p className="absolute bottom-0 right-0 rounded-tl-md bg-(--bg-surface)/90 px-1.5 py-px text-caption leading-4 text-(--text-secondary)">
        © OpenStreetMap contributors
      </p>
    </div>
  )
}

/** The interactive route map on a workout's page. */
export function RouteMap({ line, height = 260, label = 'Route map' }: { line: RouteLine; height?: number; label?: string }) {
  return <SlippyMap pins={[]} path={line} onSelect={() => {}} locate={false} height={height} label={label} />
}
