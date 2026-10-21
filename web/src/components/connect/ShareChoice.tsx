// "Share new workouts with friends?" asked right after a watch or app connects (ConnectSheet's
// "You're all set"), so the feed fills from day one. Only shown when the person hasn't answered
// yet. Yes posts the last few days once (community.py backfill), then each new workout.
import { useEffect, useState } from 'react'
import { Check, Share2 } from 'lucide-react'
import { MapShareAsk } from '@/components/community/MapShareAsk'
import { getCommunitySettings, putCommunitySettings, SHARE_CONSENT_LINE } from '@/lib/community'
import { cn } from '@/lib/utils'

export function ShareChoice({ className }: { className?: string }) {
  const [state, setState] = useState<'hidden' | 'ask' | 'busy' | 'on' | 'off'>('hidden')
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getCommunitySettings().then((r) => {
      if (live && r.settings.share_workouts == null) setState('ask')
    }, () => {})
    return () => { live = false }
  }, [])
  if (state === 'hidden') return null

  async function answer(v: boolean) {
    setState('busy'); setErr(null)
    try {
      // "Not now" isn't a no: it leaves sharing unanswered so a later ask (Home card) still can.
      await putCommunitySettings(v ? { share_workouts: true, share_prompted: true } : { share_prompted: true })
      setState(v ? 'on' : 'off')
    } catch (e) { setErr((e as Error).message); setState('ask') }
  }

  return (
    <section aria-labelledby="share-choice" className={cn('flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5', className)}>
      <div className="flex items-start gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
          {state === 'on' ? <Check className="size-5" /> : <Share2 className="size-5" />}
        </span>
        <div className="min-w-0">
          <h3 id="share-choice" className="text-body font-semibold text-(--text)">
            {state === 'on' ? 'Sharing with friends' : state === 'off' ? 'Workouts stay private' : 'Share new workouts with friends?'}
          </h3>
          <p className="text-meta leading-snug text-(--text-secondary)">
            {state === 'on' ? 'Your last few days are on the Feed now. New ones post after each sync.'
              : state === 'off' ? 'No problem. Share any time from Home or Community settings.'
                : SHARE_CONSENT_LINE}
          </p>
        </div>
      </div>
      {(state === 'ask' || state === 'busy') && (
        <div className="flex gap-2">
          <button type="button" disabled={state === 'busy'} onClick={() => void answer(true)}
            className="min-h-11 flex-1 rounded-full bg-(--accent) px-4 text-small font-semibold text-(--on-fill) active:opacity-80 disabled:opacity-60">
            Yes, share
          </button>
          <button type="button" disabled={state === 'busy'} onClick={() => void answer(false)}
            className="min-h-11 flex-1 rounded-full border border-(--border) px-4 text-small font-medium text-(--text) active:bg-(--bg-inset) disabled:opacity-60">
            Not now
          </button>
        </div>
      )}
      {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
      {state === 'on' && <MapShareAsk className="mt-1 border-0 bg-(--bg-inset) p-3" />}
    </section>
  )
}
