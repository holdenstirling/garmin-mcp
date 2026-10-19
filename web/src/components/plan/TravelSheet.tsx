// Travel mode: mark days away and what you'll have there; the plan swaps sessions to
// fit and moves long sessions to home days of the same week. Undo any time.
import { useState } from 'react'
import { Plane } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Row, Switch } from '@/components/settings/Grouped'
import type { TripOptions } from '@/lib/calendar'
import { Card, Field, inputCls } from './ui'
import { todayStr } from './PlanParts'
import { Sheet } from '@/components/ui/Sheet'

export function TravelSheet({ initial, raceDate, today = todayStr(), onApply, onClose, onDismissed, closing }: {
  initial?: { start: string; end: string; label: string }
  raceDate: string
  /** the athlete's date from the server (defaults to the device's) */
  today?: string
  onApply: (b: { start: string; end: string; label: string } & TripOptions) => Promise<void>
  onClose: () => void; onDismissed: () => void; closing: boolean
}) {
  const [start, setStart] = useState(initial?.start ?? today)
  const [end, setEnd] = useState(initial?.end ?? today)
  const [label, setLabel] = useState(initial?.label ?? '')
  const [has, setHas] = useState<TripOptions>({ gym: true, treadmill: false, pool: false, bike: false })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toggle = (k: keyof TripOptions) => (v: boolean) => setHas((h) => ({ ...h, [k]: v }))

  async function apply() {
    setBusy(true); setError(null)
    try { await onApply({ start, end: end < start ? start : end, label: label.trim() || 'Travel', ...has }); onClose() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <Sheet title="Travel mode" onClose={onClose} closing={closing} onDismissed={onDismissed} bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <p className="px-1 text-small leading-snug text-(--text-muted)">
            rabbt reworks the sessions on those days for what you'll have, keeps them under 75 minutes, and moves long sessions to home days that week.
          </p>
          <Card>
            <Field label="Trip">
              <input className={inputCls} value={label} maxLength={60} placeholder="e.g. Work trip to NYC" onChange={(e) => setLabel(e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 border-t border-(--border)">
              <Field label="Leave">
                <input type="date" className={inputCls} value={start} min={today} max={raceDate} onChange={(e) => e.target.value && setStart(e.target.value)} />
              </Field>
              <Field label="Back">
                <input type="date" className={inputCls} value={end} min={start} max={raceDate} onChange={(e) => e.target.value && setEnd(e.target.value)} />
              </Field>
            </div>
          </Card>
          <Card>
            <Row title="Hotel gym" subtitle="Weights, spin or stationary bike" trailing={<Switch label="Hotel gym" checked={has.gym} onChange={toggle('gym')} />} />
            <Row title="Treadmill" trailing={<Switch label="Treadmill" checked={has.treadmill} onChange={toggle('treadmill')} />} />
            <Row title="Pool" trailing={<Switch label="Pool" checked={has.pool} onChange={toggle('pool')} />} />
            <Row title="My bike or a rental" trailing={<Switch label="Bike" checked={has.bike} onChange={toggle('bike')} />} />
          </Card>
          {error && <p className="px-1 text-small text-(--danger)" role="alert">{error}</p>}
          <Button variant="primary" className="h-11 gap-1.5 text-body" loading={busy} onClick={() => void apply()}>
            <Plane className="size-5" /> Plan around this trip
          </Button>
    </Sheet>
  )
}
