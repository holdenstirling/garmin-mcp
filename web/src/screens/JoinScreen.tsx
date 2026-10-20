// /app/join/<token>: someone opened an invite link. First name + email (contact only), then
// the browser makes a passkey and they're in. Or "Continue with Google": the same invite, and
// that Google account signs them in from then on (webauth.start_join). No allowlist either way.
import { LegalFooter } from '@/components/legal/LegalFooter'
import { useEffect, useId, useState } from 'react'
import { KeyRound, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { inputCls } from '@/components/plan/ui'
import { joinInfo, joinWithPasskey, passkeyError, PasskeyApiError, supportsPasskeys } from '@/lib/passkey'
import { hapticTap } from '@/lib/haptics'
import { flushUsage, track } from '@/lib/usage'
import { useDraft } from '@/lib/drafts'
import { TAGLINE } from '@/lib/legal'
import { DataPromise } from '@/components/legal/DataPromise'

/** Google's "G" (their brand colors, as Google asks sign-in buttons to show it). */
function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  )
}

type Phase = { kind: 'loading' } | { kind: 'bad'; message: string } | { kind: 'form'; inviter: string; signedIn: boolean }

export function JoinScreen({ token }: { token: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  // Name + email only (never anything else) are kept as a draft per invite (lib/drafts, no
  // account yet, so it's the device's "anon" space) until the join goes through.
  const [f, setF, draft] = useDraft<{ name: string; email: string }>(`join.${token.slice(0, 16)}`, { name: '', email: '' })
  const { name, email } = f
  const setName = (name: string) => setF((x) => ({ ...x, name }))
  const setEmail = (email: string) => setF((x) => ({ ...x, email }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ text: string; signin?: boolean } | null>(null)
  const nameId = useId(), emailId = useId(), errId = useId(), hintId = useId()

  useEffect(() => {
    joinInfo(token)
      .then((i) => setPhase({ kind: 'form', inviter: i.inviter, signedIn: i.signed_in }))
      .catch((e: Error) => setPhase({ kind: 'bad', message: e.message || "This invite link isn't valid." }))
  }, [token])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    hapticTap()
    setBusy(true); setError(null)
    try {
      await joinWithPasskey(token, name.trim(), email.trim())
      draft.clear()
      track('invite_join'); flushUsage(true) // counted as the new account (lib/usage)
      window.location.replace('/app/')
    } catch (err) {
      setError({ text: passkeyError(err), signin: err instanceof PasskeyApiError && err.signin })
      setBusy(false)
    }
  }

  if (phase.kind === 'loading') {
    return <div className="flex flex-1 items-center justify-center"><RabbitLoader size={64} label="Opening your invite…" /></div>
  }
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 overflow-y-auto p-6">
      <RabbitLoader size={64} gentle decorative />
      <div className="text-center">
        <h1 className="font-display text-display text-(--brand)">Join rabbt</h1>
        <p className="text-lead text-(--text-secondary)">{TAGLINE}</p>
        {phase.kind === 'form' && (
          <p className="mt-1.5 text-(--text-secondary)">
            {phase.inviter ? `${phase.inviter} invited you to train with rabbt.` : "You're invited to train with rabbt."}
          </p>
        )}
      </div>

      {phase.kind === 'bad' && (
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <p role="alert" className="rounded-xl bg-(--danger-subtle) px-4 py-3 text-body text-(--danger)">{phase.message}</p>
          <a href="/app/" className="inline-flex min-h-11 items-center text-body font-medium text-(--accent) underline-offset-2 hover:underline">Go to sign in</a>
        </div>
      )}

      {phase.kind === 'form' && phase.signedIn && (
        <p className="max-w-sm text-center text-body text-(--text-secondary)">
          You're already signed in on this device. <a href="/app/" className="font-medium text-(--accent) underline">Open rabbt</a>
        </p>
      )}

      {phase.kind === 'form' && !phase.signedIn && (
        <div className="flex w-full max-w-sm flex-col gap-4">
          <a href={`/app/auth/google/join/${encodeURIComponent(token)}`} onClick={() => hapticTap()}
            className="flex h-12 w-full items-center justify-center gap-2.5 rounded-xl border border-(--border-strong) bg-(--bg-surface) text-body font-semibold text-(--text) active:bg-(--bg-inset)">
            <GoogleG /> Continue with Google
          </a>
          <div className="flex items-center gap-3 text-meta text-(--text-muted)" aria-hidden>
            <span className="h-px flex-1 bg-(--border)" />or use a passkey<span className="h-px flex-1 bg-(--border)" />
          </div>
        </div>
      )}
      {phase.kind === 'form' && !phase.signedIn && (
        supportsPasskeys() ? (
          <form onSubmit={(e) => void submit(e)} className="flex w-full max-w-sm flex-col gap-4" noValidate>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={nameId} className="text-body font-medium text-(--text)">First name</label>
              <input id={nameId} className={inputCls + ' h-11'} value={name} onChange={(e) => setName(e.target.value)}
                autoComplete="given-name" maxLength={40} required aria-invalid={!!error && !name.trim()} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={emailId} className="text-body font-medium text-(--text)">Email</label>
              <input id={emailId} type="email" inputMode="email" className={inputCls + ' h-11'} value={email}
                onChange={(e) => setEmail(e.target.value)} autoComplete="email webauthn" maxLength={254} required
                aria-describedby={hintId + (error ? ` ${errId}` : '')} />
              <span id={hintId} className="text-meta leading-snug text-(--text-muted)">
                Only so we can reach you about your account. Never shown to other athletes.
              </span>
            </div>
            {error && (
              <p id={errId} role="alert" className="rounded-xl bg-(--danger-subtle) px-3 py-2 text-small text-(--danger)">
                {error.text}{' '}
                {error.signin && <a href="/app/" className="font-medium underline">Sign in</a>}
              </p>
            )}
            <Button type="submit" variant="primary" className="h-11 gap-2 text-body" disabled={busy || !name.trim() || !email.trim()}>
              {busy ? <KeyRound className="size-5" aria-hidden /> : <UserPlus className="size-5" aria-hidden />}
              {busy ? 'Creating your passkey…' : 'Create my passkey'}
            </Button>
            <p className="text-center text-meta leading-snug text-(--text-muted)">
              A passkey signs you in with your face, fingerprint or device PIN. No password to remember.
              By joining you agree to the <a href="/app/terms" className="underline">terms</a> and{' '}
              <a href="/app/privacy" className="underline">privacy policy</a>.
            </p>
          </form>
        ) : (
          <p role="alert" className="max-w-sm text-center text-body text-(--danger)">
            This browser can't create passkeys. Open this link in Safari, Chrome or Edge on your phone or computer.
          </p>
        )
      )}
      <DataPromise center className="max-w-xs" />
      <LegalFooter />
    </div>
  )
}
