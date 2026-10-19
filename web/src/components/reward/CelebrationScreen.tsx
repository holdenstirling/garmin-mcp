// A full-screen moment for things that took weeks: a race finish, a finished training block, a
// personal record that's the best in 12 months or ever (server: celebrate.py; records come from
// the post-workout reward). Shown once per achievement on any device (marked seen as it opens).
// Carrot bursts + a haptic, still under reduced motion; a share card (canvas, like the month card).
import { useEffect, useRef, useState } from 'react'
import { Award, Download, Flag, Share2, Trophy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { celebrate, reducedMotion } from '@/components/fx/motion'
import { haptic } from '@/lib/haptics'
import { markCelebrated, type Celebration } from '@/lib/trends'
import { drawCelebrationCard } from './celebrationCard'
import { CARD_H, CARD_W, shareImage } from './monthCard'

const EYEBROW: Record<Celebration['kind'], string> = { race: 'Race finish', block: 'Block complete', pr: 'Personal record' }
const ICON = { race: Flag, block: Trophy, pr: Award } as const

export function CelebrationScreen({ c, onClose }: { c: Celebration; onClose: () => void }) {
  const [img, setImg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const canvas = useRef<HTMLCanvasElement | null>(null)
  const done = useRef<HTMLButtonElement>(null)
  const hero = useRef<HTMLDivElement>(null)
  const Icon = ICON[c.kind]

  useEffect(() => {
    markCelebrated(c.id).catch(() => { /* shown again next time; harmless */ })
    haptic(35)
    const t1 = window.setTimeout(() => celebrate(hero.current, c.kind === 'race' ? 'race' : 'badge'), 350)
    const t2 = reducedMotion() ? 0 : window.setTimeout(() => celebrate({ x: window.innerWidth * 0.25, y: window.innerHeight * 0.3 }, 'kudos'), 1300)
    done.current?.focus()
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => { window.clearTimeout(t1); window.clearTimeout(t2); window.removeEventListener('keydown', k) }
  }, [c.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let live = true
    const cv = canvas.current ?? (canvas.current = document.createElement('canvas'))
    drawCelebrationCard(cv, { eyebrow: EYEBROW[c.kind], title: c.title, subtitle: c.subtitle, stats: c.stats })
      .then(() => { if (live) setImg(cv.toDataURL('image/png')) }, () => {})
    return () => { live = false }
  }, [c])

  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'
  async function share(el: HTMLElement) {
    if (!canvas.current) return
    setBusy(true); setNote(null)
    try {
      const how = await shareImage(canvas.current, `rabbt-${c.kind}-${c.date}.png`, `${c.title} ${c.subtitle}`)
      if (how === 'downloaded') setNote('Saved the image. Post it anywhere you like.')
      if (how !== 'cancelled') celebrate(el, 'kudos')
    } catch (e) { setNote((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="fx-cel fixed inset-0 z-(--z-dialog) flex flex-col overflow-y-auto bg-(--brand) text-(--bg)"
      role="dialog" aria-modal="true" aria-labelledby="cel-title" aria-describedby="cel-line" data-usage-card="celebration">
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-5 px-6 pb-[max(24px,env(safe-area-inset-bottom))] pt-[max(40px,env(safe-area-inset-top))] text-center">
        <div ref={hero} className="relative flex size-28 items-center justify-center">
          <span className="fx-cel-glow absolute inset-0 rounded-full bg-(--bg)" aria-hidden="true" />
          <span className="fx-medal relative flex size-24 items-center justify-center rounded-full border-4 border-(--bg) bg-(--brand)">
            <Icon className="size-11" aria-hidden="true" />
          </span>
        </div>
        <p className="fx-cel-rise m-0 text-meta font-semibold opacity-90" style={{ animationDelay: '150ms' }}>
          {EYEBROW[c.kind]}
        </p>
        <h2 id="cel-title" className="fx-cel-rise m-0 font-display text-display-2xl leading-none" style={{ animationDelay: '220ms' }}>{c.title}</h2>
        <p className="fx-cel-rise m-0 text-title-sm font-semibold" style={{ animationDelay: '300ms' }}>{c.subtitle}</p>
        <p id="cel-line" className="fx-cel-rise m-0 max-w-xs text-body-lg leading-snug opacity-90" style={{ animationDelay: '380ms' }}>{c.line}</p>
        {c.stats.length > 0 && (
          <ul className="fx-cel-rise m-0 grid w-full list-none gap-3 p-0" style={{ animationDelay: '460ms', gridTemplateColumns: 'repeat(auto-fit, minmax(6.5rem, 1fr))' }}>
            {c.stats.map((s) => (
              <li key={s.label} className="flex flex-col items-center gap-0.5 rounded-xl border border-(--bg)/25 px-3 py-3">
                <span className="text-small font-medium opacity-90">{s.label}</span>
                <span className="text-title-sm font-semibold tabular-nums">{s.value}</span>
              </li>
            ))}
          </ul>
        )}
        {img && (
          <img src={img} alt={`Share card: ${c.title} ${c.subtitle}. ${c.stats.map((s) => `${s.label} ${s.value}`).join(', ')}.`}
            width={CARD_W} height={CARD_H} className="fx-cel-rise h-auto w-32 rounded-xl shadow-lg" style={{ animationDelay: '600ms' }} />
        )}
        <div className="mt-1 flex w-full flex-col gap-2">
          <Button variant="default" className="h-12 gap-1.5 border-(--bg) bg-(--bg) text-body-lg text-(--brand)" loading={busy} disabled={!img}
            onClick={(e) => void share(e.currentTarget)}>
            {canShare ? <><Share2 className="size-5" aria-hidden="true" /> Share</> : <><Download className="size-5" aria-hidden="true" /> Download image</>}
          </Button>
          <button ref={done} type="button" onClick={onClose}
            className="min-h-12 rounded-(--radius) text-body-lg font-medium underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-(--bg)">
            {c.kind === 'block' ? 'On to the next one' : 'Done'}
          </button>
          {note && <p className="m-0 text-meta opacity-90" role="status">{note}</p>}
        </div>
      </div>
    </div>
  )
}
