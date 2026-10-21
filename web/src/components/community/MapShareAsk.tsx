// "Show your routes on the Feed map too?" asked right after someone says yes to sharing their
// workouts (WelcomeFlow's share step, ShareNudge, ShareChoice), so friends' routes fill the Feed
// map without a trip to settings. Maps are their own opt-in (community.py routes_share: None =
// never asked = off). Only asked when it hasn't been answered; start and finish stay trimmed
// and the home area stays hidden either way (routes.py).
import { useEffect, useState } from 'react'
import { Check, Map as MapIcon } from 'lucide-react'
import { getCommunitySettings, putCommunitySettings } from '@/lib/community'
import { cn } from '@/lib/utils'

type State = 'hidden' | 'ask' | 'busy' | 'on' | 'off'

export function MapShareAsk({ className, onDone }: {
  className?: string
  /** answered (or already answered): the parent can move on */
  onDone?: (shared: boolean | null) => void
}) {
  const [state, setState] = useState<State>('hidden')
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getCommunitySettings().then((r) => {
      if (!live) return
      if (r.settings.routes_share == null) setState('ask')
      else onDone?.(r.settings.routes_share)
    }, () => { if (live) onDone?.(null) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  if (state === 'hidden') return null

  async function answer(v: boolean) {
    setState('busy'); setErr(null)
    try {
      await putCommunitySettings({ routes_share: v })
      setState(v ? 'on' : 'off')
      onDone?.(v)
    } catch (e) { setErr((e as Error).message || "Couldn't save just now."); setState('ask') }
  }

  return (
    <section aria-labelledby="map-share-ask" aria-live="polite"
      className={cn('flex flex-col gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5', className)}>
      <div className="flex items-start gap-2.5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
          {state === 'on' ? <Check className="rb-pop size-5" /> : <MapIcon className="size-5" />}
        </span>
        <div className="min-w-0">
          <h3 id="map-share-ask" className="m-0 text-body font-semibold leading-snug text-(--text)">
            {state === 'on' ? 'Your routes are on the map' : state === 'off' ? 'Maps stay private' : 'Show your routes on the Feed map too?'}
          </h3>
          <p className="m-0 mt-0.5 text-small leading-snug text-(--text-secondary)">
            {state === 'on' ? 'Friends see the line of each run you share. Change it any time in Community settings.'
              : state === 'off' ? 'Friends still see sport, time and distance. Turn maps on any time in Community settings.'
                : 'Friends see the line of your run. The start and finish are trimmed, so where you live stays private.'}
          </p>
        </div>
      </div>
      {(state === 'ask' || state === 'busy') && (
        <div className="flex gap-2">
          <button type="button" disabled={state === 'busy'} onClick={() => void answer(true)}
            className="min-h-11 flex-1 rounded-full bg-(--accent) px-4 text-small font-semibold text-(--on-fill) active:opacity-80 disabled:opacity-60">
            Yes, show routes
          </button>
          <button type="button" disabled={state === 'busy'} onClick={() => void answer(false)}
            className="min-h-11 flex-1 rounded-full border border-(--border) px-4 text-small font-medium text-(--text) active:bg-(--bg-inset) disabled:opacity-60">
            Keep maps private
          </button>
        </div>
      )}
      {err && <p className="m-0 text-small text-(--danger)" role="alert">{err}</p>}
    </section>
  )
}
