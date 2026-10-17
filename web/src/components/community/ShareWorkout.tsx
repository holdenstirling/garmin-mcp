// "Share this workout" on the post-workout reaction card: explicit only. Posts a compact
// card (sport, distance, time, highlight) to your default audience; never maps, heart rate or health data.
import { useState } from 'react'
import { Check, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { burst } from '@/components/anim'
import { shareWorkout } from '@/lib/community'

export function ShareWorkoutButton({ activityId }: { activityId: number }) {
  const [state, setState] = useState<'idle' | 'busy' | 'done'>('idle')
  const [err, setErr] = useState<string | null>(null)
  async function share(el: HTMLElement) {
    setState('busy'); setErr(null)
    try { await shareWorkout(activityId); setState('done'); burst(el, 'kudos') }
    catch (e) { setErr((e as Error).message); setState('idle') }
  }
  return (
    <div className="flex flex-col gap-1">
      <Button variant="ghost" className="h-11 gap-1.5 text-[0.7647rem]" loading={state === 'busy'} disabled={state === 'done'}
        onClick={(e) => void share(e.currentTarget)}>
        {state === 'done' ? <><Check className="size-4" /> Shared to your Feed</> : <><Share2 className="size-4" /> Share this workout</>}
      </Button>
      {err && <p className="text-center text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
    </div>
  )
}
