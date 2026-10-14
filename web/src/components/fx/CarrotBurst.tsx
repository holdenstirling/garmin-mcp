// CarrotBurst: tiny carrots and sparkles flung from a point, with a dust puff. Rendered once
// via FxHost (a portal on <body>); trigger anywhere with celebrate()/useCelebrate().
import { createPortal } from 'react-dom'
import { Carrot, Puff, Sparkle } from './shapes'
import { useBurst, type BurstKind } from './motion'

const COUNT: Record<BurstKind, number> = { xp: 9, checkin: 9, race: 11, plan: 12, challenge: 12, badge: 14, level: 16 }

// Small deterministic PRNG so a burst looks the same if React renders it twice.
function rng(seed: number) {
  let s = seed * 9301 + 49297
  return () => { s = (s * 9301 + 49297) % 233280; return s / 233280 }
}

export function CarrotBurst({ x, y, kind = 'xp', seed = 1 }: { x: number; y: number; kind?: BurstKind; seed?: number }) {
  const n = COUNT[kind]
  const r = rng(seed)
  const big = kind === 'level' || kind === 'badge'
  const parts = Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2 + r() * 0.5 - Math.PI / 2
    const dist = (big ? 70 : 52) + r() * (big ? 60 : 40)
    return {
      carrot: i % 3 !== 2,
      dx: Math.round(Math.cos(a) * dist),
      dy: Math.round(Math.sin(a) * dist * 0.85 - 12),
      rot: Math.round((r() - 0.5) * 540),
      delay: Math.round(r() * 80),
      size: Math.round((big ? 14 : 12) + r() * 6),
    }
  })
  return (
    <div className="fx-burst" style={{ left: x, top: y }} aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <Puff key={`p${i}`} size={18} className="fx-burst__puff"
          style={{ ['--dx' as string]: `${(i - 1) * 16}px`, animationDelay: `${i * 30}ms` }} />
      ))}
      {parts.map((p, i) => {
        const style = {
          ['--dx' as string]: `${p.dx}px`, ['--dy' as string]: `${p.dy}px`, ['--rot' as string]: `${p.rot}deg`,
          animationDelay: `${p.delay}ms`,
        }
        return p.carrot
          ? <Carrot key={i} size={p.size} className="fx-burst__bit" style={style} />
          : <Sparkle key={i} size={p.size - 3} className="fx-burst__bit fx-burst__spark" style={style} />
      })}
    </div>
  )
}

/** Mount once near the app root. Shows the current burst (max one at a time). */
export function FxHost() {
  const b = useBurst()
  if (!b || typeof document === 'undefined') return null
  return createPortal(<CarrotBurst key={b.id} x={b.x} y={b.y} kind={b.kind} seed={b.id} />, document.body)
}
