// Apple Watch, set up with the athlete's own iPhone Shortcut (server: applehealth.py). Apple
// Health has no web API, so the connect popup is a guide instead of a sign-in:
//   intro   what Rabbit gets and never gets, "Set it up"
//   steps   1. copy your Rabbit link and import key (shown this once), 2. build the Shortcut,
//           3. run it automatically, 4. run it once: "Check for workouts" waits for the first import
//   done    "You're all set" once a first import arrived
//   manage  last import, the steps again, a new key, turn off (optionally deleting imported workouts)
// Same look as the other connect popups (ConnectSheet: tiles, Bullets, StateChip).
import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, Eye, EyeOff, KeyRound, Lock, RefreshCw, ShieldCheck, Smartphone, TriangleAlert, Watch } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { RabbitNap } from '@/components/anim'
import { AppTile, Bullets, RabbitTile, StateChip } from '@/components/connect/ConnectSheet'
import {
  TEXT_TEMPLATE, copyText, disconnectAppleHealth, getAppleHealth, importLine, newAppleKey, type AppleHealth,
} from '@/lib/applehealth'
import { connectionsChanged, getConnections, type Connection } from '@/lib/connections'
import { cn } from '@/lib/utils'

type View = 'loading' | 'intro' | 'steps' | 'done' | 'manage'

const NEXT = [
  'Each time you finish a workout on your Apple Watch, your Shortcut sends it to rabbt',
  'It shows on its day in your plan, marked “via Apple Watch”',
  'If you share workouts with friends, it goes in their feed too',
]

/** A labelled value with a Copy button. `secret` masks it until Show. */
function CopyField({ label, value, secret, onToast }: { label: string; value: string; secret?: boolean; onToast: (m: string) => void }) {
  const [shown, setShown] = useState(!secret)
  const [done, setDone] = useState(false)
  const t = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(t.current), [])
  async function copy() {
    const ok = await copyText(value)
    if (!ok) { onToast('Couldn’t copy. Press and hold the text to copy it.'); setShown(true); return }
    setDone(true); window.clearTimeout(t.current); t.current = window.setTimeout(() => setDone(false), 1800)
  }
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{label}</span>
      <div className="flex items-center gap-1.5 rounded-xl border border-(--border) bg-(--bg-inset) py-1 pl-3 pr-1">
        <code className="min-w-0 flex-1 select-all break-all font-mono text-[0.7059rem] leading-snug text-(--text)">
          {shown ? value : `${value.slice(0, 6)}${'•'.repeat(14)}`}
        </code>
        {secret && (
          <button type="button" className="flex size-11 shrink-0 items-center justify-center rounded-lg text-(--text-muted) active:bg-(--bg-surface)"
            aria-label={shown ? `Hide ${label}` : `Show ${label}`} onClick={() => setShown((s) => !s)}>
            {shown ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
          </button>
        )}
        <button type="button" onClick={() => void copy()} aria-label={`Copy ${label}`}
          className={cn('flex h-11 shrink-0 items-center gap-1 rounded-lg px-3 text-[0.7647rem] font-semibold active:opacity-80',
            done ? 'text-(--accent)' : 'bg-(--accent) text-(--on-fill)')}>
          {done ? <><Check className="size-3.5" aria-hidden />Copied</> : <><Copy className="size-3.5" aria-hidden />Copy</>}
        </button>
      </div>
    </div>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="flex gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5" aria-label={`Step ${n}: ${title}`}>
      <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-full bg-(--accent) font-mono text-[0.7647rem] font-semibold text-(--on-fill)">{n}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <h3 className="text-[0.8235rem] font-semibold leading-snug text-(--text)">{title}</h3>
        {children}
      </div>
    </section>
  )
}

/** Shortcuts action names in the app's own words, so they're easy to find with its search. */
function Act({ children }: { children: React.ReactNode }) {
  return <b className="font-semibold text-(--text)">“{children}”</b>
}

function Ol({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="flex list-none flex-col gap-1.5 p-0">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2 text-[0.7647rem] leading-snug text-(--text-secondary)">
          <span aria-hidden className="w-4 shrink-0 text-right font-mono text-(--text-muted)">{String.fromCharCode(97 + i)}.</span>
          <span className="min-w-0">{it}</span>
        </li>
      ))}
    </ol>
  )
}

export function ConnectAppleHealth({ onClose, onChanged, onToast }: {
  onClose: () => void
  onChanged: () => void
  onToast: (msg: string) => void
}) {
  const [h, setH] = useState<AppleHealth | null>(null)
  const [conn, setConn] = useState<Connection | null>(null)
  const [view, setView] = useState<View>('loading')
  const [key, setKey] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [remove, setRemove] = useState(false)
  const live = useRef(true)
  useEffect(() => () => { live.current = false }, [])

  const load = useCallback(async () => {
    try {
      const [v, c] = await Promise.all([getAppleHealth(), getConnections().catch(() => null)])
      if (!live.current) return v
      setH(v); setErr(null)
      if (c) setConn(c.apps.find((a) => a.id === 'apple') ?? null)
      setView((cur) => cur === 'loading' ? (v.on ? 'manage' : 'intro') : cur)
      return v
    } catch (e) {
      if (live.current) { setErr((e as Error).message); setView((cur) => cur === 'loading' ? 'intro' : cur) }
      return null
    }
  }, [])
  useEffect(() => { void load() }, [load])

  const changed = () => { onChanged(); connectionsChanged() }

  async function makeKey(thenSteps: boolean) {
    setBusy(true); setErr(null)
    try {
      const r = await newAppleKey()
      setKey(r.key); setH(r)
      changed()
      if (thenSteps) setView('steps')
      else onToast('New key made. Paste it into your Shortcut; the old one stopped working.')
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  // "Check for workouts": look for the first import for up to ~30 s.
  async function check() {
    setChecking(true)
    const before = h?.last_import ?? null
    for (let i = 0; i < 6 && live.current; i++) {
      const v = await load()
      if (v?.last_import && v.last_import !== before) {
        setChecking(false)
        if (view === 'steps') setView('done')
        else onToast(`rabbt has ${v.workouts} Apple Watch workout${v.workouts === 1 ? '' : 's'}`)
        changed()
        return
      }
      await new Promise((r) => window.setTimeout(r, 5000))
    }
    if (live.current) {
      setChecking(false)
      onToast('Nothing yet. Run the Shortcut on your iPhone, then check again.')
    }
  }

  async function turnOff() {
    setBusy(true)
    try {
      const v = await disconnectAppleHealth(remove)
      setH(v); setKey(null); setConfirm(false)
      onToast(remove ? 'Apple Watch turned off and its workouts deleted' : 'Apple Watch turned off')
      changed()
      setView('intro')
    } catch (e) { onToast((e as Error).message) } finally { setBusy(false) }
  }

  const reads = conn?.reads ?? []
  const never = conn?.never ?? []
  const title = view === 'manage' ? 'Apple Watch' : view === 'done' ? 'Apple Watch connected' : 'Connect Apple Watch'

  let body: React.ReactNode
  if (view === 'loading') {
    body = <div className="flex justify-center py-8"><RabbitLoader label="Checking Apple Watch…" /></div>
  } else if (view === 'intro') {
    body = (
      <>
        <div className="flex items-center justify-center gap-3 py-1" aria-hidden>
          <RabbitTile />
          <span className="conn-dots flex items-center gap-1"><span /><span /><span /></span>
          <AppTile app="apple" size={56} />
        </div>
        <div className="text-center">
          <p className="font-display text-[1.1765rem] leading-tight text-(--brand)">rabbt + Apple Watch</p>
          <p className="mt-1 text-[0.8235rem] leading-snug text-(--text-secondary)">
            Apple Watch workouts live in the Health app on your iPhone. A Shortcut you set up once sends them to rabbt after each workout.
          </p>
        </div>
        {err && <p role="alert" className="text-[0.7647rem] text-(--danger)">{err}</p>}
        {reads.length > 0 && (
          <section aria-labelledby="ah-reads" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
            <h3 id="ah-reads" className="text-[0.7647rem] font-semibold text-(--text)">rabbt will get</h3>
            <Bullets items={reads} tone="yes" />
          </section>
        )}
        {never.length > 0 && (
          <section aria-labelledby="ah-never" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
            <h3 id="ah-never" className="flex items-center gap-1.5 text-[0.7647rem] font-semibold text-(--text)">
              <ShieldCheck className="size-4 text-(--accent)" aria-hidden />Your privacy
            </h3>
            <Bullets items={never} tone="no" />
            <p className="flex items-start gap-2 border-t border-(--border) pt-2 text-[0.7059rem] leading-snug text-(--text-muted)">
              <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              Your Shortcut uses a personal import key. rabbt stores only a scrambled copy of it, and the key can only add workouts, never read anything. Turn it off anytime.
            </p>
          </section>
        )}
        {h && !h.available ? (
          <p className="rounded-xl bg-(--bg-inset) px-3.5 py-3 text-center text-[0.7647rem] text-(--text-secondary)">
            Apple Watch import isn’t available on this server yet.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="flex items-start gap-2 text-[0.7059rem] leading-snug text-(--text-muted)">
              <Smartphone className="mt-0.5 size-3.5 shrink-0 text-(--accent)" aria-hidden />
              Takes about 5 minutes on your iPhone, in the Shortcuts app. Easiest if you open rabbt on the same iPhone so you can copy and paste.
            </p>
            <Button variant="primary" className="h-12 w-full text-[0.8824rem]" loading={busy} onClick={() => void makeKey(true)}>Set it up</Button>
            <button type="button" className="min-h-11 text-[0.7647rem] text-(--text-muted)" onClick={onClose}>Not now</button>
          </div>
        )}
      </>
    )
  } else if (view === 'steps') {
    const endpoint = h?.endpoint ?? ''
    body = (
      <>
        <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">
          Do these on your iPhone, in the <b className="text-(--text)">Shortcuts</b> app. You only do this once.
        </p>
        <Step n={1} title="Copy your rabbt link and import key">
          <CopyField label="rabbt link" value={endpoint} onToast={onToast} />
          {key ? (
            <>
              <CopyField label="Import key" value={key} secret onToast={onToast} />
              <p className="flex items-start gap-1.5 text-[0.7059rem] leading-snug text-(--warning-text)">
                <KeyRound className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                This key shows only now. Keep it private: anyone with it can add workouts to your rabbt.
              </p>
            </>
          ) : (
            <div className="flex flex-col gap-2 rounded-xl bg-(--bg-inset) px-3 py-2.5">
              <p className="text-[0.7059rem] leading-snug text-(--text-secondary)">
                Your key is hidden for safety. Need it again? Make a new one (the old one stops working, so update your Shortcut).
              </p>
              <Button className="h-11 text-[0.7647rem]" loading={busy} onClick={() => void makeKey(false)}>Make a new key</Button>
            </div>
          )}
        </Step>
        <Step n={2} title="Build the Shortcut">
          <Ol items={[
            <>Open Shortcuts, tap <b className="text-(--text)">+</b> and name it <b className="text-(--text)">Send workouts to rabbt</b>.</>,
            <>Add <Act>Find Health Samples</Act>. Set the type to <b className="text-(--text)">Workouts</b>, add the filter <b className="text-(--text)">Start Date is in the last 7 days</b>, sort by Start Date, latest first, limit 50.</>,
            <>Add <Act>Repeat with Each</Act> and pick the Health Samples from the step above.</>,
            <>Inside the repeat, add <Act>Text</Act> and paste the template below. Then swap each ⟨…⟩ for the matching detail: tap <b className="text-(--text)">Repeat Item</b> and choose Workout Type, Start Date, End Date, Duration or Distance.</>,
            <>After <b className="text-(--text)">End Repeat</b>, add <Act>Combine Text</Act>: Repeat Results, with New Lines.</>,
            <>Add <Act>Get Contents of URL</Act> and paste your rabbt link. Tap the arrow for more: Method <b className="text-(--text)">POST</b>, add a header <b className="text-(--text)">Authorization</b> with the value <b className="text-(--text)">Bearer</b>, a space, then your key. Request Body: <b className="text-(--text)">File</b>, and pick Combined Text.</>,
            <>Optional: add <Act>Show Result</Act> to see rabbt’s reply while you test.</>,
          ]} />
          <CopyField label="Text template" value={TEXT_TEMPLATE} onToast={onToast} />
          <p className="text-[0.7059rem] leading-snug text-(--text-muted)">
            Only these five details are sent. Heart rate and calories aren’t, and rabbt would throw them away anyway.
          </p>
        </Step>
        <Step n={3} title="Make it run on its own">
          <Ol items={[
            <>In Shortcuts, open <b className="text-(--text)">Automation</b> and tap <b className="text-(--text)">+</b>.</>,
            <>Choose <Act>Apple Watch Workout</Act>, then <b className="text-(--text)">Ends</b> for any workout. Don’t see it? Use <Act>Time of Day</Act>, every evening.</>,
            <>Pick <b className="text-(--text)">Run Immediately</b>, then choose <b className="text-(--text)">Send workouts to rabbt</b>.</>,
          ]} />
          <p className="text-[0.7059rem] leading-snug text-(--text-muted)">
            Each run sends the last 7 days, so a missed run catches up next time. Nothing counts twice, and a workout Garmin also has counts once.
          </p>
        </Step>
        <Step n={4} title="Run it once">
          <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
            Tap your Shortcut to run it and allow Health access when your iPhone asks. Then come back here.
          </p>
          <Button variant="primary" className="h-11 w-full text-[0.8235rem]" loading={checking} onClick={() => void check()}>
            <RefreshCw className="mr-1.5 size-3.5" aria-hidden />Check for workouts
          </Button>
          {checking && <p role="status" className="text-center text-[0.7059rem] text-(--text-muted)">Waiting for your Shortcut…</p>}
        </Step>
        <button type="button" className="min-h-11 text-[0.7647rem] text-(--text-muted)" onClick={() => { void load(); setView('manage') }}>
          I’ll finish later
        </button>
      </>
    )
  } else if (view === 'done') {
    body = (
      <>
        <div className="flex flex-col items-center gap-2 py-3 text-center">
          <RabbitNap size={52} mode="cheer" />
          <p className="font-display text-[1.1765rem] leading-tight text-(--brand)">You’re all set</p>
          <p className="text-[0.7647rem] text-(--text-secondary)">
            {h ? `rabbt got ${h.last_received ?? 0} workout${h.last_received === 1 ? '' : 's'} from your Apple Watch.` : 'Apple Watch is connected to rabbt.'}
          </p>
        </div>
        <section aria-labelledby="ah-next" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
          <h3 id="ah-next" className="text-[0.7647rem] font-semibold text-(--text)">What happens now</h3>
          <Bullets items={NEXT} tone="yes" />
        </section>
        <Button variant="primary" className="h-11 w-full text-[0.8235rem]" onClick={onClose}>Done</Button>
      </>
    )
  } else {
    const waiting = !h?.last_import
    body = (
      <>
        <div className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
          <AppTile app="apple" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[0.9412rem] text-(--text)">Apple Watch</span>
            <span className="block text-[0.7059rem] text-(--text-muted)">{h ? importLine(h) : ''}</span>
          </span>
          <StateChip state={waiting ? 'attention' : 'connected'} />
        </div>
        {waiting && (
          <p className="flex items-start gap-2 rounded-xl bg-(--bg-inset) px-3.5 py-2.5 text-[0.7647rem] leading-snug text-(--text-secondary)">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-(--warning-text)" aria-hidden />
            rabbt hasn’t heard from your Shortcut yet. Finish the steps, then run it once.
          </p>
        )}
        <Button variant={waiting ? 'primary' : 'default'} className="h-11 w-full text-[0.8235rem]" onClick={() => setView('steps')}>
          <Watch className="mr-1.5 size-3.5" aria-hidden />{waiting ? 'Finish setting up' : 'See the setup steps'}
        </Button>
        <Button className="h-11 w-full text-[0.8235rem]" loading={checking} onClick={() => void check()}>
          <RefreshCw className="mr-1.5 size-3.5" aria-hidden />Check for new workouts
        </Button>
        {reads.length > 0 && (
          <details className="rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5">
            <summary className="flex min-h-11 cursor-pointer items-center gap-1.5 text-[0.7647rem] text-(--text-secondary)">
              <ShieldCheck className="size-4 text-(--accent)" aria-hidden />What rabbt uses, and your privacy
            </summary>
            <div className="flex flex-col gap-2 pb-1.5">
              <Bullets items={reads} tone="yes" />
              <Bullets items={never} tone="no" />
            </div>
          </details>
        )}
        {confirm ? (
          <div role="group" aria-label="Turn off Apple Watch?" className="flex flex-col gap-2.5 rounded-xl border border-(--danger) p-3.5">
            <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
              Turn off Apple Watch? Your import key stops working right away, so your Shortcut can’t send anything. You can delete the Shortcut on your iPhone too.
            </p>
            {(h?.workouts ?? 0) > 0 && (
              <label className="flex min-h-11 items-center gap-2.5 text-[0.7647rem] text-(--text)">
                <input type="checkbox" className="size-5 accent-(--danger)" checked={remove} onChange={(e) => setRemove(e.target.checked)} />
                Also delete the {h!.workouts} workout{h!.workouts === 1 ? '' : 's'} rabbt imported
              </label>
            )}
            <div className="flex gap-2">
              <Button className="h-11 flex-1" onClick={() => setConfirm(false)} disabled={busy}>Cancel</Button>
              <Button variant="destructive" className="h-11 flex-1" loading={busy} onClick={() => void turnOff()}>Turn off</Button>
            </div>
          </div>
        ) : (
          <button type="button" className="min-h-11 text-[0.8235rem] text-(--danger)" onClick={() => { setRemove(false); setConfirm(true) }}>
            Turn off Apple Watch
          </button>
        )}
      </>
    )
  }

  return (
    <Sheet title={title} onClose={onClose} dismissible={!busy} bodyClassName="gap-4">
      {body}
    </Sheet>
  )
}
