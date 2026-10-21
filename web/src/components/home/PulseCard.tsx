// The day-7 pulse (server: traction.py): "How likely are you to recommend rabbt to a friend?"
// 0-10 plus an optional note. Asked once (answer or dismiss), never when usage counting is off.
// The score is only a tally; the note reaches the owners as feedback.
import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { RabbitNap } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { areaCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { answerPulse, dismissPulse, getPulse } from '@/lib/traction'

export function PulseCard() {
  const [ask, setAsk] = useState(false)
  const [score, setScore] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getPulse().then((r) => setAsk(r.ask), () => {}) }, [])
  if (!ask) return null
  if (sent) {
    return (
      <div role="status" className="flex items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
        <RabbitNap size={36} mode="cheer" />
        <p className="m-0 flex-1 text-body font-semibold text-(--text)">Thank you! That really helps.</p>
        <button type="button" aria-label="Close" className="flex size-11 items-center justify-center text-(--text-muted)" onClick={() => setAsk(false)}><X className="size-5" /></button>
      </div>
    )
  }
  async function send() {
    if (score == null) return
    setBusy(true)
    try { await answerPulse(score, note.trim()); setSent(true) } catch { setAsk(false) } finally { setBusy(false) }
  }
  return (
    <section aria-labelledby="pulse-q" className="flex flex-col gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-start gap-3">
        <RabbitNap size={36} mode="think" />
        <h2 id="pulse-q" className="m-0 flex-1 pt-1 text-body-lg font-semibold leading-snug text-(--text)">How likely are you to recommend rabbt to a friend?</h2>
        <button type="button" aria-label="Not now" className="-mr-2 -mt-2 flex size-11 shrink-0 items-center justify-center text-(--text-muted)"
          onClick={() => { setAsk(false); void dismissPulse().catch(() => {}) }}><X className="size-5" /></button>
      </div>
      <div className="grid grid-cols-6 gap-1.5 min-[400px]:grid-cols-11" role="radiogroup" aria-label="0 is not likely, 10 is very likely">
        {Array.from({ length: 11 }, (_, i) => (
          <button key={i} type="button" role="radio" aria-checked={score === i} onClick={() => setScore(i)}
            className={cn('flex h-11 items-center justify-center rounded-lg border text-body font-semibold tabular-nums',
              score === i ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) bg-(--bg) text-(--text)')}>{i}</button>
        ))}
      </div>
      <div className="flex justify-between text-meta text-(--text-muted)" aria-hidden><span>Not likely</span><span>Very likely</span></div>
      {score != null && (
        <>
          <label className="sr-only" htmlFor="pulse-note">Anything we should know? (optional)</label>
          <textarea id="pulse-note" className={cn(areaCls, 'min-h-[72px]')} maxLength={500} placeholder="Anything we should know? (optional)"
            value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="primary" className="h-11 w-full text-body" loading={busy} onClick={() => void send()}>Send</Button>
        </>
      )}
    </section>
  )
}
