import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'

const ERRORS: Record<string, string> = {
  not_allowed: "That Google account isn't on the invite list. Ask Andrew to add it.",
  expired: 'That sign-in took too long or was interrupted. Please try again.',
  cancelled: 'Sign-in was cancelled.',
  google: "Couldn't reach Google. Please try again.",
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
      {redirecting
        ? <RabbitLoader size={80} label="Signing you in…" />
        : <RabbitLoader size={80} gentle decorative />}
      <div>
        <h1 className="font-display text-4xl text-(--brand)">Rabbit</h1>
        <p className="mt-2 text-(--text-secondary)">Your training pacer. Prep, reviews, and a nudge when you need it.</p>
      </div>
      {error && (
        <p className="max-w-sm rounded-(--radius) bg-(--danger-subtle) px-3 py-2 text-sm text-(--danger)">
          {ERRORS[error] ?? 'Sign-in failed. Please try again.'}
        </p>
      )}
      <Button asChild variant="primary" className="h-11 px-6 text-sm">
        <a href="/app/auth/google/start" onClick={(e) => {
          // A modified click opens a new tab; only a plain click leaves this page.
          if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) setRedirecting(true)
        }}>Sign in with Google</a>
      </Button>
    </div>
  )
}
