// "Share new workouts with friends?" asked right after a watch or app connects (ConnectSheet's
// "You're all set"), so the feed fills from day one. Only shown when the person hasn't answered
// yet. Yes posts the last few days once (community.py backfill), then each new workout.
import { useEffect, useState } from 'react'
import { Check, Share2 } from 'lucide-react'
import { getCommunitySettings, putCommunitySettings } from '@/lib/community'
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
      await putCommunitySettings({ share_workouts: v, share_prompted: true })
      setState(v ? 'on' : 'off')
    } catch (e) { setErr((e as Error).message); setState('ask') }
  }

  return (
    <section aria-labelledby="share-choice" className={cn('flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5', className)}>
      <div className="flex items-start gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
          {state === 'on' ? <Check className="size-4" /> : <Share2 className="size-4" />}
        </span>
        <div className="min-w-0">
          <h3 id="share-choice" className="text-[0.8235rem] font-semibold text-(--text)">
            {state === 'on' ? 'Sharing with friends' : state === 'off' ? 'Workouts stay private' : 'Share new workouts with friends?'}
          </h3>
          <p className="text-[0.7059rem] leading-snug text-(--text-secondary)">
            {state === 'on' ? 'Your last few days are on the Feed now. New ones post after each sync.'
              : state === 'off' ? 'You can turn this on any time in Me.'
                : 'People who follow you see sport, time and distance on the Feed. Never heart rate or where.'}
          </p>
        </div>
      </div>
      {(state === 'ask' || state === 'busy') && (
        <div className="flex gap-2">
          <button type="button" disabled={state === 'busy'} onClick={() => void answer(true)}
            className="min-h-11 flex-1 rounded-full bg-(--accent) px-4 text-[0.7647rem] font-semibold text-(--on-fill) active:opacity-80 disabled:opacity-60">
            Yes, share
          </button>
          <button type="button" disabled={state === 'busy'} onClick={() => void answer(false)}
            className="min-h-11 flex-1 rounded-full border border-(--border) px-4 text-[0.7647rem] font-medium text-(--text) active:bg-(--bg-inset) disabled:opacity-60">
            Not now
          </button>
        </div>
      )}
      {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
    </section>
  )
}
