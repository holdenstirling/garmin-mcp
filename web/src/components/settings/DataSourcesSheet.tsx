// "How should Rabbit use your data?": asked once after Oura connects (and once for athletes
// who connected Oura before this existed), and from Settings -> Data sources. Workouts are
// always Garmin's; the athlete picks where recovery and sleep come from.
import { useRef, useState } from 'react'
import { Check, X } from 'lucide-react'
import { putSettings, type Me } from '@/lib/api'
import { defaultSources, type DataSource } from '@/lib/sources'
import { Switch } from '@/components/settings/Grouped'
import { cn } from '@/lib/utils'
import { useDialog } from '@/hooks/useDialog'

const CHOICES: { id: DataSource; title: string; sub: string }[] = [
  { id: 'oura', title: 'Oura', sub: 'Recommended if you wear it nightly' },
  { id: 'garmin', title: 'Garmin', sub: 'Training readiness and sleep from your watch' },
]

export function DataSourcesSheet({ me, onClose, onSaved }: {
  me: Me
  onClose: () => void
  /** after saving: a toast message for the caller to show */
  onSaved: (msg: string) => void
}) {
  const ouraOn = me.oura.connected
  const cur = me.settings.data_sources ?? defaultSources(ouraOn)
  const [recovery, setRecovery] = useState<DataSource>(ouraOn ? cur.recovery : 'garmin')
  const [both, setBoth] = useState(ouraOn && cur.show_both)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function save() {
    setBusy(true); setErr(null)
    try {
      await putSettings({ data_sources: { recovery, sleep: recovery, show_both: ouraOn && both }, data_sources_asked: true })
      onSaved(`Recovery and sleep from ${recovery === 'oura' ? 'Oura' : 'Garmin'}`)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  // Closing without saving keeps the defaults and doesn't ask again.
  async function dismiss() {
    if (busy) return
    if (!me.settings.data_sources_asked) {
      setBusy(true)
      await putSettings({ data_sources_asked: true }).catch(() => {})
    }
    onClose()
  }
  const box = useRef<HTMLDivElement>(null)
  useDialog(box, () => void dismiss())

  return (
    <div className="modal-overlay" onClick={() => void dismiss()}>
      <div ref={box} className="modal" role="dialog" aria-modal="true" aria-labelledby="ds-title" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 id="ds-title" className="modal-title">How should Rabbit use your data?</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={() => void dismiss()}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">
            Workouts come from Garmin only. Oura workouts are never added, so nothing is counted twice.
          </p>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1.5 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
              Recovery &amp; sleep from
            </legend>
            {CHOICES.map((c) => {
              const disabled = c.id === 'oura' && !ouraOn
              const on = recovery === c.id
              return (
                <label key={c.id}
                  className={cn('flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 transition-colors',
                    on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)',
                    disabled && 'cursor-not-allowed opacity-50')}>
                  <input type="radio" name="ds-recovery" value={c.id} checked={on} disabled={disabled}
                    onChange={() => setRecovery(c.id)} className="sr-only" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[0.9412rem] text-(--text)">{c.title}</span>
                    <span className="block text-[0.7647rem] text-(--text-muted)">{disabled ? 'Connect Oura in Settings to use it' : c.sub}</span>
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
              <Switch label="Show both in Progress" checked={both} onChange={setBoth} />
            </div>
          )}

          <p className="text-[0.7059rem] leading-snug text-(--text-muted)">
            Rabbit's AI never sees Oura numbers; it only knows which one you read, so it won't quote a score that disagrees.
          </p>
          {err && <p role="alert" className="text-[0.7647rem] text-(--danger)">{err}</p>}
          <button type="button" disabled={busy} onClick={() => void save()}
            className="min-h-11 rounded-xl bg-(--accent) px-4 text-[0.9412rem] font-medium text-(--on-fill) disabled:opacity-50">
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
