// "Friends' latest" on the Rabbit home: the last 3 friend workouts/posts (community.py
// `latest`), one line each with a one-tap cheer; tapping a line opens the Community feed.
// Light on purpose: nothing renders until there's something from friends.
import { useEffect, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { burst } from '@/components/anim'
import { PersonAvatar } from '@/components/community/Feed'
import { ago, react, unreact, type Post } from '@/lib/community'
import { getFriendsLatest } from '@/lib/community2'
import { fmtDist, fmtDuration } from '@/lib/format'
import { hapticTap } from '@/lib/haptics'
import { cn } from '@/lib/utils'

function line(p: Post, imperial: boolean): string {
  const w = p.workout
  if (w) {
    const bits = [w.km ? fmtDist(w.km, imperial, w.sport) : null, w.minutes ? fmtDuration(w.minutes) : null].filter(Boolean)
    return [w.title, ...bits].join(' · ') + (w.headline ? ` · ${w.headline}` : '')
  }
  return p.text || (p.photos.length ? 'Shared a photo' : 'Shared a post')
}

export function FriendsLatest({ refreshKey, imperial, onOpenFeed, onShown }: {
  refreshKey?: number; imperial: boolean; onOpenFeed: () => void
  /** tells the home whether the strip shows (Quick actions then skips its own cheer chip) */
  onShown?: (shown: boolean) => void
}) {
  const [items, setItems] = useState<Post[]>([])
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getFriendsLatest().then((r) => { if (live) { setItems(r.items); onShown?.(r.items.length > 0) } },
      () => { if (live) { setItems([]); onShown?.(false) } })
    return () => { live = false }
  }, [refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!items.length) return null

  async function cheer(p: Post, el: HTMLElement) {
    const on = p.my_reaction != null
    const optimistic = { ...p, my_reaction: on ? null : 'party' as const, reaction_total: p.reaction_total + (on ? -1 : 1) }
    setItems((xs) => xs.map((x) => (x.id === p.id ? optimistic : x)))
    if (!on) { burst(el, 'kudos'); hapticTap() }
    try {
      const r = on ? await unreact(p.id) : await react(p.id, 'party')
      setItems((xs) => xs.map((x) => (x.id === p.id ? { ...r.post, user: p.user } : x)))
      setErr(null)
    } catch (e) {
      setItems((xs) => xs.map((x) => (x.id === p.id ? p : x)))
      setErr((e as Error).message)
    }
  }

  return (
    <div className="px-4">
      <section aria-label="Friends' latest" className="mx-auto max-w-2xl rounded-2xl border border-(--border) bg-(--bg-surface) px-3 py-2">
        <button type="button" onClick={onOpenFeed} className="flex min-h-9 w-full items-center gap-1 text-left">
          <h2 className="flex-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Friends' latest</h2>
          <span className="flex items-center text-[0.7059rem] font-medium text-(--accent)">Feed <ChevronRight className="size-3.5" aria-hidden /></span>
        </button>
        <ul className="flex flex-col">
          {items.map((p) => (
            <li key={p.id} className="flex items-center gap-2 border-t border-(--border) first:border-t-0">
              <button type="button" onClick={onOpenFeed} className="flex min-h-12 min-w-0 flex-1 items-center gap-2.5 text-left">
                <PersonAvatar u={p.user} size={30} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.7647rem] text-(--text)">
                    <span className="font-medium">{p.user?.name ?? 'A friend'}</span> <span className="text-(--text-muted)">· {ago(p.created)}</span>
                  </span>
                  <span className="block truncate text-[0.7059rem] text-(--text-secondary)">{line(p, imperial)}</span>
                </span>
              </button>
              <button type="button" aria-pressed={p.my_reaction != null}
                aria-label={p.my_reaction ? `Cheered ${p.user?.name ?? ''}`.trim() : `Cheer ${p.user?.name ?? 'your friend'}`}
                onClick={(e) => void cheer(p, e.currentTarget)}
                className={cn('hit-44 inline-flex h-9 shrink-0 items-center gap-1 rounded-full px-3 text-[0.7059rem] font-medium transition-colors',
                  p.my_reaction ? 'bg-(--accent-subtle) text-(--accent)' : 'border border-(--border) text-(--text-secondary) active:bg-(--bg-inset)')}>
                <span aria-hidden className={cn(p.my_reaction && 'celebrate')}>🎉</span>
                {p.reaction_total > 0 ? <span className="tabular-nums">{p.reaction_total}</span> : 'Cheer'}
              </button>
            </li>
          ))}
        </ul>
        {err && <p className="pb-1 text-[0.7059rem] text-(--danger)" role="status">{err}</p>}
      </section>
    </div>
  )
}
