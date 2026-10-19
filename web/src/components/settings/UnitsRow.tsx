// Settings > Units: Miles (default) or Kilometers. Saves athlete.units; every screen, Rabbit's
// replies, briefs and calendar feeds follow it (miles also means yards for swims and °F).
import { useState } from 'react'
import { Group } from '@/components/settings/Grouped'
import { putAthlete, type Me } from '@/lib/api'
import { isImperial } from '@/lib/plan'
import { haptic } from '@/lib/haptics'
import { cn } from '@/lib/utils'

const OPTIONS = [['imperial', 'Miles', 'mi · yd · °F'], ['metric', 'Kilometers', 'km · m · °C']] as const

export function UnitsGroup({ me, onChange }: { me: Me; onChange: () => void }) {
  const [units, setUnits] = useState<'imperial' | 'metric'>(isImperial(me.athlete.units) ? 'imperial' : 'metric')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function pick(v: 'imperial' | 'metric') {
    if (v === units || busy) return
    const was = units
    setUnits(v); setBusy(true); setErr(null); haptic()
    try { await putAthlete({ units: v } as Parameters<typeof putAthlete>[0]); onChange() }
    catch (e) { setUnits(was); setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Group label="Units" footer={err ?? 'Distances, paces and weather everywhere in rabbt, including its replies.'}>
      <div role="radiogroup" aria-label="Units" className="grid grid-cols-2 gap-1 rounded-xl bg-(--bg-inset) p-1 m-3">
        {OPTIONS.map(([v, name, hint]) => (
          <button key={v} type="button" role="radio" aria-checked={units === v} disabled={busy}
            onClick={() => void pick(v)}
            className={cn('flex min-h-11 flex-col items-center justify-center rounded-lg px-2 py-1 transition-colors',
              units === v ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-secondary)')}>
            <span className="text-body font-medium">{name}</span>
            <span className="text-caption text-(--text-muted)">{hint}</span>
          </button>
        ))}
      </div>
    </Group>
  )
}
