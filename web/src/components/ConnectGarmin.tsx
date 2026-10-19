import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, Lock, Mail } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getJSON, postRaw } from '@/lib/api'

type Job = {
  job_id: string
  state: 'pending' | 'needs_mfa' | 'ok' | 'error' | 'cooldown'
  error: string | null
  mfa_tries_left: number | null
  cooldown_until?: number | null
  cooldown_scope?: 'user' | 'global' | null
}

// What went wrong and what to do about it, in Garmin's terms.
const ERRORS: Record<string, string> = {
  bad_credentials: "Garmin didn't accept that email or password. Use the ones you sign in to the Garmin Connect app with, and check for a typo.",
  bad_mfa: "That code didn't work. Use the newest code Garmin sent you.",
  rate_limited: 'Garmin is limiting sign-ins right now. Nothing is wrong with your account.',
  blocked: "Garmin's security check stopped this sign-in. Wait a few minutes and try again.",
  failed: "rabbt couldn't reach Garmin just now. Check your connection and try again.",
  expired: 'That sign-in timed out, so nothing was saved. Start again whenever you’re ready.',
}

function fmtTime(epochSec: number): string {
  return new Date(epochSec * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(t)
  }, [active])
  return now
}

export type GarminStep = 'signin' | 'code' | 'connecting'

// The Garmin sign-in form (email + password, then Garmin's code when it asks), shown as steps
// inside the Garmin connect popup (components/connect/ConnectSheet.tsx). `onStep` lets the
// popup draw its progress indicator.
export function ConnectGarmin({ cooldownUntil, onConnected, onStep }: {
  cooldownUntil: number | null
  onConnected: () => void
  onStep?: (s: GarminStep) => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [until, setUntil] = useState<number | null>(cooldownUntil)
  const [submitting, setSubmitting] = useState(false)
  const [show, setShow] = useState(false)
  const poll = useRef<ReturnType<typeof setTimeout> | null>(null)
  const now = useNow(until !== null)
  const coolingDown = until !== null && until > now
  const step: GarminStep = job?.state === 'pending' ? 'connecting' : job?.state === 'needs_mfa' ? 'code' : 'signin'
  const stepCb = useRef(onStep)
  stepCb.current = onStep
  useEffect(() => { stepCb.current?.(step) }, [step])

  // Polling stops once this form is gone (a poll already in flight is ignored).
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (poll.current) clearTimeout(poll.current)
    }
  }, [])

  function handle(j: Job) {
    if (!mounted.current) return
    setJob(j)
    if (j.state === 'pending') {
      poll.current = setTimeout(async () => {
        poll.current = null
        if (!mounted.current) return
        try {
          const next = await getJSON<Job>(`/api/garmin/login/${j.job_id}`)
          if (mounted.current) handle(next)
        } catch (e) {
          if (!mounted.current) return
          setMessage((e as Error).message); setJob(null)
        }
      }, 2000)
      return
    }
    if (j.state === 'ok') { setPassword(''); onConnected(); return }
    if (j.state === 'needs_mfa') { setMessage(j.error ? ERRORS[j.error] : null); return }
    // error or cooldown
    setPassword('')
    setCode('')
    const base = j.error ? ERRORS[j.error] ?? ERRORS.failed : null
    if (j.cooldown_until) {
      setUntil(j.cooldown_until)
      setMessage(j.cooldown_scope === 'global'
        ? `${base ?? ERRORS.rate_limited} To avoid a longer block, rabbt will wait until ${fmtTime(j.cooldown_until)} before trying again.`
        : `${base ?? ''} You can try again at ${fmtTime(j.cooldown_until)}.`.trim())
    } else {
      setMessage(base)
    }
  }

  async function submitLogin(e: React.FormEvent) {
    e.preventDefault()
    setMessage(null)
    setSubmitting(true)
    try {
      const r = await postRaw<Job & { error?: string }>('/api/garmin/login', { email, password })
      if (r.status === 202 || r.status === 429) handle(r.data)
      else setMessage(r.data?.error ?? `Error ${r.status}`)
    } catch (err) {
      setMessage((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault()
    if (!job) return
    setMessage(null)
    setSubmitting(true)
    try {
      const r = await postRaw<Job & { error?: string }>('/api/garmin/mfa', { job_id: job.job_id, code: code.trim() })
      if (r.status === 202) { setCode(''); handle(r.data) }
      else setMessage(r.data?.error ?? `Error ${r.status}`)
    } catch (err) {
      setMessage(`Couldn't send the code: ${(err as Error).message}. Check your connection and try again.`)
    } finally {
      setSubmitting(false)
    }
  }

  if (job?.state === 'pending') {
    return (
      <div role="status" className="flex flex-col items-center gap-1 py-2 text-center">
        <p className="text-[0.8235rem] font-medium text-(--text)">Signing in to Garmin…</p>
        <p className="text-[0.7059rem] text-(--text-muted)">This can take up to a minute. You can keep this open.</p>
      </div>
    )
  }

  const label = 'text-[0.7059rem] font-medium text-(--text-secondary)'
  if (job?.state === 'needs_mfa') {
    return (
      <form onSubmit={submitCode} className="flex flex-col gap-2.5">
        <p className="flex items-start gap-2 rounded-xl bg-(--bg-inset) px-3.5 py-3 text-[0.7647rem] leading-snug text-(--text-secondary)">
          <Mail className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
          Garmin sent a verification code to your email or phone. Enter it here to finish signing in.
        </p>
        <label className="flex flex-col gap-1.5">
          <span className={label}>Verification code</span>
          <Input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*" maxLength={8}
            placeholder="123456" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            className="h-12 text-center text-lg tracking-[0.4em]" autoFocus aria-invalid={!!message || undefined} />
        </label>
        {message && <p role="alert" className="text-[0.7059rem] text-(--danger)">{message}</p>}
        {job.mfa_tries_left != null && job.mfa_tries_left < 3 && (
          <p className="text-[0.7059rem] text-(--text-muted)">{job.mfa_tries_left} {job.mfa_tries_left === 1 ? 'try' : 'tries'} left</p>
        )}
        <Button type="submit" variant="primary" className="h-12" loading={submitting} disabled={code.length < 4}>Verify and connect</Button>
      </form>
    )
  }

  return (
    <form onSubmit={submitLogin} className="flex flex-col gap-2.5">
      <p className="flex items-center gap-1.5 text-[0.7647rem] font-semibold text-(--text)">
        <Lock className="size-4 text-(--accent)" aria-hidden />Sign in with your Garmin account
      </p>
      <label className="flex flex-col gap-1.5">
        <span className={label}>Email</span>
        <Input type="email" autoComplete="username" inputMode="email" autoCapitalize="off" autoCorrect="off" spellCheck={false}
          placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} className="h-12 text-base" required autoFocus />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className={label}>Password</span>
        <span className="relative block">
          <Input type={show ? 'text' : 'password'} autoComplete="current-password" autoCapitalize="off" autoCorrect="off" spellCheck={false}
            placeholder="Garmin password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-12 pr-12 text-base" required />
          <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}
            className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-(--text-muted)">
            {show ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
          </button>
        </span>
      </label>
      {message && <p role="alert" className={`text-[0.7059rem] leading-snug ${coolingDown ? 'text-(--warning-text)' : 'text-(--danger)'}`}>{message}</p>}
      {coolingDown && !message && (
        <p className="text-[0.7059rem] text-(--warning-text)">You can try again at {fmtTime(until!)}.</p>
      )}
      <Button type="submit" variant="primary" className="h-12" loading={submitting}
        disabled={coolingDown || !email || !password}>
        {coolingDown ? `Try again at ${fmtTime(until!)}` : 'Sign in and connect'}
      </Button>
      <p className="flex items-start gap-2 rounded-xl bg-(--bg-inset) px-3.5 py-2.5 text-[0.7059rem] leading-snug text-(--text-secondary)">
        <Lock className="mt-0.5 size-3.5 shrink-0 text-(--accent)" aria-hidden />
        rabbt passes your password to Garmin once to sign in and never stores it. rabbt keeps only Garmin’s sign-in token, encrypted, and you can disconnect anytime.
      </p>
    </form>
  )
}
