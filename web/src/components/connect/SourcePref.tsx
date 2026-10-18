// "Recovery & sleep from Garmin or Oura?" (sources.py): asked in the Oura popup right after
// connecting and kept there (and in Garmin's) while both are connected. Workouts always come
// from Garmin; Oura workouts Garmin missed are shown only (workouts.py), so nothing counts twice.
import { useState } from 'react'
import { Check } from 'lucide-react'
import { putSettings, type Me } from '@/lib/api'
import { defaultSources, type DataSource } from '@/lib/sources'
import { Switch } from '@/components/settings/Grouped'
import { cn } from '@/lib/utils'

const CHOICES: { id: DataSource; title: string; sub: string }[] = [
  { id: 'oura', title: 'Oura', sub: 'Recommended if you wear it nightly' },
  { id: 'garmin', title: 'Garmin', sub: 'Training readiness and sleep from your watch' },
]

export function useSourcePref(me: Me, ouraOn: boolean) {
  const cur = me.settings.data_sources ?? defaultSources(ouraOn)
  const [recovery, setRecovery] = useState<DataSource>(ouraOn ? cur.recovery : 'garmin')
  const [both, setBoth] = useState(ouraOn && cur.show_both)
  const dirty = recovery !== cur.recovery || both !== cur.show_both || !me.settings.data_sources_asked
  /** Save (also marks the question answered). Returns the toast line. */
  const save = async () => {
    await putSettings({ data_sources: { recovery, sleep: recovery, show_both: ouraOn && both }, data_sources_asked: true })
    return `Recovery and sleep from ${recovery === 'oura' ? 'Oura' : 'Garmin'}`
  }
  return { recovery, setRecovery, both, setBoth, dirty, save }
}

export function SourcePref({ pref, ouraOn }: { pref: ReturnType<typeof useSourcePref>; ouraOn: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1.5 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
          Recovery &amp; sleep from
        </legend>
        {CHOICES.map((c) => {
          const disabled = c.id === 'oura' && !ouraOn
          const on = pref.recovery === c.id
          return (
            <label key={c.id}
              className={cn('flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 transition-colors',
                on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)',
                disabled && 'cursor-not-allowed opacity-50')}>
              <input type="radio" name="ds-recovery" value={c.id} checked={on} disabled={disabled}
                onChange={() => pref.setRecovery(c.id)} className="sr-only" />
              <span className="min-w-0 flex-1">
                <span className="block text-[0.9412rem] text-(--text)">{c.title}</span>
                <span className="block text-[0.7647rem] text-(--text-muted)">{disabled ? 'Connect Oura to use it' : c.sub}</span>
              </span>
              <span aria-hidden="true"
                className={cn('flex size-5 shrink-0 items-center justify-center rounded-full border',
                  on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')}>
                {on && <Check className="size-3" />}
              </span>
            </label>
          )
        })}
      </fieldset>
      {ouraOn && (
        <div className="flex min-h-11 items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-2">
          <span className="min-w-0 flex-1">
            <span className="block text-[0.9412rem] text-(--text)">Show both in Progress</span>
            <span className="block text-[0.7647rem] text-(--text-muted)">Garmin and Oura side by side. Rabbit still plans from one.</span>
          </span>
          <Switch label="Show both in Progress" checked={pref.both} onChange={pref.setBoth} />
        </div>
      )}
      <p className="px-1 text-[0.7059rem] leading-snug text-(--text-muted)">
        Stats and plan matching count Garmin workouts; Oura workouts Garmin missed only show on their day. Rabbit's coaching never uses Oura numbers; it only knows which one you read, so it won't quote a score that disagrees.
      </p>
    </div>
  )
}
