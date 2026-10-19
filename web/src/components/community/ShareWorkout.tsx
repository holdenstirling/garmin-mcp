// "Post to feed" on my workout (reaction card, reward, workout page): explicit. Shows "On your
// Feed" when it's already there (auto-shared or posted before; the server never makes a copy). Posts a compact
// card (sport, distance, time, highlight) to your default audience; never maps, heart rate or health data.
import { useEffect, useState } from 'react'
import { Check, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { burst } from '@/components/anim'
import { getWorkoutPost, shareWorkout } from '@/lib/community'

export function ShareWorkoutButton({ activityId }: { activityId: number }) {
  const [state, setState] = useState<'idle' | 'busy' | 'done'>('idle')
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {  // already on the feed (auto-shared): say so instead of offering a copy
    let live = true
    getWorkoutPost(activityId).then((r) => { if (live && r.post_id) setState('done') }, () => {})
    return () => { live = false }
  }, [activityId])
  async function share(el: HTMLElement) {
    setState('busy'); setErr(null)
    try { await shareWorkout(activityId); setState('done'); burst(el, 'kudos') }
    catch (e) { setErr((e as Error).message); setState('idle') }
  }
  return (
    <div className="flex flex-col gap-1">
      <Button variant="ghost" className="h-11 gap-1.5 text-small" loading={state === 'busy'} disabled={state === 'done'}
        onClick={(e) => void share(e.currentTarget)}>
        {state === 'done' ? <><Check className="size-5" /> On your Feed</> : <><Share2 className="size-5" /> Post to feed</>}
      </Button>
      {err && <p className="text-center text-meta text-(--danger)" role="alert">{err}</p>}
    </div>
  )
}
