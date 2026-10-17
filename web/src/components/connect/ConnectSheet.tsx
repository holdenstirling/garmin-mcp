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
// Trust copy (TRUST below) only states what the code does: Garmin's password is used for one
// sign-in and dropped (garminlogin.py), tokens and pasted sign-ins live in Fernet-encrypted
// files (tokens.py, appstore.py), Disconnect deletes them (garminlogin.disconnect,
// oura.disconnect, gcalendar.disconnect also revokes at Google, tpsync.disconnect), Oura and
// Google sign in on their own pages (OAuth), Calendar asks only for calendar.readonly.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, KeyRound, Lock, RefreshCw, ShieldCheck, TriangleAlert, X } from 'lucide-react'
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
import { disconnectWhoop } from '@/lib/whoop'
import { disconnectCalendar, getCalendar } from '@/lib/calendar'
import {
  OAUTH_URL, STATE_LABEL, connectionsChanged, getConnections, syncConnection, syncedAgo,
  type ConnApp, type ConnState, type Connection, type ConnectRequest,
} from '@/lib/connections'
import { cn } from '@/lib/utils'
import { RabbitNap } from '@/components/anim'

const NAME: Record<ConnApp, string> = { garmin: 'Garmin Connect', oura: 'Oura', whoop: 'WHOOP', calendar: 'Google Calendar', trainingpeaks: 'TrainingPeaks' }
const SHORT: Record<ConnApp, string> = { garmin: 'Garmin', oura: 'Oura', whoop: 'WHOOP', calendar: 'Google Calendar', trainingpeaks: 'TrainingPeaks' }
type View = 'loading' | 'intro' | 'garmin' | 'tp' | 'redirect' | 'importing' | 'done' | 'failed' | 'manage'

/** Text monograms on a plain tile: recognisable without anyone's logo artwork. */
const MONO: Record<ConnApp, string> = { garmin: 'G', oura: 'O', whoop: 'W', calendar: 'Cal', trainingpeaks: 'TP' }

/** What each app is for, in one line (Connected apps hub). */
export const PURPOSE: Record<ConnApp, string> = {
  garmin: 'Workouts, heart rate, sleep and readiness',
  oura: 'Readiness, sleep, HRV and workouts Garmin missed',
  whoop: 'Workouts Garmin missed, for your day and your friends’ feed',
  calendar: 'Trips and busy days, so your plan fits',
  trainingpeaks: 'Your coach’s planned workouts',
}

// How signing in works and how the access is kept, per app (see the header for where each fact
// comes from). `cta` is the one primary button.
const TRUST: Record<ConnApp, { how: string; kept: string; cta: string; icon: typeof Lock }> = {
  garmin: {
    how: 'Sign in with your Garmin account on the next screen. Rabbit passes your password to Garmin once to sign in and never stores it.',
    kept: 'Rabbit keeps only Garmin’s sign-in token, encrypted. Disconnect anytime and it’s deleted.',
    cta: 'Continue to Garmin', icon: Lock,
  },
  oura: {
    how: 'You’ll sign in on Oura’s own page and approve access there, then come right back. Rabbit never sees your Oura password.',
    kept: 'The access Oura gives Rabbit is stored encrypted. Disconnect anytime and it’s deleted.',
    cta: 'Continue to Oura', icon: ShieldCheck,
  },
  whoop: {
    how: 'You’ll sign in on WHOOP’s own page and approve access to your workouts, then come right back. Rabbit never sees your WHOOP password.',
    kept: 'The access WHOOP gives Rabbit is stored encrypted. Disconnect anytime: Rabbit deletes it and tells WHOOP to revoke it.',
    cta: 'Continue to WHOOP', icon: ShieldCheck,
  },
  calendar: {
    how: 'You’ll sign in on Google’s own page and approve read-only access, then come right back. Rabbit never sees your Google password.',
    kept: 'The access Google gives Rabbit is stored encrypted. Disconnect anytime: Rabbit deletes it and tells Google to revoke it.',
    cta: 'Continue with Google', icon: ShieldCheck,
  },
  trainingpeaks: {
    how: 'No password: you’ll copy a sign-in value from TrainingPeaks on a computer and paste it here.',
    kept: 'The pasted sign-in is stored encrypted and never shown again. Disconnect anytime and it’s deleted.',
    cta: 'Continue', icon: KeyRound,
  },
}

// "You're all set": what happens now, in plain words.
const NEXT: Record<ConnApp, string[]> = {
  garmin: ['Your recent workouts are coming in now', 'New workouts show up on their own after your watch syncs with Garmin', 'Send planned workouts to your watch from Plan'],
  oura: ['Readiness and sleep show in Progress', 'Rabbit can ease your week after a rough night', 'Workouts Oura records that Garmin didn’t show on their day'],
  whoop: ['Workouts WHOOP records that Garmin didn’t show on their day', 'If you share workouts, friends see them in their feed', 'Strain, heart rate and calories stay private'],
  calendar: ['Trips and busy days show next to your plan', 'Rabbit works your workouts around them'],
  trainingpeaks: ['Your TrainingPeaks workouts show on your plan', 'Choose below which plan leads'],
}

/** Plain tile with the app's monogram (no brand logos). */
export function AppTile({ app, size = 44 }: { app: ConnApp; size?: number }) {
  const m = MONO[app]
  return (
    <span className="flex shrink-0 items-center justify-center rounded-[22%] bg-(--text) font-semibold tracking-tight text-(--bg) shadow-sm"
      style={{ width: size, height: size, fontSize: size * (m.length > 2 ? 0.3 : m.length > 1 ? 0.36 : 0.46) }} aria-hidden>
      {m}
    </span>
  )
}

/** Rabbit's own tile, matching AppTile. */
export function RabbitTile({ size = 56 }: { size?: number }) {
  return (
    <span className="logo-tile flex shrink-0 items-center justify-center rounded-[22%] bg-(--brand) shadow-sm" style={{ width: size, height: size }} aria-hidden>
      <RabbitLogo size={size * 0.72} />
    </span>
  )
}

/** Rabbit ··· App: the two tiles with a calm "linking" pulse while something is happening. */
function Link({ app, busy }: { app: ConnApp; busy?: boolean }) {
  return (
    <div className="flex items-center justify-center gap-3 py-1" aria-hidden>
      <RabbitTile />
      <span className={cn('conn-dots flex items-center gap-1', busy && 'conn-dots--busy')}>
        <span /><span /><span />
      </span>
      <AppTile app={app} size={56} />
    </div>
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

export function Bullets({ items, tone }: { items: string[]; tone: 'yes' | 'no' }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((t) => (
        <li key={t} className="flex items-start gap-2 text-[0.7647rem] leading-snug text-(--text-secondary)">
          <span aria-hidden className={cn('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full text-[0.6471rem]',
            tone === 'yes' ? 'bg-(--accent-subtle) text-(--accent)' : 'bg-(--bg-inset) text-(--text-muted)')}>
            {tone === 'yes' ? <Check className="size-2.5" /> : <X className="size-2.5" />}
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
  else if (app === 'whoop') await syncConnection('whoop')
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
      else if (app === 'whoop') await disconnectWhoop()
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
    : app === 'oura' ? me.oura.available : app === 'whoop' ? !!me.whoop?.available : app === 'calendar' ? me.calendar.available : false
  const reads = conn?.reads ?? []
  const never = conn?.never ?? []
  const title = view === 'manage' ? SHORT[app] : view === 'done' ? `${SHORT[app]} connected`
    : view === 'failed' ? `Couldn’t connect ${SHORT[app]}` : `Connect ${SHORT[app]}`
  const gIndex = view === 'importing' ? 3 : GARMIN_STEPS.findIndex((s) => s.id === gStep)

  let body: React.ReactNode
  if (view === 'loading') {
    body = <div className="flex justify-center py-8"><RabbitLoader label={`Checking ${SHORT[app]}…`} /></div>
  } else if (view === 'intro') {
    const t = TRUST[app]
    const How = t.icon
    body = (
      <>
        <Link app={app} />
        <div className="text-center">
          <p className="font-display text-[1.1765rem] leading-tight text-(--brand)">Rabbit + {NAME[app]}</p>
          <p className="mt-1 text-[0.8235rem] leading-snug text-(--text-secondary)">
            {app === 'garmin' ? 'Your workouts, streak, fitness and personal bests fill in on their own.'
              : app === 'oura' ? 'Your readiness and sleep show in Progress and help Rabbit ease your week after a rough night.'
              : app === 'whoop' ? 'Workouts you record on WHOOP show on their day and, if you share workouts, in your friends’ feed.'
              : app === 'trainingpeaks' ? 'Your coach’s TrainingPeaks workouts show on your Rabbit plan, or Rabbit’s plan goes to TrainingPeaks. You choose which one leads.'
              : 'Rabbit spots trips and busy days so your plan can work around them.'}
          </p>
        </div>
        {loadErr && <p role="alert" className="text-[0.7647rem] text-(--danger)">{loadErr}</p>}
        {reads.length > 0 && (
          <section aria-labelledby="conn-reads" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
            <h3 id="conn-reads" className="text-[0.7647rem] font-semibold text-(--text)">Rabbit will be able to see</h3>
            <Bullets items={reads} tone="yes" />
          </section>
        )}
        {never.length > 0 && (
          <section aria-labelledby="conn-never" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
            <h3 id="conn-never" className="flex items-center gap-1.5 text-[0.7647rem] font-semibold text-(--text)">
              <ShieldCheck className="size-4 text-(--accent)" aria-hidden />Your privacy
            </h3>
            <Bullets items={never} tone="no" />
            <p className="flex items-start gap-2 border-t border-(--border) pt-2 text-[0.7059rem] leading-snug text-(--text-muted)">
              <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />{t.kept}
            </p>
          </section>
        )}
        {available ? (
          <div className="flex flex-col gap-2">
            <p className="flex items-start gap-2 text-[0.7059rem] leading-snug text-(--text-muted)">
              <How className="mt-0.5 size-3.5 shrink-0 text-(--accent)" aria-hidden />{t.how}
            </p>
            <Button variant="primary" className="h-12 w-full text-[0.8824rem]" onClick={cont}>{t.cta}</Button>
            <button type="button" className="min-h-11 text-[0.7647rem] text-(--text-muted)" onClick={onClose}>Not now</button>
          </div>
        ) : (
          <p className="rounded-xl bg-(--bg-inset) px-3.5 py-3 text-center text-[0.7647rem] text-(--text-secondary)">
            {me.owner ? `${SHORT[app]} isn’t set up on this server yet (it needs ${SHORT[app]} app credentials).`
              : `Connecting ${SHORT[app]} is coming soon.`}
          </p>
        )}
      </>
    )
  } else if (view === 'garmin') {
    body = (
      <>
        <Link app="garmin" busy={gStep === 'connecting'} />
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
    body = (
      <>
        <Link app="trainingpeaks" />
        <ConnectTrainingPeaks onConnected={() => { changed(); setView('importing') }} />
      </>
    )
  } else if (view === 'redirect') {
    body = (
      <div className="flex flex-col items-center gap-3 py-4 text-center" role="status">
        <Link app={app} busy />
        <p className="text-[0.8235rem] text-(--text-secondary)">Opening {app === 'calendar' ? 'Google' : SHORT[app]}’s sign-in page…</p>
      </div>
    )
  } else if (view === 'importing') {
    body = (
      <>
        <Link app={app} busy />
        {app === 'garmin' && <Progress step={3} total={GARMIN_STEPS.length} />}
        <div className="flex flex-col items-center gap-2 py-4 text-center">
          <RabbitLoader label={conn?.import_label ?? 'Importing…'} />
        </div>
      </>
    )
  } else if (view === 'done') {
    body = (
      <>
        <div className="flex flex-col items-center gap-2 py-3 text-center">
          <RabbitNap size={52} mode="cheer" />
          <p className="font-display text-[1.1765rem] leading-tight text-(--brand)">You’re all set</p>
          <p className="text-[0.7647rem] text-(--text-secondary)">{importNote ?? `${NAME[app]} is connected to Rabbit.`}</p>
        </div>
        <section aria-labelledby="conn-next" className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
          <h3 id="conn-next" className="text-[0.7647rem] font-semibold text-(--text)">What happens now</h3>
          <Bullets items={NEXT[app]} tone="yes" />
        </section>
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
            {SHORT[app]} didn’t finish connecting, so nothing was shared and nothing was changed. You can try again now.
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
        {conn?.note && !conn.error && (
          <div className="flex flex-col gap-2 rounded-xl bg-(--bg-inset) px-3.5 py-2.5">
            <p className="flex items-start gap-2 text-[0.7647rem] text-(--text-secondary)">
              <RefreshCw className="mt-0.5 size-3.5 shrink-0 text-(--accent)" aria-hidden />{conn.note}
            </p>
            {state === 'connected' && conn.kind === 'oauth' && (
              <Button variant="default" className="h-11 text-[0.7647rem]" onClick={cont}>Reconnect {SHORT[app]}</Button>
            )}
          </div>
        )}
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
            <summary className="flex min-h-11 cursor-pointer items-center gap-1.5 text-[0.7647rem] text-(--text-secondary)">
              <ShieldCheck className="size-4 text-(--accent)" aria-hidden />What Rabbit uses, and your privacy
            </summary>
            <div className="flex flex-col gap-2 pb-1.5">
              <Bullets items={reads} tone="yes" />
              <Bullets items={never} tone="no" />
              <p className="flex items-start gap-2 border-t border-(--border) pt-2 text-[0.7059rem] leading-snug text-(--text-muted)">
                <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />{TRUST[app].kept}
              </p>
            </div>
          </details>
        )}
        {confirm ? (
          <div role="group" aria-label={`Disconnect ${SHORT[app]}?`} className="flex flex-col gap-2 rounded-xl border border-(--danger) p-3.5">
            <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
              Disconnect {SHORT[app]}? Rabbit stops reading from it and deletes its stored access{app === 'calendar' ? ' (and asks Google to revoke it)' : ''}. What’s already in Rabbit stays. You can connect again anytime.
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
