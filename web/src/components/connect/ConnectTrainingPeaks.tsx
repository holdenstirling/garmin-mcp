// TrainingPeaks sign-in, as steps inside the connect popup (ConnectSheet). TrainingPeaks has
// no public API and its sign-in form uses a captcha, so Rabbit can't take a password: the
// athlete copies their Production_tpAuth session value from a signed-in browser and pastes it
// here once (server: tpsync.TPSync.connect; stored encrypted, never shown again).
// Also: TPSourcePref, the "which plan is the source of truth" choice.
import { useState } from 'react'
import { ExternalLink, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Progress } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  TP_SOURCE_HINT, TP_SOURCE_LABEL, connectTP, setTPSource, tpChanged, type TPSource,
} from '@/lib/trainingpeaks'

const STEPS = ['Sign in to TrainingPeaks', 'Copy your session value', 'Paste it here', 'Connecting'] as const

export function ConnectTrainingPeaks({ onConnected }: { onConnected: (name: string | null) => void }) {
  const [step, setStep] = useState(0)
  const [value, setValue] = useState('')
  const [err, setErr] = useState<string | null>(null)

  async function connect() {
    setErr(null); setStep(3)
    try {
      const r = await connectTP(value)
      setValue('')
      tpChanged()
      onConnected(r.name)
    } catch (e) {
      setErr((e as Error).message); setStep(2)
    }
  }

  return (
    <div className="flex flex-col gap-3.5">
      <div>
        <Progress step={step} total={STEPS.length} />
        <p className="mt-2 text-center text-small text-(--text-secondary)">Step {step + 1} of {STEPS.length} · {STEPS[step]}</p>
      </div>

      {step === 0 && (
        <>
          <p className="text-body leading-snug text-(--text-secondary)">
            On a computer, open TrainingPeaks and sign in as you normally do. Keep that tab open.
          </p>
          <a href="https://app.trainingpeaks.com" target="_blank" rel="noopener noreferrer"
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-(--border) text-body text-(--accent) active:bg-(--bg-inset)">
            Open TrainingPeaks <ExternalLink className="size-4" aria-hidden />
          </a>
          <Button variant="primary" className="h-11 w-full text-body" onClick={() => setStep(1)}>I’m signed in</Button>
        </>
      )}

      {step === 1 && (
        <>
          <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-small leading-snug text-(--text-secondary)">
            <li>In the TrainingPeaks tab, open developer tools (F12, or Cmd+Option+I on a Mac).</li>
            <li>Go to <b>Application</b> (Chrome, Edge) or <b>Storage</b> (Firefox, Safari), then <b>Cookies</b> → app.trainingpeaks.com.</li>
            <li>Find <b>Production_tpAuth</b> and copy its whole <b>Value</b> (a long line of letters and numbers).</li>
          </ol>
          <Button variant="primary" className="h-11 w-full text-body" onClick={() => setStep(2)}>I copied it</Button>
          <button type="button" className="min-h-11 text-small text-(--text-muted)" onClick={() => setStep(0)}>Back</button>
        </>
      )}

      {step === 2 && (
        <>
          <label className="flex flex-col gap-1.5">
            <span className="text-small text-(--text-secondary)">Production_tpAuth value</span>
            <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={3}
              autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
              className="w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-small text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="Paste the value here" aria-describedby="tp-paste-help" />
          </label>
          {err && <p role="alert" className="text-small text-(--danger)">{err}</p>}
          <Button variant="primary" className="h-11 w-full text-body" disabled={value.trim().length < 20} onClick={() => void connect()}>
            Connect TrainingPeaks
          </Button>
          <button type="button" className="min-h-11 text-small text-(--text-muted)" onClick={() => setStep(1)}>Back</button>
        </>
      )}

      {step === 3 && <div className="flex justify-center py-6"><RabbitLoader label="Checking with TrainingPeaks…" /></div>}

      <p id="tp-paste-help" className="flex items-start gap-2 rounded-xl bg-(--bg-inset) px-3.5 py-2.5 text-meta leading-snug text-(--text-secondary)">
        <Lock className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
        <span>
          Why not your password? TrainingPeaks has no public connection for apps and its sign-in uses a captcha,
          so rabbt can’t sign in for you. The value you paste lets rabbt see your calendar; it’s stored encrypted
          and never shown again. On a phone? Do this once on a computer. If you sign out of TrainingPeaks,
          rabbt asks you to reconnect.
        </span>
      </p>
    </div>
  )
}

/** Which plan wins when both have the same workout. Saves on tap. */
export function TPSourcePref({ source, onSaved, onToast }: {
  source: TPSource
  onSaved: (s: TPSource) => void
  onToast: (msg: string) => void
}) {
  const [busy, setBusy] = useState<TPSource | null>(null)
  async function pick(s: TPSource) {
    if (s === source || busy) return
    setBusy(s)
    try {
      await setTPSource(s)
      onSaved(s); tpChanged()
      onToast(s === 'rabbit' ? 'rabbt plan is the source. Your next 14 days are in TrainingPeaks.' : 'TrainingPeaks plan is the source')
    } catch (e) { onToast((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <fieldset role="radiogroup" aria-label="Source of truth" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
      <legend className="px-1 text-meta font-semibold text-(--text-secondary)">Source of truth</legend>
      {(['trainingpeaks', 'rabbit'] as const).map((s) => (
        <button key={s} type="button" role="radio" aria-checked={source === s} disabled={!!busy} onClick={() => void pick(s)}
          className={cn('flex min-h-11 flex-col items-start gap-0.5 rounded-lg border px-3 py-2 text-left',
            source === s ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) active:bg-(--bg-inset)')}>
          <span className={cn('text-body', source === s ? 'text-(--accent)' : 'text-(--text)')}>
            {TP_SOURCE_LABEL[s]}{busy === s ? '…' : ''}
          </span>
          <span className="text-small leading-snug text-(--text-secondary)">{TP_SOURCE_HINT[s]}</span>
        </button>
      ))}
    </fieldset>
  )
}
