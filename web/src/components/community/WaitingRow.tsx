// The Feed's "haven't shared yet" row: people I follow who never answered "share my workouts"
// (server: community.py `waiting`). One tap asks them (a push from me by name, at most weekly;
// community.py `ask_friend`). Asking shares nothing: they still decide on their Share card.
import { useState } from 'react'
import { Check, Hand } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PersonAvatar } from '@/components/community/Feed'
import { askShare, type Waiting } from '@/lib/community'

/** "Jesse hasn't" / "Jesse and Axel haven't" / "Jesse, Axel and 2 others haven't" */
export function waitingLine(names: string[]): string {
  const first = names.map((n) => n.split(' ')[0])
  if (first.length === 1) return `${first[0]} hasn't shared their workouts yet`
  if (first.length === 2) return `${first[0]} and ${first[1]} haven't shared their workouts yet`
  return `${first[0]}, ${first[1]} and ${first.length - 2} other${first.length > 3 ? 's' : ''} haven't shared their workouts yet`
}

export function WaitingRow({ people }: { people: Waiting[] }) {
  const [asked, setAsked] = useState<Record<string, boolean>>(() => Object.fromEntries(people.map((p) => [p.id, p.asked_recently])))
  const [busy, setBusy] = useState<string | null>(null)
  if (!people.length) return null
  const open = people.filter((p) => !asked[p.id])

  async function ask(ids: string[]) {
    setBusy(ids.length > 1 ? 'all' : ids[0])
    for (const id of ids) {
      try { await askShare(id) } catch { /* one failing never blocks the rest */ }
      setAsked((a) => ({ ...a, [id]: true }))
    }
    setBusy(null)
  }

  return (
    <section aria-label="Friends who haven't shared yet" className="flex flex-col gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-4 py-3.5">
      <div className="flex items-center gap-3">
        <div className="flex shrink-0 -space-x-2" aria-hidden>
          {people.slice(0, 3).map((p) => (
            <span key={p.id} className="rounded-full ring-2 ring-(--bg-surface)"><PersonAvatar u={p.user ?? null} size={32} /></span>
          ))}
        </div>
        <p className="m-0 min-w-0 flex-1 text-body font-semibold leading-snug text-(--text)">{waitingLine(people.map((p) => p.name))}</p>
      </div>
      <p className="m-0 text-small leading-snug text-(--text-secondary)">
        Give them a nudge. They choose whether to share; it's sport, time and distance only.
      </p>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {people.map((p) => (
          <li key={p.id} className="flex min-h-11 items-center gap-3">
            <PersonAvatar u={p.user ?? null} size={28} />
            <span className="min-w-0 flex-1 truncate text-body text-(--text)">{p.name.split(' ')[0]}</span>
            {asked[p.id] ? (
              <span className="flex items-center gap-1 text-small font-medium text-(--text-muted)"><Check className="size-4" aria-hidden /> Asked</span>
            ) : (
              <Button variant="default" className="h-9 gap-1.5 px-3 text-small" loading={busy === p.id} disabled={busy !== null}
                onClick={() => void ask([p.id])} aria-label={`Ask ${p.name.split(' ')[0]} to share their workouts`}>
                <Hand className="size-4" aria-hidden /> Ask
              </Button>
            )}
          </li>
        ))}
      </ul>
      {open.length > 1 && (
        <Button variant="primary" className="h-11 w-full text-body" loading={busy === 'all'} disabled={busy !== null}
          onClick={() => void ask(open.map((p) => p.id))}>
          Ask all {open.length}
        </Button>
      )}
    </section>
  )
}

/** "Ask to see their workouts" on a friend's card, when they haven't answered. */
export function AskShareButton({ id, name, status }: { id: string; name: string; status: { can_ask: boolean; asked_recently?: boolean } }) {
  const [done, setDone] = useState(!!status.asked_recently)
  const [busy, setBusy] = useState(false)
  if (!status.can_ask && !status.asked_recently) return null
  const first = name.split(' ')[0]
  if (done) {
    return <p role="status" className="m-0 flex items-center gap-1.5 text-small text-(--text-muted)"><Check className="size-4" aria-hidden /> You asked {first} to share. They decide.</p>
  }
  return (
    <Button variant="default" className="h-11 w-full gap-1.5 text-small" loading={busy}
      onClick={async () => { setBusy(true); try { await askShare(id); setDone(true) } catch { /* try again later */ } finally { setBusy(false) } }}>
      <Hand className="size-5" aria-hidden /> Ask {first} to share their workouts
    </Button>
  )
}
