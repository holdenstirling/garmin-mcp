// "Friends today" on the Rabbit home: who you follow trained today (people.py friends_today,
// one-tap kudos) and who races soon, merged with friends' latest posts (community.py `latest`,
// one-tap cheer). Names and avatars open that person; a post line opens the Community feed.
// Light on purpose: nothing renders until there's something from friends.
import { useEffect, useState } from 'react'
import { Flag } from 'lucide-react'
import { Section, SeeAll } from '@/components/ui/section'
import { Card } from '@/components/plan/ui'
import { burst } from '@/components/anim'
import { PersonAvatar } from '@/components/community/Feed'
import { ago, react, unreact, type Post } from '@/lib/community'
import { getFriendsLatest } from '@/lib/community2'
import { fmtDist, fmtDuration } from '@/lib/format'
import { hapticTap } from '@/lib/haptics'
import { cn } from '@/lib/utils'
import { giveKudos, takeKudos } from '@/lib/social'
import { getFriendsToday, openPerson, sportWord, type FriendsToday } from '@/lib/people'
import { PersonAvatar as TapAvatar } from '@/components/people/PersonLink'
import { daysUntil } from '@/lib/events'
import { displayText } from '@/lib/mentions'

function line(p: Post, imperial: boolean): string {
  const w = p.workout
  if (w) {
    const bits = [w.km ? fmtDist(w.km, imperial, w.sport) : null, w.minutes ? fmtDuration(w.minutes) : null].filter(Boolean)
    return [w.title, ...bits].join(' · ') + (w.headline ? ` · ${w.headline}` : '')
  }
  return displayText(p.text) || (p.photos.length ? 'Shared a photo' : 'Shared a post')
}

export function FriendsLatest({ refreshKey, imperial, onOpenFeed, onShown }: {
  refreshKey?: number; imperial: boolean; onOpenFeed: () => void
  /** tells the home whether the strip shows (Quick actions then skips its own cheer chip) */
  onShown?: (shown: boolean) => void
}) {
  const [items, setItems] = useState<Post[]>([])
  const [today, setToday] = useState<FriendsToday | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    Promise.all([
      getFriendsLatest().then((r) => r.items, () => [] as Post[]),
      getFriendsToday().catch(() => null),
    ]).then(([posts, t]) => {
      if (!live) return
      // Someone already in "today" doesn't repeat below with the same workout's post.
      const trained = new Set((t?.trained ?? []).map((x) => x.person.id))
      const rest = posts.filter((p) => !(p.workout && p.user && trained.has(p.user.id))).slice(0, 3)
      setItems(rest); setToday(t)
      onShown?.(rest.length > 0 || !!t?.trained.length)
    })
    return () => { live = false }
  }, [refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const trained = today?.trained.slice(0, 4) ?? []
  const racing = today?.racing.slice(0, 2) ?? []
  if (!items.length && !trained.length && !racing.length) return null

  async function kudos(i: number, el: HTMLElement) {
    const t = trained[i]
    if (!t || !today) return
    const on = t.you_cheered
    const flip = (x: FriendsToday['trained'][number], v: boolean, n: number) => ({ ...x, you_cheered: v, kudos: n })
    const upd = (v: boolean, n: number) => setToday((d) => d && ({ ...d, trained: d.trained.map((x) => (x.workout.id === t.workout.id && x.person.id === t.person.id ? flip(x, v, n) : x)) }))
    upd(!on, t.kudos + (on ? -1 : 1))
    if (!on) { burst(el, 'kudos'); hapticTap() }
    try {
      const r = on ? await takeKudos(t.person.id, t.workout.id) : await giveKudos(t.person.id, t.workout.id)
      upd(r.you_kudoed, r.count); setErr(null)
    } catch (e) { upd(on, t.kudos); setErr((e as Error).message) }
  }

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

  const kudosBtn = 'hit-44 inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-small font-medium transition-colors'
  return (
    <Section title={trained.length || racing.length ? 'Friends today' : "Friends' latest"}
      action={<SeeAll label="Feed" ariaLabel="Open the feed" onClick={onOpenFeed} />}>
      <Card>
        <ul className="flex flex-col divide-y divide-(--border)">
          {trained.map((t, i) => {
            const w = t.workout
            const bits = [w.km != null ? fmtDist(w.km, imperial, w.sport.includes('swim') ? 'swim' : w.sport) : null, w.minutes ? fmtDuration(w.minutes) : null].filter(Boolean)
            return (
              <li key={`t:${t.person.id}:${w.id}`} className="flex items-center gap-3 px-4 py-3">
                <TapAvatar p={t.person} size={40} />
                <button type="button" onClick={() => openPerson(t.person.id)} className="flex min-h-11 min-w-0 flex-1 flex-col justify-center text-left">
                  <span className="block text-body leading-snug text-(--text)"><span className="font-semibold">{t.person.name}</span> <span className="text-(--text-muted)">trained today</span></span>
                  <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">{w.title || sportWord(w.sport)}{bits.length ? ` · ${bits.join(' · ')}` : ''}</span>
                </button>
                <button type="button" aria-pressed={t.you_cheered}
                  aria-label={t.you_cheered ? `Gave ${t.person.name} kudos` : `Give ${t.person.name} kudos`}
                  onClick={(e) => void kudos(i, e.currentTarget)}
                  className={cn(kudosBtn, t.you_cheered ? 'bg-(--accent-subtle) text-(--accent)' : 'border border-(--border) text-(--text-secondary) active:bg-(--bg-inset)')}>
                  <span aria-hidden className={cn(t.you_cheered && 'celebrate')}>👏</span>
                  {t.kudos > 0 ? <span className="tabular-nums">{t.kudos}</span> : 'Kudos'}
                </button>
              </li>
            )
          })}
          {racing.map((r) => {
            const d = daysUntil(r.date)
            return (
              <li key={`r:${r.key}`} className="flex items-center gap-3 px-4 py-3">
                <TapAvatar p={r.person} size={40} />
                <button type="button" onClick={() => openPerson(r.person.id)} className="flex min-h-11 min-w-0 flex-1 flex-col justify-center text-left">
                  <span className="block text-body leading-snug text-(--text)"><span className="font-semibold">{r.person.name}</span> <span className="text-(--text-muted)">{d <= 0 ? 'is racing today' : d === 1 ? 'races tomorrow' : `races in ${d} days`}</span></span>
                  <span className="mt-0.5 flex items-center gap-1.5 text-small leading-snug text-(--text-secondary)"><Flag className="size-4 shrink-0 text-(--accent)" aria-hidden />{r.name}</span>
                </button>
              </li>
            )
          })}
          {items.map((p) => (
            <li key={p.id} className="flex items-center gap-3 px-4 py-3">
              <button type="button" onClick={onOpenFeed} className="flex min-h-11 min-w-0 flex-1 items-center gap-3 text-left">
                <PersonAvatar u={p.user} size={40} />
                <span className="min-w-0 flex-1">
                  <span className="block text-body leading-snug text-(--text)">
                    <span className="font-semibold">{p.user?.name ?? 'A friend'}</span> <span className="text-(--text-muted)">{ago(p.created)}</span>
                  </span>
                  <span className="mt-0.5 line-clamp-2 text-small leading-snug text-(--text-secondary)">{line(p, imperial)}</span>
                </span>
              </button>
              <button type="button" aria-pressed={p.my_reaction != null}
                aria-label={p.my_reaction ? `Cheered ${p.user?.name ?? ''}`.trim() : `Cheer ${p.user?.name ?? 'your friend'}`}
                onClick={(e) => void cheer(p, e.currentTarget)}
                className={cn(kudosBtn, p.my_reaction ? 'bg-(--accent-subtle) text-(--accent)' : 'border border-(--border) text-(--text-secondary) active:bg-(--bg-inset)')}>
                <span aria-hidden className={cn(p.my_reaction && 'celebrate')}>🎉</span>
                {p.reaction_total > 0 ? <span className="tabular-nums">{p.reaction_total}</span> : 'Cheer'}
              </button>
            </li>
          ))}
        </ul>
        {err && <p className="px-4 pb-3 text-small text-(--danger)" role="status">{err}</p>}
      </Card>
    </Section>
  )
}
