// "Your September": the monthly recap as a share image (server totals from reward.py, drawn
// client-side by monthCard.ts). Share uses the system share sheet with the PNG where the
// browser supports files, else downloads it. From Progress and the moment on the 1st.
import { useEffect, useRef, useState } from 'react'
import { Download, Share2, X } from 'lucide-react'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { burst } from '@/components/anim'
import { getMonthRecap, type MonthRecap } from '@/lib/reward'
import { drawMonthCard, shareCard, tiles, CARD_H, CARD_W } from './monthCard'

export function MonthRecapSheet({ month, onClose }: { month?: string; onClose: () => void }) {
  const [r, setR] = useState<MonthRecap | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [img, setImg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [tries, setTries] = useState(0)
  const canvas = useRef<HTMLCanvasElement | null>(null)
  const drag = useSheetDrag(onClose)
  useEffect(() => {
    let live = true
    setError(null)
    getMonthRecap(month).then((x) => { if (live) setR(x) }, (e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [month, tries])
  useEffect(() => {
    if (!r || !r.sessions) return
    let live = true
    const c = canvas.current ?? (canvas.current = document.createElement('canvas'))
    drawMonthCard(c, r).then(() => { if (live) setImg(c.toDataURL('image/png')) }, () => { if (live) setError("Couldn't draw the card.") })
    return () => { live = false }
  }, [r])
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }
  const canShareFiles = typeof navigator !== 'undefined' && typeof navigator.share === 'function'

  async function share(el: HTMLElement) {
    if (!r || !canvas.current) return
    setBusy(true); setNote(null)
    try {
      const how = await shareCard(canvas.current, r)
      if (how === 'downloaded') setNote('Saved the image. Post it anywhere you like.')
      if (how !== 'cancelled') burst(el, 'kudos')
    } catch (e) { setNote((e as Error).message) } finally { setBusy(false) }
  }

  const alt = r ? `Your ${r.label} on rabbt: ${tiles(r).map(([k, v]) => `${k} ${v}`).join(', ')}.` : ''
  return (
    <div className={`modal-overlay ${closing ? 'modal-overlay--exit' : ''}`} onClick={close}>
      <div className={`modal ${closing ? 'modal--exit' : ''}`} onClick={(e) => e.stopPropagation()} {...drag}
        role="dialog" aria-modal aria-labelledby="month-title">
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 id="month-title" className="modal-title">{r ? `Your ${r.label}` : 'Your month'}</h2>
          <button className="modal-close hit-44" aria-label="Close" onClick={close}><X className="size-5" /></button>
        </div>
        <div className="modal-body flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {!r && !error && <RabbitLoader className="py-10" label="Adding up your month" cycle={['Adding up your hours…', 'Finding your longest day…', 'Drawing your card…']} />}
          {error && <ErrorState message={`Couldn't load your recap: ${error}`} onRetry={() => setTries((n) => n + 1)} compact />}
          {r && !r.sessions && (
            <p className="py-8 text-center text-body text-(--text-muted)">No workouts synced in {r.label}. Next month's card starts with your next one.</p>
          )}
          {r && r.sessions > 0 && (
            <>
              {img
                ? <img src={img} alt={alt} width={CARD_W} height={CARD_H} className="mx-auto h-auto w-full max-w-sm rounded-2xl shadow-sm" />
                : <div className="skeleton mx-auto aspect-[4/5] w-full max-w-sm rounded-2xl" aria-hidden="true" />}
              <p className="m-0 text-center text-meta text-(--text-muted)">Totals only: no names, places or heart rate.</p>
              <Button variant="primary" className="h-11 gap-1.5 text-body" loading={busy} disabled={!img}
                onClick={(e) => void share(e.currentTarget)}>
                {canShareFiles ? <><Share2 className="size-5" aria-hidden="true" /> Share</> : <><Download className="size-5" aria-hidden="true" /> Download image</>}
              </Button>
              {note && <p className="m-0 text-center text-meta text-(--text-secondary)" role="status">{note}</p>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
