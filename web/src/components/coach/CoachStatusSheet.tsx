// "Looking for a coach?": asked once (the optional "coach_status" setup quest, or the Me
// row while unanswered). Saves athlete.coach_status; "looking" opens Find a coach.
import { useRef, useState } from 'react'
import { Check, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { putAthlete, type Athlete, type CoachStatus } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useDialog } from '@/hooks/useDialog'

const CHOICES: { id: CoachStatus; title: string; sub: string }[] = [
  { id: 'looking', title: "I'd like a coach", sub: 'See coaches who fit your race' },
  { id: 'have_coach', title: 'I already have one', sub: 'Invite them to see your plan' },
  { id: 'self_coached', title: "I'll go solo", sub: 'Rabbit has your back' },
]

export function CoachStatusSheet({ current, onClose, onSaved }: {
  current?: CoachStatus | null
  onClose: () => void
  /** after saving; the caller routes on the choice and refreshes /me */
  onSaved: (s: CoachStatus) => void
}) {
  const [pick, setPick] = useState<CoachStatus | null>(current ?? null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  useDialog(box, () => { if (!busy) onClose() })

  async function save() {
    if (!pick) return
    setBusy(true); setErr(null)
    try { await putAthlete({ coach_status: pick } as Athlete); onSaved(pick) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="modal-overlay" onClick={() => { if (!busy) onClose() }}>
      <div ref={box} className="modal" role="dialog" aria-modal="true" aria-labelledby="cs-title" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 id="cs-title" className="modal-title">Do you want a coach?</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">
            A human coach can work alongside Rabbit. You can change this any time.
          </p>
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">Coaching</legend>
            {CHOICES.map((c) => {
              const on = pick === c.id
              return (
                <label key={c.id}
                  className={cn('flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-(--accent)',
                    on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
                  <input type="radio" name="coach-status" value={c.id} checked={on} onChange={() => setPick(c.id)} className="sr-only" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[0.9412rem] text-(--text)">{c.title}</span>
                    <span className="block text-[0.7647rem] text-(--text-muted)">{c.sub}</span>
                  </span>
                  <span aria-hidden="true" className={cn('flex size-5 shrink-0 items-center justify-center rounded-full border',
                    on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')}>
                    {on && <Check className="size-3" />}
                  </span>
                </label>
              )
            })}
          </fieldset>
          {err && <p className="text-[0.7647rem] text-(--danger)" role="alert">{err}</p>}
          <Button variant="primary" className="h-11 w-full text-[0.8824rem]" loading={busy} disabled={!pick}
            onClick={() => void save()}>Save</Button>
        </div>
      </div>
    </div>
  )
}
