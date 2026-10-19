// When the session runs out mid-use (any 401 -> AuthError -> 'rabbit:auth-lost'), App shows
// this over the current screen instead of throwing the person out: whatever they were typing
// stays on screen (and in its draft), and queued saves (lib/outbox) go out once they're back.
//   * passkey: signs in right here;
//   * Google: opens sign-in in a small window and picks the session up when it comes back
//     (the window closes itself, see App.tsx). If popups are blocked it falls back to a full
//     redirect; drafts are in localStorage, so the form comes back when reopened, and App
//     shows "pick up where you left off" after sign-in.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui/button'
import { PasskeySignIn } from '@/components/settings/PasskeySignIn'
import { useDialog } from '@/hooks/useDialog'
import { getMe } from '@/lib/api'
import { lastDraft } from '@/lib/drafts'

export const RESUME_KEY = 'rabbit.resume'

export function SessionLost({ userId, onBack }: { userId: string; onBack: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  const [checking, setChecking] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const popup = useRef<Window | null>(null)
  useDialog(box, undefined)

  const check = async () => {
    setChecking(true)
    try {
      const me = await getMe()
      if (me.user_id === userId) { onBack(); return }
      // Someone else signed in: start over cleanly (their own drafts load for them).
      window.location.replace('/app/')
    } catch { /* still signed out */ } finally { setChecking(false) }
  }

  // Coming back from the sign-in window.
  useEffect(() => {
    const onFocus = () => { if (popup.current) void check() }
    window.addEventListener('focus', onFocus)
    const t = window.setInterval(() => { if (popup.current?.closed) { popup.current = null; void check() } }, 1000)
    return () => { window.removeEventListener('focus', onFocus); window.clearInterval(t) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const google = () => {
    setMsg(null)
    const w = window.open('/app/auth/google/start', 'rabbit-signin', 'popup,width=480,height=640')
    if (w) { popup.current = w; setMsg('Finish signing in in the new window, then come back here.'); return }
    // Popup blocked: full redirect. Remember where they were; drafts are already saved.
    try {
      const d = lastDraft(2 * 3600_000)
      window.localStorage.setItem(RESUME_KEY, JSON.stringify({ user: userId, at: Date.now(), label: d?.label ?? null }))
    } catch { /* ignore */ }
    window.location.assign('/app/auth/google/start')
  }

  return createPortal(
    <div className="fixed inset-0 z-(--z-dialog) flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" />
      <div ref={box} role="alertdialog" aria-modal="true" aria-labelledby="session-lost-title"
        className="relative z-10 mx-4 flex w-full max-w-sm flex-col items-center gap-3 rounded-lg border bg-background p-5 text-center shadow-lg">
        <h3 id="session-lost-title" className="text-lead font-semibold text-(--text)">Sign in again to keep going</h3>
        <p className="text-body text-(--text-muted)">
          You were signed out. What you typed is still here, and anything not saved yet goes through once you're back.
        </p>
        <Button variant="primary" className="h-11 min-w-[200px]" onClick={google} loading={checking}>Sign in with Google</Button>
        <PasskeySignIn onSignedIn={() => void check()} />
        {msg && <p role="status" className="text-small text-(--text-muted)">{msg}</p>}
        <button type="button" className="hit-44 text-small underline text-(--text-muted)" onClick={() => void check()}>
          I've signed in
        </button>
      </div>
    </div>,
    document.body,
  )
}
