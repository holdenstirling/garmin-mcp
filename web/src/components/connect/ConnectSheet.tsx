// One connect popup per app, in the pattern other apps use (one bottom sheet, nothing opens on
// top of it):
//   1. "Connect <App> to Rabbit": app tile, what Rabbit reads, what it never does, Continue.
//   2. Garmin: email + password, then Garmin's code if it asks, as steps with a progress bar
//      (ConnectGarmin inside this sheet). Oura / Google Calendar: Continue goes to the provider;
//      on return (?oura= / ?calendar=) Chat.tsx reopens this popup with `result`.
//   3. Success: check mark, "Importing your last N weeks…" (RabbitLoader), then Done. Oura asks
//      where recovery & sleep should come from (sources.py) right here.
//   TrainingPeaks: paste-your-session steps (ConnectTrainingPeaks) inside this sheet, then the
//   source-of-truth choice (TPSourcePref) on success and when connected.
//   Connected: last sync, Sync now, the source choice, Disconnect (with a confirm).
// Status comes from GET /app/api/connections (connections.py), facts included.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeftRight, CalendarClock, Check, CircleDot, ClipboardList, RefreshCw, TriangleAlert, Watch } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { RabbitLogo } from '@/components/RabbitLogo'
import { ConnectGarmin, type GarminStep } from '@/components/ConnectGarmin'
import { Progress } from '@/components/plan/ui'
import { SourcePref, useSourcePref } from '@/components/connect/SourcePref'
import { ConnectTrainingPeaks, TPSourcePref } from '@/components/connect/ConnectTrainingPeaks'
import { disconnectTP, getTP, syncTP, tpChanged, type TPSource } from '@/lib/trainingpeaks'
import { postJSON, type Me } from '@/lib/api'
import { syncNow } from '@/lib/live'
import { getProgress } from '@/lib/progress'
import { disconnectOura, getOura } from '@/lib/oura'
import { disconnectCalendar, getCalendar } from '@/lib/calendar'
import {
  OAUTH_URL, STATE_LABEL, connectionsChanged, getConnections, syncConnection, syncedAgo,
  type ConnApp, type ConnState, type Connection, type ConnectRequest,
} from '@/lib/connections'
import { cn } from '@/lib/utils'

export const APP_ICON: Record<ConnApp, typeof Watch> = { garmin: Watch, oura: CircleDot, calendar: CalendarClock, trainingpeaks: ClipboardList }
const NAME: Record<ConnApp, string> = { garmin: 'Garmin Connect', oura: 'Oura', calendar: 'Google Calendar', trainingpeaks: 'TrainingPeaks' }
const SHORT: Record<ConnApp, string> = { garmin: 'Garmin', oura: 'Oura', calendar: 'Google Calendar', trainingpeaks: 'TrainingPeaks' }

type View = 'loading' | 'intro' | 'garmin' | 'tp' | 'redirect' | 'importing' | 'done' | 'failed' | 'manage'

/** Generic app tile (no brand logos). */
export function AppTile({ app, size = 44 }: { app: ConnApp; size?: number }) {
  const I = APP_ICON[app]
  return (
    <span className="flex shrink-0 items-center justify-center rounded-[12px] bg-(--accent-subtle) text-(--accent)"
      style={{ width: size, height: size }} aria-hidden>
      <I style={{ width: size * 0.5, height: size * 0.5 }} />
    </span>
  )
}

export function StateChip({ state }: { state: ConnState }) {
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.6471rem] font-medium',
      state === 'connected' ? 'bg-(--accent-subtle) text-(--accent)'
        : state === 'attention' ? 'bg-(--warning-subtle) text-(--warning-text)'
        : 'bg-(--bg-inset) text-(--text-muted)')}>
      <span aria-hidden className={cn('size-1.5 rounded-full',
        state === 'connected' ? 'bg-(--accent)' : state === 'attention' ? 'bg-(--warning-text)' : 'bg-(--text-muted)')} />
      {STATE_LABEL[state]}
    </span>
  )
}

function Bullets({ items, tone }: { items: string[]; tone: 'yes' | 'no' }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-2 text-[0.7647rem] leading-snug text-(--text-secondary)">
          <span aria-hidden className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full text-[0.6471rem]',
            tone === 'yes' ? 'bg-(--accent-subtle) text-(--accent)' : 'bg-(--bg-inset) text-(--text-muted)')}>
            {tone === 'yes' ? <Check className="size-2.5" /> : '–'}
          </span>
          <span>{t}</span>
        </li>
      ))}
    </ul>
  )
}

const GARMIN_STEPS: { id: GarminStep | 'import'; label: string }[] = [
  { id: 'signin', label: 'Sign in to Garmin' }, { id: 'code', label: 'Enter Garmin’s code' },
  { id: 'connecting', label: 'Connecting' }, { id: 'import', label: 'Importing' },
]

// What "importing" reads right after connecting: the same reads the app makes anyway (the
// first progress read back-fills XP from a year of workouts), so this only warms them.
async function runImport(app: ConnApp): Promise<void> {
  if (app === 'garmin') { await syncNow().catch(() => null); await getProgress() }
  else if (app === 'oura') await getOura(28)
  else if (app === 'trainingpeaks') { await syncTP(); tpChanged() }
  else await getCalendar(42)
}

export function ConnectSheet({ me, req, onClose, onChanged, onToast }: {
  me: Me
  req: ConnectRequest
  onClose: () => void
  /** something changed: refresh /me */
  onChanged: () => void
  onToast: (msg: string) => void
}) {
  const app = req.app
  const [conn, setConn] = useState<Connection | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [view, setView] = useState<View>(req.result === 'failed' ? 'failed' : req.result === 'connected' ? 'importing' : 'loading')
  const [gStep, setGStep] = useState<GarminStep>('signin')
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [importNote, setImportNote] = useState<string | null>(null)
  const ouraOn = me.oura.connected || (app === 'oura' && (conn?.connected ?? false))
  const pref = useSourcePref(me, ouraOn)
  const [tpSource, setTpSource] = useState<TPSource | null>(null)
  useEffect(() => {
    if (app !== 'trainingpeaks' || !(view === 'manage' || view === 'done')) return
    let off = false
    getTP().then((v) => { if (!off) setTpSource(v.source) }, () => {})
    return () => { off = true }
  }, [app, view])

  const live = useRef(true)
  useEffect(() => () => { live.current = false }, [])
  const load = useCallback(async () => {
    try {
      const r = await getConnections()
      const c = r.apps.find((a) => a.id === app) ?? null
      if (!live.current) return c
      setConn(c); setLoadErr(null)
      setView((v) => v === 'loading' ? (c?.connected ? 'manage' : 'intro') : v)
      return c
    } catch (e) {
      if (live.current) { setLoadErr((e as Error).message); setView((v) => v === 'loading' ? 'intro' : v) }
      return null
    }
  }, [app])
  useEffect(() => { void load() }, [load])

  // Step 3: import, then Done (at least a beat, so it reads as a step and not a flash).
  useEffect(() => {
    if (view !== 'importing') return
    let off = false
    const t0 = Date.now()
    void runImport(app).then(() => null, () => 'Rabbit will keep importing in the background.').then(async (note) => {
      const wait = 1200 - (Date.now() - t0)
      if (wait > 0) await new Promise((r) => window.setTimeout(r, wait))
      if (off) return
      setImportNote(note)
      setView('done')
      void load()
    })
    return () => { off = true }
  }, [view, app, load])

  const changed = () => { onChanged(); connectionsChanged() }
  const onGarminConnected = () => { changed(); setView('importing') }

  const cont = () => {
    if (app === 'garmin') { setView('garmin'); return }
    if (app === 'trainingpeaks') { setView('tp'); return }
    setView('redirect')
    window.location.href = OAUTH_URL[app]
  }

  async function syncNowFor() {
    setBusy(true)
    try {
      if (app === 'garmin') {
        const r = await syncNow()
        onToast(r.error ? r.error : r.new.length ? `Synced ${r.new.length} new workout${r.new.length === 1 ? '' : 's'}` : 'Up to date')
      } else {
        const r = await syncConnection(app)
        if (app === 'trainingpeaks') tpChanged()
        onToast(r.app.error ?? (r.app.connected ? `${SHORT[app]} synced` : `${SHORT[app]} needs connecting again`))
      }
      await load(); connectionsChanged()
    } catch (e) { onToast((e as Error).message) } finally { setBusy(false) }
  }

  async function disconnect() {
    setBusy(true)
    try {
      if (app === 'garmin') await postJSON('/api/garmin/disconnect')
      else if (app === 'oura') await disconnectOura()
      else if (app === 'trainingpeaks') { await disconnectTP(); tpChanged() }
      else await disconnectCalendar()
      onToast(`${SHORT[app]} disconnected`)
      setConfirm(false)
      changed()
      const c = await load()
      setView(c?.connected ? 'manage' : 'intro')
    } catch (e) { onToast((e as Error).message) } finally { setBusy(false) }
  }

  async function savePref(thenClose: boolean) {
    setBusy(true)
    try {
      onToast(await pref.save())
      onChanged()
      if (thenClose) onClose()
    } catch (e) { onToast((e as Error).message) } finally { setBusy(false) }
  }

  const available = conn ? conn.available || conn.connected : app === 'garmin' ? me.garmin.can_connect
    : app === 'oura' ? me.oura.available : app === 'calendar' ? me.calendar.available : false
  const reads = conn?.reads ?? []
  const never = conn?.never ?? []
  const title = view === 'manage' ? SHORT[app] : view === 'done' ? `${SHORT[app]} connected`
    : view === 'failed' ? `Couldn’t connect ${SHORT[app]}` : `Connect ${SHORT[app]} to Rabbit`
  const gIndex = view === 'importing' ? 3 : GARMIN_STEPS.findIndex((s) => s.id === gStep)

  let body: React.ReactNode
  if (view === 'loading') {
    body = <div className="flex justify-center py-8"><RabbitLoader label={`Checking ${SHORT[app]}…`} /></div>
  } else if (view === 'intro') {
    body = (
      <>
        <div className="flex items-center justify-center gap-3 py-2">
          <AppTile app={app} size={56} />
          <ArrowLeftRight className="size-5 text-(--text-muted)" aria-hidden />
          <span className="flex size-14 items-center justify-center rounded-[14px] bg-(--brand)" aria-hidden><RabbitLogo size={44} /></span>
        </div>
        <p className="text-center text-[0.8235rem] leading-snug text-(--text-secondary)">
          {app === 'garmin' ? 'Your workouts, streak, fitness and personal bests fill in on their own.'
            : app === 'oura' ? 'Your readiness and sleep show in Progress and help Rabbit ease your week after a rough night.'
            : app === 'trainingpeaks' ? 'Your coach’s TrainingPeaks workouts show on your Rabbit plan, or Rabbit’s plan goes to TrainingPeaks. You choose which one leads.'
            : 'Rabbit spots trips and busy days so your plan can work around them.'}
        </p>
        {loadErr && <p role="alert" className="text-[0.7647rem] text-(--danger)">{loadErr}</p>}
        {reads.length > 0 && (
          <section className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
            <h3 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Rabbit reads</h3>
            <Bullets items={reads} tone="yes" />
            <h3 className="mt-1.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Rabbit never</h3>
            <Bullets items={never} tone="no" />
          </section>
        )}
        {available ? (
          <Button variant="primary" className="h-11 w-full text-[0.8235rem]" onClick={cont}>Continue</Button>
        ) : (
          <p className="rounded-xl bg-(--bg-inset) px-3.5 py-3 text-[0.7647rem] text-(--text-secondary)">
            {SHORT[app]} isn’t set up on this server yet.
          </p>
        )}
        {(app === 'oura' || app === 'calendar') && available && (
          <p className="text-center text-[0.6471rem] text-(--text-muted)">You’ll sign in with {SHORT[app]} and come right back here.</p>
        )}
      </>
    )
  } else if (view === 'garmin') {
    body = (
      <>
        <div>
          <Progress step={Math.max(0, gIndex)} total={GARMIN_STEPS.length} />
          <p className="mt-2 text-center text-[0.7059rem] text-(--text-muted)">
            Step {Math.max(0, gIndex) + 1} of {GARMIN_STEPS.length} · {GARMIN_STEPS[Math.max(0, gIndex)]!.label}
          </p>
        </div>
        <ConnectGarmin cooldownUntil={me.garmin.cooldown_until} onConnected={onGarminConnected} onStep={setGStep} />
        {me.garmin.fake && (
          <p className="text-[0.6471rem] text-(--text-muted)">Fake Garmin (dev): try mfa@, wrong@, 429@ or cf@ emails; code 123456.</p>
        )}
      </>
    )
  } else if (view === 'tp') {
    body = <ConnectTrainingPeaks onConnected={() => { changed(); setView('importing') }} />
  } else if (view === 'redirect') {
    body = <div className="flex justify-center py-8"><RabbitLoader label={`Opening ${SHORT[app]}…`} /></div>
  } else if (view === 'importing') {
    body = (
      <>
        {app === 'garmin' && <Progress step={3} total={GARMIN_STEPS.length} />}
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          <RabbitLoader label={conn?.import_label ?? 'Importing…'} />
        </div>
      </>
    )
  } else if (view === 'done') {
    body = (
      <>
        <div className="flex flex-col items-center gap-2 py-3 text-center">
          <span className="flex size-14 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)" aria-hidden>
            <Check className="size-7" />
          </span>
          <p className="font-display text-[1.1765rem] leading-tight text-(--brand)">You’re all set</p>
          <p className="text-[0.7647rem] text-(--text-secondary)">{importNote ?? `${NAME[app]} is connected to Rabbit.`}</p>
        </div>
        {app === 'oura' && <SourcePref pref={pref} ouraOn />}
        {app === 'trainingpeaks' && tpSource && <TPSourcePref source={tpSource} onSaved={setTpSource} onToast={onToast} />}
        <Button variant="primary" className="h-11 w-full text-[0.8235rem]" loading={busy}
          onClick={() => void (app === 'oura' ? savePref(true) : onClose())}>Done</Button>
      </>
    )
  } else if (view === 'failed') {
    body = (
      <>
        <div className="flex flex-col items-center gap-2 py-3 text-center">
          <span className="flex size-14 items-center justify-center rounded-full bg-(--bg-inset) text-(--warning-text)" aria-hidden>
            <TriangleAlert className="size-7" />
          </span>
          <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">
            {SHORT[app]} didn’t finish connecting. Nothing was changed. You can try again now.
          </p>
        </div>
        <Button variant="primary" className="h-11 w-full text-[0.8235rem]" onClick={cont} disabled={!available}>Try again</Button>
      </>
    )
  } else {
    // Connected: status, sync, source choice, disconnect.
    const state = conn?.state ?? 'connected'
    const showPref = app === 'oura' || (app === 'garmin' && me.oura.connected)
    body = (
      <>
        <div className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
          <AppTile app={app} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[0.9412rem] text-(--text)">{NAME[app]}</span>
            <span className="block text-[0.7059rem] text-(--text-muted)">{syncedAgo(conn?.last_sync ?? null)}</span>
          </span>
          <StateChip state={state} />
        </div>
        {conn?.error && (
          <p role="alert" className="flex items-start gap-2 rounded-xl bg-(--bg-inset) px-3.5 py-2.5 text-[0.7647rem] text-(--warning-text)">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />{conn.error}
          </p>
        )}
        {state === 'attention' ? (
          <Button variant="primary" className="h-11 w-full text-[0.8235rem]" onClick={cont}>Reconnect {SHORT[app]}</Button>
        ) : (
          <Button className="h-11 w-full text-[0.8235rem]" loading={busy} onClick={() => void syncNowFor()}>
            <RefreshCw className="mr-1.5 size-3.5" aria-hidden />Sync now
          </Button>
        )}
        {app === 'trainingpeaks' && tpSource && state !== 'attention' && (
          <TPSourcePref source={tpSource} onSaved={(s) => { setTpSource(s); void load() }} onToast={onToast} />
        )}
        {showPref && (
          <>
            <SourcePref pref={pref} ouraOn={me.oura.connected} />
            {pref.dirty && (
              <Button variant="primary" className="h-11 w-full text-[0.8235rem]" loading={busy} onClick={() => void savePref(!!req.ask)}>
                Save
              </Button>
            )}
          </>
        )}
        {reads.length > 0 && (
          <details className="rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5">
            <summary className="flex min-h-11 cursor-pointer items-center text-[0.7647rem] text-(--text-secondary)">What Rabbit reads and never does</summary>
            <div className="flex flex-col gap-2 pb-1.5">
              <Bullets items={reads} tone="yes" />
              <Bullets items={never} tone="no" />
            </div>
          </details>
        )}
        {confirm ? (
          <div role="group" aria-label={`Disconnect ${SHORT[app]}?`} className="flex flex-col gap-2 rounded-xl border border-(--danger) p-3.5">
            <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
              Disconnect {SHORT[app]}? Rabbit stops reading from it and deletes the stored access. You can connect again anytime.
            </p>
            <div className="flex gap-2">
              <Button className="h-11 flex-1" onClick={() => setConfirm(false)} disabled={busy}>Cancel</Button>
              <Button variant="destructive" className="h-11 flex-1" loading={busy} onClick={() => void disconnect()}>Disconnect</Button>
            </div>
          </div>
        ) : (
          <button type="button" className="min-h-11 text-[0.8235rem] text-(--danger)" onClick={() => setConfirm(true)}>
            Disconnect {SHORT[app]}
          </button>
        )}
      </>
    )
  }

  return (
    <Sheet title={title} onClose={onClose} dismissible={!busy && view !== 'redirect'} bodyClassName="gap-4">
      {body}
    </Sheet>
  )
}
