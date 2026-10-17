import { useCallback, useEffect, useRef, useState } from 'react'
import { AuthError, getMe, signOut, type Me } from './lib/api'
import { CoachApp } from './screens/lazyScreens'
import { isIOS, isStandalone } from './lib/push'
import { Chat } from './screens/Chat'
import { InstallPrompt } from './screens/InstallPrompt'
import { SignIn } from './screens/SignIn'
import { JoinScreen } from './screens/JoinScreen'
import { RabbitLogo } from './components/RabbitLogo'
import { RabbitLoader } from './components/RabbitLoader'
import { FxHost } from './components/fx/CarrotBurst'
import { SessionLost } from './components/ui/SessionLost'
import { OutboxPill, ResumeNote } from './components/ui/SaveSafety'
import { UpdatePill } from './components/ui/UpdatePill'
import { setDraftUser } from './lib/drafts'
import { startOutbox } from './lib/outbox'
import { hideSplash } from './lib/splash'
import { consentOf } from './lib/legal'
import { ConsentScreen } from './components/legal/ConsentScreen'

const BOOT_MESSAGES = ['Lacing up…', 'Warming up…', 'Checking your watch…', 'Crunching the numbers…']

type State =
  | { kind: 'loading' }
  | { kind: 'install' }
  | { kind: 'signin'; error: string | null }
  | { kind: 'home'; me: Me }
  | { kind: 'error'; message: string }

// /app/join/<token>: invite link (passkey sign-up), shown before the iOS install prompt.
const JOIN_TOKEN = /^\/app\/join\/([A-Za-z0-9_-]{20,100})\/?$/.exec(window.location.pathname)?.[1] ?? null

export function App() {
  useEffect(() => { if (JOIN_TOKEN) hideSplash() }, [])  // the join page has no loading step
  if (JOIN_TOKEN) return <div className="app-shell"><JoinScreen token={JOIN_TOKEN} /><FxHost /></div>
  return <MainApp />
}

function MainApp() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [skipInstall, setSkipInstall] = useState(false)
  // Only the newest /api/me request may update state (refreshes can overlap).
  const reqId = useRef(0)
  // Once the app is showing, a failed refresh keeps the current UI instead of the error screen.
  const shown = useRef(false)
  // The session ran out mid-use: sign in again over the current screen (nothing typed is lost).
  const [authLost, setAuthLost] = useState(false)
  useEffect(() => {
    const on = () => { if (shown.current) setAuthLost(true) }
    window.addEventListener('rabbit:auth-lost', on)
    return () => window.removeEventListener('rabbit:auth-lost', on)
  }, [])

  const load = useCallback(async () => {
    const params = new URLSearchParams(window.location.search)
    const authError = params.get('auth_error')
    if (authError) window.history.replaceState(null, '', '/app/')
    // Push on iOS only works from the installed (Home Screen) app, and the installed
    // app keeps its own cookies, so sign-in has to happen there too.
    if (isIOS() && !isStandalone() && !skipInstall) {
      setState({ kind: 'install' })
      return
    }
    const id = ++reqId.current
    try {
      const me = await getMe()
      if (id !== reqId.current) return
      // The Google sign-in window opened by SessionLost: done, hand back to the app.
      if (window.name === 'rabbit-signin' && window.opener) { window.name = ''; window.close() }
      setDraftUser(me.user_id) // lib/drafts: per-user form drafts
      startOutbox()            // lib/outbox: retry saves that didn't go through
      shown.current = true
      setState({ kind: 'home', me })
    } catch (e) {
      if (id !== reqId.current) return
      if (e instanceof AuthError) { shown.current = false; setState({ kind: 'signin', error: authError }) }
      else if (!shown.current) setState({ kind: 'error', message: (e as Error).message })
    }
  }, [skipInstall])

  useEffect(() => { void load() }, [load])
  useEffect(() => { if (state.kind !== 'loading') hideSplash() }, [state.kind])

  return (
    <div className="app-shell">
      {state.kind === 'loading' && (
        <div className="flex flex-1 items-center justify-center"><RabbitLoader size={64} cycle={BOOT_MESSAGES} /></div>
      )}
      {state.kind === 'install' && <InstallPrompt onSkip={() => setSkipInstall(true)} />}
      {state.kind === 'signin' && <SignIn error={state.error} />}
      {state.kind === 'home' && consentOf(state.me)?.needed && (
        <ConsentScreen consent={consentOf(state.me)!} onDone={() => void load()} onSignOut={() => void signOut().finally(load)} />
      )}
      {state.kind === 'home' && !consentOf(state.me)?.needed && (state.me.role === 'coach'
        ? <CoachApp me={state.me} onSignOut={() => void signOut().finally(load)} />
        : <Chat me={state.me} onChange={load} />)}
      {state.kind === 'home' && <><OutboxPill /><ResumeNote userId={state.me.user_id} /></>}
      {state.kind === 'home' && authLost && (
        <SessionLost userId={state.me.user_id} onBack={() => { setAuthLost(false); startOutbox() }} />
      )}
      {state.kind === 'error' && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <RabbitLogo size={40} />
          <p className="text-(--text-secondary)">Rabbit tripped over something: {state.message}</p>
          <button className="hit-44 underline" onClick={() => void load()}>Try again</button>
        </div>
      )}
      <FxHost />
      <UpdatePill />
    </div>
  )
}
