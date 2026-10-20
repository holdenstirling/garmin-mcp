import { LegalFooter } from '@/components/legal/LegalFooter'
import { DataPromise } from '@/components/legal/DataPromise'
import { TAGLINE } from '@/lib/legal'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { hapticTap } from '@/lib/haptics'
import { PasskeySignIn } from '@/components/settings/PasskeySignIn'

const ERRORS: Record<string, string> = {
  not_allowed: "That Google account doesn't have a rabbt account yet. Ask a friend on rabbt for an invite link, then tap Continue with Google on it.",
  invite: 'That invite link has expired or is used up. Ask for a new one.',
  account_exists: 'That email already has a rabbt account. Sign in with your passkey instead.',
  expired: 'That sign-in took too long or got interrupted. Try once more.',
  cancelled: 'Sign-in was cancelled.',
  google: "Couldn't reach Google. Check your connection and try again.",
  busy: 'Too many sign-ins in progress. Try again in a minute.',
}

export function SignIn({ error }: { error: string | null }) {
  // Set while the browser heads off to Google; reset if the page comes back from bfcache.
  const [redirecting, setRedirecting] = useState(false)
  useEffect(() => {
    const reset = (e: PageTransitionEvent) => { if (e.persisted) setRedirecting(false) }
    window.addEventListener('pageshow', reset)
    return () => window.removeEventListener('pageshow', reset)
  }, [])

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-6 text-center">
      {/* Tapping Sign in: the rabbit speeds up and does a little jump (.rb-jump). */}
      <div className={redirecting ? 'rb-jump' : undefined}>
        {redirecting
          ? <RabbitLoader size={80} label="Signing you in…" />
          : <RabbitLoader size={80} gentle decorative />}
      </div>
      <div>
        <h1 className="font-display text-display-xl text-(--brand)">rabbt</h1>
        <p className="mt-2 text-lead text-(--text-secondary)">{TAGLINE}</p>
      </div>
      {error && (
        <p role="alert" className="max-w-sm rounded-(--radius) bg-(--danger-subtle) px-3 py-2 text-body text-(--danger)">
          {ERRORS[error] ?? "Sign-in didn't go through. Try once more."}
        </p>
      )}
      <Button asChild variant="primary" className="h-11 px-6 text-body">
        <a href="/app/auth/google/start" onClick={(e) => {
          // A modified click opens a new tab; only a plain click leaves this page.
          if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { hapticTap(); setRedirecting(true) }
        }}>Sign in with Google</a>
      </Button>
      <PasskeySignIn />
      <DataPromise center className="max-w-xs" />
      <LegalFooter />
    </div>
  )
}
