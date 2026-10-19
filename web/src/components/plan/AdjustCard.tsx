// Rabbit's suggested changes to the rest of the week, approved with one tap.
import { useState } from 'react'
import { ArrowRight, HeartPulse } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Button } from '@/components/ui/button'
import { KIND_LABEL, fmtMin } from '@/lib/plan'
import { decideAdjust, type Proposal } from '@/lib/adjust'
import type { BuiltPlan } from '@/lib/plan'
import { fmtDay } from './PlanParts'

export function AdjustCard({ p, onDone }: { p: Proposal; onDone: (plan: BuiltPlan | null, msg: string) => void }) {
  const [busy, setBusy] = useState<'apply' | 'dismiss' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  if (p.status === 'watch' && p.reasons?.length) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-(--warning)/30 bg-(--warning-subtle) px-3.5 py-2.5">
        <HeartPulse className="mt-0.5 size-5 shrink-0 text-(--warning-text)" />
        <p className="text-small leading-snug text-(--text-secondary)">{p.reasons.join(' ')} Nothing hard is coming up, so keep today easy and sleep well.</p>
      </div>
    )
  }
  if (p.status !== 'suggest') return null
  async function decide(action: 'apply' | 'dismiss') {
    if (p.status !== 'suggest') return
    setBusy(action); setError(null)
    try {
      const r = await decideAdjust(p.id, action)
      onDone(r.plan, action === 'apply' ? `Updated ${r.applied} session${r.applied === 1 ? '' : 's'}. Sync to Garmin to update your watch.` : 'OK, keeping the plan as it is.')
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }
  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) px-3.5 py-3">
      <p className="flex items-center gap-2 text-body-lg font-medium text-(--accent)"><RabbitLogo size={16} current /> rabbt suggests adjusting your plan</p>
      <ul className="flex flex-col gap-1 text-small leading-snug text-(--text-secondary)">
        {p.reasons.map((r) => <li key={r}>• {r}</li>)}
      </ul>
      {p.tip && <p className="text-meta leading-snug text-(--text-muted)">{p.tip}</p>}
      {open && (
        <div className="flex flex-col gap-2 rounded-lg bg-(--bg-surface) p-2.5">
          {p.changes.map((c) => (
            <div key={`${c.session_id}-${c.date}`} className="text-small">
              <p className="text-caption text-(--text-muted) font-semibold">{fmtDay(c.date)}</p>
              <p className="flex flex-wrap items-center gap-1.5 text-(--text)">
                <span className="text-(--text-muted) line-through">{c.from.title}{c.from.minutes ? ` ${fmtMin(c.from.minutes)}` : ''}</span>
                <ArrowRight className="size-4 text-(--accent)" />
                <span>{c.action === 'rest' ? 'Rest' : `${KIND_LABEL[c.to.kind ?? ''] ?? c.to.kind} ${c.to.sport}${c.to.minutes ? ` ${fmtMin(c.to.minutes)}` : ''}`}{c.action === 'move' ? ' (added back)' : ''}</span>
              </p>
              <p className="text-caption text-(--text-muted)">{c.why}</p>
            </div>
          ))}
        </div>
      )}
      {error && <p className="text-meta text-(--danger)">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" className="h-11 flex-1 text-small" loading={busy === 'apply'} disabled={busy != null} onClick={() => void decide('apply')}>
          Apply {p.changes.length} change{p.changes.length === 1 ? '' : 's'}
        </Button>
        <Button variant="default" className="h-11 px-3 text-small" onClick={() => setOpen((v) => !v)}>{open ? 'Hide' : 'See changes'}</Button>
        <Button variant="ghost" className="h-11 px-2 text-small" loading={busy === 'dismiss'} disabled={busy != null} onClick={() => void decide('dismiss')}>Not now</Button>
      </div>
    </div>
  )
}
