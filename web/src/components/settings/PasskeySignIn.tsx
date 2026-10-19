// "Sign in with a passkey" on the sign-in screen (discoverable credentials: no email to type).
import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { passkeyError, signInWithPasskey, supportsPasskeys } from '@/lib/passkey'
import { hapticTap } from '@/lib/haptics'

export function PasskeySignIn({ onSignedIn }: { onSignedIn?: () => void } = {}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!supportsPasskeys()) return null
  const go = async () => {
    hapticTap()
    setBusy(true); setError(null)
    try {
      await signInWithPasskey()
      if (onSignedIn) { setBusy(false); onSignedIn() } else window.location.replace('/app/')
    } catch (e) {
      setError(passkeyError(e)); setBusy(false)
    }
  }
  return (
    <div className="flex flex-col items-center gap-2">
      <Button type="button" variant="default" className="h-11 min-w-[200px] gap-2 px-6 text-body" disabled={busy} onClick={() => void go()}>
        <KeyRound className="size-5" aria-hidden />
        {busy ? 'Checking your passkey…' : 'Sign in with a passkey'}
      </Button>
      {error && <p role="alert" className="max-w-sm text-small text-(--danger)">{error}</p>}
      <p className="max-w-xs text-small leading-snug text-(--text-secondary)">
        Got an invite link? Open it to join. rabbt doesn't need Google.
      </p>
    </div>
  )
}
