// A small, dependency-free street map: OpenStreetMap raster tiles in a pannable, zoomable view
// with tappable pins. Drag (mouse or one finger) pans, pinch / wheel / the +- buttons zoom by
// whole levels. Pins are real buttons with names, so keyboard and screen readers can use them,
// but the list next to the map stays the main way to browse.
//
// Tiles: tile.openstreetmap.org under the OSMF tile usage policy (attribution visible, a real
// Referer, only the current view, no offline or bulk use). TILE_URL is the one place to switch
// to a paid provider before heavy use. The app sends no Referer by default (Caddy sets
// Referrer-Policy: no-referrer), so each tile asks for its origin to be sent.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { LocateFixed, Minus, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'

export const TILE_URL = (z: number, x: number, y: number) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`
const TILE = 256
const MIN_Z = 3
const MAX_Z = 17

export type MapPin = {
  id: string
  lat: number
  lon: number
  /** accessible name: what it is and where */
  label: string
  /** the pin's face: an icon element */
  icon: ReactNode
  /** css color tokens for the pin */
  fg: string
  bg: string
}

export type Bounds = { north: number; south: number; east: number; west: number }

const worldX = (lon: number, z: number) => ((lon + 180) / 360) * TILE * 2 ** z
const worldY = (lat: number, z: number) => {
  const s = Math.sin((Math.max(-85, Math.min(85, lat)) * Math.PI) / 180)
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE * 2 ** z
}
const lonAt = (x: number, z: number) => (x / (TILE * 2 ** z)) * 360 - 180
const latAt = (y: number, z: number) => {
  const n = Math.PI - (2 * Math.PI * y) / (TILE * 2 ** z)
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))
}

/** The highest whole zoom that fits every point (with padding) in w x h. */
function fitZoom(pts: { lat: number; lon: number }[], w: number, h: number): number {
  if (pts.length < 2) return 13
  for (let z = 15; z >= MIN_Z; z--) {
    const xs = pts.map((p) => worldX(p.lon, z)), ys = pts.map((p) => worldY(p.lat, z))
    if (Math.max(...xs) - Math.min(...xs) <= w - 64 && Math.max(...ys) - Math.min(...ys) <= h - 72) return z
  }
  return MIN_Z
}

export function SlippyMap({ pins, center, selected, onSelect, onMoved, className, height = 340 }: {
  pins: MapPin[]
  /** the area to start on when there are no pins */
  center?: { lat: number; lon: number } | null
  selected?: string | null
  onSelect: (id: string | null) => void
  /** after the person pans or zooms: the visible area */
  onMoved?: (b: Bounds) => void
  className?: string
  height?: number
}) {
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 360, h: height })
  const [view, setView] = useState<{ lat: number; lon: number; z: number } | null>(null)
  const [pinch, setPinch] = useState(1)
  const drag = useRef<{ id: number; x: number; y: number; lat: number; lon: number; moved: boolean } | null>(null)
  const touches = useRef(new Map<number, { x: number; y: number }>())
  const pinch0 = useRef<number | null>(null)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const measure = () => setSize({ w: el.clientWidth || 360, h: el.clientHeight || height })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [height])

  // Start: fit the pins, else the person's area.
  const fitKey = pins.map((p) => p.id).join(',')
  useEffect(() => {
    const pts = pins.length ? pins : center ? [center] : []
    if (!pts.length) return
    const lat = (Math.max(...pts.map((p) => p.lat)) + Math.min(...pts.map((p) => p.lat))) / 2
    const lon = (Math.max(...pts.map((p) => p.lon)) + Math.min(...pts.map((p) => p.lon))) / 2
    setView({ lat, lon, z: pins.length ? fitZoom(pins, size.w, size.h) : 12 })
    // only when the set of pins changes, not on every resize
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, center?.lat, center?.lon])

  const report = useCallback((v: { lat: number; lon: number; z: number }) => {
    if (!onMoved) return
    const cx = worldX(v.lon, v.z), cy = worldY(v.lat, v.z)
    onMoved({
      north: latAt(cy - size.h / 2, v.z), south: latAt(cy + size.h / 2, v.z),
      west: lonAt(cx - size.w / 2, v.z), east: lonAt(cx + size.w / 2, v.z),
    })
  }, [onMoved, size.w, size.h])

  const zoomBy = (d: number) => setView((v) => {
    if (!v) return v
    const n = { ...v, z: Math.max(MIN_Z, Math.min(MAX_Z, v.z + d)) }
    report(n)
    return n
  })

  const tiles = useMemo(() => {
    if (!view) return []
    const { z } = view
    const cx = worldX(view.lon, z), cy = worldY(view.lat, z)
    const left = cx - size.w / 2, top = cy - size.h / 2
    const n = 2 ** z
    const out: { key: string; src: string; x: number; y: number }[] = []
    for (let tx = Math.floor(left / TILE); tx <= Math.floor((left + size.w) / TILE); tx++) {
      for (let ty = Math.floor(top / TILE); ty <= Math.floor((top + size.h) / TILE); ty++) {
        if (ty < 0 || ty >= n) continue
        const wx = ((tx % n) + n) % n
        out.push({ key: `${z}/${tx}/${ty}`, src: TILE_URL(z, wx, ty), x: tx * TILE - left, y: ty * TILE - top })
      }
    }
    return out
  }, [view, size.w, size.h])

  const place = (lat: number, lon: number) => {
    if (!view) return { x: 0, y: 0 }
    const cx = worldX(view.lon, view.z), cy = worldY(view.lat, view.z)
    return { x: worldX(lon, view.z) - cx + size.w / 2, y: worldY(lat, view.z) - cy + size.h / 2 }
  }

  const onDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
    if (touches.current.size === 2) {
      const [a, b] = [...touches.current.values()]
      pinch0.current = Math.hypot(a.x - b.x, a.y - b.y)
      drag.current = null
      return
    }
    if (view) drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, lat: view.lat, lon: view.lon, moved: false }
  }
  const onMove = (e: React.PointerEvent) => {
    if (!touches.current.has(e.pointerId)) return
    touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (touches.current.size === 2 && pinch0.current) {
      const [a, b] = [...touches.current.values()]
      setPinch(Math.max(0.25, Math.min(4, Math.hypot(a.x - b.x, a.y - b.y) / pinch0.current)))
      return
    }
    const d = drag.current
    if (!d || d.id !== e.pointerId || !view) return
    const dx = e.clientX - d.x, dy = e.clientY - d.y
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true
    const z = view.z
    setView({ z, lon: lonAt(worldX(d.lon, z) - dx, z), lat: latAt(worldY(d.lat, z) - dy, z) })
  }
  const onUp = (e: React.PointerEvent) => {
    touches.current.delete(e.pointerId)
    if (pinch0.current && touches.current.size < 2) {
      pinch0.current = null
      const d = Math.round(Math.log2(pinch))
      setPinch(1)
      if (d) zoomBy(d)
      return
    }
    const d = drag.current
    drag.current = null
    if (d?.moved && view) report(view)
  }
  const onWheel = (e: React.WheelEvent) => {
    if (Math.abs(e.deltaY) < 4) return
    zoomBy(e.deltaY < 0 ? 1 : -1)
  }

  const locate = () => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition((p) => {
      const n = { lat: p.coords.latitude, lon: p.coords.longitude, z: 14 }
      setView(n); report(n)
    }, () => {}, { maximumAge: 300_000, timeout: 10_000 })
  }

  return (
    <div className={cn('relative overflow-hidden rounded-2xl border border-(--border) bg-(--bg-inset)', className)} style={{ height }}>
      <div ref={box} className="slippy absolute inset-0 touch-none select-none"
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onWheel={onWheel}
        onClick={(e) => { if (!(e.target as HTMLElement).closest('button')) onSelect(null) }}>
        <div className="slippy__tiles absolute inset-0" aria-hidden
          style={{ transform: pinch !== 1 ? `scale(${pinch})` : undefined, transformOrigin: 'center' } as CSSProperties}>
          {tiles.map((t) => (
            <img key={t.key} src={t.src} alt="" width={TILE} height={TILE} draggable={false} decoding="async"
              referrerPolicy="strict-origin-when-cross-origin" className="absolute max-w-none"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }}
              style={{ left: t.x, top: t.y, width: TILE, height: TILE }} />
          ))}
        </div>
        {pinch === 1 && pins.map((p) => {
          const { x, y } = place(p.lat, p.lon)
          if (x < -24 || y < -24 || x > size.w + 24 || y > size.h + 24) return null
          const on = p.id === selected
          return (
            <button key={p.id} type="button" aria-label={p.label} aria-pressed={on}
              onClick={(e) => { e.stopPropagation(); onSelect(on ? null : p.id) }}
              className={cn('absolute flex -translate-x-1/2 -translate-y-full items-center justify-center rounded-full rounded-bl-none shadow-md ring-2 ring-white transition-transform',
                on ? 'z-10 size-11 scale-110' : 'size-9')}
              style={{ left: x, top: y, background: p.bg, color: p.fg, rotate: '-45deg' }}>
              <span style={{ rotate: '45deg' }} className="flex">{p.icon}</span>
            </button>
          )
        })}
      </div>
      <div className="absolute right-2 top-2 z-20 flex flex-col gap-2">
        <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1)}
          className="flex size-11 items-center justify-center rounded-xl bg-(--bg-surface) text-(--text) shadow-md active:bg-(--bg-inset)">
          <Plus className="size-5" aria-hidden />
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomBy(-1)}
          className="flex size-11 items-center justify-center rounded-xl bg-(--bg-surface) text-(--text) shadow-md active:bg-(--bg-inset)">
          <Minus className="size-5" aria-hidden />
        </button>
        <button type="button" aria-label="Show where I am" onClick={locate}
          className="flex size-11 items-center justify-center rounded-xl bg-(--bg-surface) text-(--text) shadow-md active:bg-(--bg-inset)">
          <LocateFixed className="size-5" aria-hidden />
        </button>
      </div>
      <p className="absolute bottom-0 right-0 z-20 rounded-tl-lg bg-(--bg-surface)/90 px-2 py-0.5 text-caption text-(--text-secondary)">
        © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener" className="underline">OpenStreetMap</a> contributors
      </p>
    </div>
  )
}
