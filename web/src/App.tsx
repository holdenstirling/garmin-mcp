import { useCallback, useEffect, useRef, useState } from 'react'
import { AuthError, getMe, signOut, type Me } from './lib/api'
import { CoachApp } from './components/coach/CoachApp'
import { isIOS, isStandalone } from './lib/push'
import { Chat } from './screens/Chat'
import { InstallPrompt } from './screens/InstallPrompt'
import { SignIn } from './screens/SignIn'
import { RabbitLogo } from './components/RabbitLogo'

type State =
  | { kind: 'loading' }
  | { kind: 'install' }
  | { kind: 'signin'; error: string | null }
  | { kind: 'home'; me: Me }
  | { kind: 'error'; message: string }

export function App() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [skipInstall, setSkipInstall] = useState(false)
  // Only the newest /api/me request may update state (refreshes can overlap).
  const reqId = useRef(0)
  // Once the app is showing, a failed refresh keeps the current UI instead of the error screen.
  const shown = useRef(false)

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
      shown.current = true
      setState({ kind: 'home', me })
    } catch (e) {
      if (id !== reqId.current) return
      if (e instanceof AuthError) { shown.current = false; setState({ kind: 'signin', error: authError }) }
      else if (!shown.current) setState({ kind: 'error', message: (e as Error).message })
    }
  }, [skipInstall])

  useEffect(() => { void load() }, [load])

  return (
    <div className="app-shell">
      {state.kind === 'loading' && (
        <div className="flex flex-1 items-center justify-center"><RabbitLogo size={48} thinking /></div>
      )}
      {state.kind === 'install' && <InstallPrompt onSkip={() => setSkipInstall(true)} />}
      {state.kind === 'signin' && <SignIn error={state.error} />}
      {state.kind === 'home' && (state.me.role === 'coach'
        ? <CoachApp me={state.me} onSignOut={() => void signOut().finally(load)} />
        : <Chat me={state.me} onChange={load} />)}
      {state.kind === 'error' && (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <RabbitLogo size={40} />
          <p className="text-(--text-secondary)">Something went wrong: {state.message}</p>
          <button className="underline" onClick={() => void load()}>Try again</button>
        </div>
      )}
    </div>
  )
}
