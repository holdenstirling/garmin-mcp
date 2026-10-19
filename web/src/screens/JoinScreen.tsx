// /app/join/<token>: someone opened an invite link. First name + email (contact only), then
// the browser makes a passkey and they're in. No Google, no allowlist.
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
      <LegalFooter />
    </div>
  )
}
