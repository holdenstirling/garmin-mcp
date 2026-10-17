// A coming-soon app (Whoop, Coros; server: demand.py) in the same native-style sheet
// as the real connect popups: Rabbit ··· App tiles, what Rabbit would use it for, plainly why it
// can't connect yet, and one "I want this" toggle (counted once per person, so we can see how
// many people want each). Owners also see the count.
import { useState } from 'react'
import { BellRing, Check, Clock } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { Bullets, RabbitTile } from '@/components/connect/ConnectSheet'
import { haptic } from '@/lib/haptics'
import { wantApp, type SoonApp, type SoonId } from '@/lib/connections'

const MONO: Record<SoonId, string> = { whoop: 'W', apple: 'AW', coros: 'C' }

/** Plain monogram tile (no brand logos), matching AppTile. */
export function SoonTile({ app, size = 44 }: { app: SoonId; size?: number }) {
  const m = MONO[app]
  return (
    <span className="flex shrink-0 items-center justify-center rounded-[22%] bg-(--bg-inset) font-semibold tracking-tight text-(--text-secondary) ring-1 ring-(--border)"
      style={{ width: size, height: size, fontSize: size * (m.length > 1 ? 0.36 : 0.46) }} aria-hidden>
      {m}
    </span>
  )
}

export function SoonSheet({ app, onClose, onChanged }: {
  app: SoonApp
  onClose: () => void
  /** after a vote: the new state (and the owner's count, when returned) */
  onChanged: (next: SoonApp) => void
}) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [cur, setCur] = useState(app)

  async function toggle() {
    setBusy(true); setErr(null)
    try {
      const r = await wantApp(cur.id, !cur.wanted)
      const next = { ...cur, wanted: r.wanted, ...(r.wanted_by != null ? { wanted_by: r.wanted_by } : {}) }
      setCur(next); onChanged(next)
      if (r.wanted) haptic()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <Sheet title={cur.name} onClose={onClose} bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <div className="flex items-center justify-center gap-3 py-1" aria-hidden>
        <RabbitTile />
        <span className="conn-dots flex items-center gap-1"><span /><span /><span /></span>
        <SoonTile app={cur.id} size={56} />
      </div>
      <div className="text-center">
        <p className="font-display text-[1.2941rem] leading-tight text-(--brand)">Rabbit + {cur.name}</p>
        <p className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-(--bg-inset) px-2.5 py-0.5 text-[0.7059rem] font-medium text-(--text-secondary)">
          <Clock className="size-3" aria-hidden /> Coming soon
        </p>
      </div>
      <section className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
        <p className="text-[0.8235rem] font-semibold text-(--text)">What Rabbit would use</p>
        <Bullets items={cur.would_use} tone="yes" />
      </section>
      <section className="flex flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
        <p className="text-[0.8235rem] font-semibold text-(--text)">Why it’s not here yet</p>
        <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">{cur.why}</p>
        <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
          Tell us you want it: the more people ask, the sooner we build it. Workouts would still count once, even if Garmin records them too.
        </p>
      </section>
      <div aria-live="polite" className="flex flex-col gap-2">
        {cur.wanted ? (
          <p className="flex items-center justify-center gap-2 text-[0.8235rem] font-medium text-(--accent)">
            <Check className="size-4" aria-hidden /> You asked for {cur.name}. We’ll let you know when it’s ready.
          </p>
        ) : null}
        {cur.wanted_by != null && (
          <p className="text-center text-[0.7059rem] text-(--text-muted)">
            {cur.wanted_by === 1 ? '1 person wants this' : `${cur.wanted_by} people want this`} (only you see this count)
          </p>
        )}
        {err && <p role="alert" className="text-center text-[0.7647rem] text-(--danger)">{err}</p>}
      </div>
      <Button variant={cur.wanted ? 'default' : 'primary'} className="h-11 w-full gap-1.5 text-[0.8235rem]" loading={busy}
        aria-pressed={cur.wanted} onClick={() => void toggle()}>
        {cur.wanted ? 'I don’t need this anymore' : <><BellRing className="size-4" aria-hidden />I want this</>}
      </Button>
    </Sheet>
  )
}
