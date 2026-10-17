// Why the Feed has no workouts from friends, in one line, with the one thing that fixes it:
//   * no watch or app connected -> "Connect your watch"
//   * my own sharing is off      -> "Your workouts are private" + Turn on
//   * otherwise                  -> friends show up once they follow you back and share
// Shown on the main feed when nothing from friends is there yet. Quiet, dismissable by use.
import { useEffect, useState } from 'react'
import { Info, Share2, UserPlus, Watch } from 'lucide-react'
import { getCommunitySettings, putCommunitySettings, sharingWorkouts } from '@/lib/community'
import { getConnections, requestConnect } from '@/lib/connections'

type Why = 'no_watch' | 'private' | 'friends'

export function FeedHint({ onInvite, onShared }: { onInvite?: () => void; onShared?: () => void }) {
  const [why, setWhy] = useState<Why | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    Promise.all([getConnections().catch(() => null), getCommunitySettings().catch(() => null)]).then(([c, s]) => {
      if (!live) return
      const watch = !!c?.apps.some((a) => (a.id === 'garmin' || a.id === 'oura') && a.connected)
      setWhy(c && !watch ? 'no_watch' : s && !sharingWorkouts(s.settings) ? 'private' : 'friends')
    })
    return () => { live = false }
  }, [])
  if (why === null) return null

  async function turnOn() {
    setBusy(true)
    try {
      await putCommunitySettings({ share_workouts: true, share_prompted: true })
      setWhy('friends'); onShared?.()
    } catch { /* the row in Me still works */ } finally { setBusy(false) }
  }

  const line = why === 'no_watch' ? 'Connect your watch so your workouts can show up here, and friends see them after each sync.'
    : why === 'private' ? 'Your workouts are private, so friends don’t see them here.'
      : 'Friends’ workouts show here once they follow you back and turn on sharing. New ones post after their next sync.'
  const Icon = why === 'no_watch' ? Watch : why === 'private' ? Share2 : Info
  return (
    <div role="note" className="flex items-start gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5">
      <Icon className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">{line}</p>
        <div className="flex flex-wrap gap-x-4">
          {why === 'no_watch' && (
            <button type="button" onClick={() => requestConnect('garmin')} className="min-h-11 text-[0.7647rem] font-semibold text-(--accent)">
              Connect your watch
            </button>
          )}
          {why === 'private' && (
            <button type="button" disabled={busy} onClick={() => void turnOn()} className="min-h-11 text-[0.7647rem] font-semibold text-(--accent) disabled:opacity-60">
              Share my workouts
            </button>
          )}
          {onInvite && (
            <button type="button" onClick={onInvite} className="inline-flex min-h-11 items-center gap-1 text-[0.7647rem] font-semibold text-(--accent)">
              <UserPlus className="size-3.5" aria-hidden /> Find friends
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
