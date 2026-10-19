// "Check-ins" under Stats > More stats: the last 30 days of voice check-ins, newest first,
// with the summary, date, chips and delete.
import { confirmAsk } from '@/lib/confirm'
import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Card } from '@/components/plan/ui'
import { deleteCheckin, listCheckins, type Checkin } from '@/lib/checkins'
import { CheckinChips } from './VoiceCheckIn'
import { EmptyRabbit } from '@/components/anim'

function fmtDate(d: string): string {
  return new Date(`${d}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

export function CheckinsCard() {
  const [items, setItems] = useState<Checkin[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { listCheckins(30).then((r) => setItems(r.checkins), (e) => setError((e as Error).message)) }, [])
  async function remove(id: string) {
    if (!(await confirmAsk('Delete this check-in?', { confirm: 'Delete', danger: true }))) return
    try {
      await deleteCheckin(id)
      setItems((cur) => cur?.filter((c) => c.id !== id) ?? null)
    } catch (e) { setError((e as Error).message) }
  }
  return (
    <section className="flex flex-col gap-2">
      <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Check-ins · last 30 days</h2>
      <Card>
        {error && <p className="px-4 py-3 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
        {items && items.length === 0 && (
          <EmptyRabbit className="px-4 pb-3 pt-4" size={44}
            body="None yet. Tap the mic on home after a workout and tell rabbt how it felt." />
        )}
        {items?.map((c, i) => (
          <div key={c.id} className={`flex items-start gap-2 px-4 py-3 ${i ? 'border-t border-(--border)' : ''}`}>
            <div className="min-w-0 flex-1">
              <p className="text-[0.8235rem] leading-snug text-(--text)">{c.summary || 'Checked in.'}</p>
              <p className="mb-1.5 text-[0.6471rem] text-(--text-muted)">{fmtDate(c.date)}{c.edited ? ' · edited' : ''}</p>
              <CheckinChips c={c} />
            </div>
            <button type="button" aria-label="Delete check-in" onClick={() => void remove(c.id)}
              className="hit-44 flex size-8 shrink-0 items-center justify-center rounded-full text-(--text-muted) hover:bg-(--bg-inset) hover:text-(--danger)">
              <Trash2 className="size-4" />
            </button>
          </div>
        ))}
      </Card>
    </section>
  )
}
