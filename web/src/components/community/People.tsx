// Community → People: suggestions (people in your clubs and race crews, followers you
// don't follow back), then the friends tools that used to live in Friends (invite code, add
// by email or code, requests, following/followers, what followers see, blocked).
import { openPerson } from '@/lib/people'
import { useCallback, useEffect, useState } from 'react'
import { UserPlus } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { PullToRefresh } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Group, Row } from '@/components/settings/Grouped'
import { PeopleTab } from '@/components/social/FriendsScreen'
import { getPeople, markSocialSeen, type People, type SocialUser } from '@/lib/social'
import { followSuggested, getSuggested } from '@/lib/community'
import { PersonAvatar as TapAvatar, PersonLink } from '@/components/people/PersonLink'

const LOADING = ['Finding your crew…', 'Lacing up…']
const SEEN_EVENT = 'rabbit:social-seen' // clears the Community tab dot (TabBar.useSocialBadge)

export function PeopleSection({ onChanged }: { imperial?: boolean; onChanged?: () => void }) {
  const [people, setPeople] = useState<People | null>(null)
  const [suggested, setSuggested] = useState<{ user: SocialUser | null; reason: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<Record<string, string>>({})

  const load = useCallback(() => Promise.all([
    getPeople().then((p) => { setPeople(p); setError(null) }, (e) => setError((e as Error).message)),
    getSuggested().then((s) => setSuggested(s.people), () => { /* suggestions are a bonus */ }),
  ]), [])
  useEffect(() => {
    void load()
    void markSocialSeen().then(() => window.dispatchEvent(new Event(SEEN_EVENT)), () => { /* dot just stays */ })
  }, [load])

  async function follow(u: SocialUser) {
    setBusy(u.id)
    try { const r = await followSuggested(u.id); setDone((d) => ({ ...d, [u.id]: r.status === 'active' ? 'Following' : 'Requested' })); void getPeople().then(setPeople) }
    catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  if (!people) return error ? <ErrorState compact message={error} onRetry={() => void load()} /> : <RabbitLoader className="py-10" label="Loading people" cycle={LOADING} />
  const sug = suggested.filter((s): s is { user: SocialUser; reason: string } => !!s.user)
  return (
    <>
      <PullToRefresh onRefresh={load} />
      {error && <ErrorState compact message={error} onRetry={() => void load()} />}
      {sug.length > 0 && (
        <Group label="Suggested">
          {sug.slice(0, 8).map(({ user: u, reason }) => (
            <Row key={u.id} icon={<TapAvatar p={u} size={30} />} title={<PersonLink id={u.id} name={u.name} />} subtitle={reason}
              trailing={done[u.id] ? <span className="text-[0.7059rem] text-(--accent)">{done[u.id]}</span> : (
                <Button variant="default" className="h-8 gap-1 px-2.5 text-[0.7059rem]" loading={busy === u.id} disabled={busy != null}
                  onClick={() => void follow(u)}><UserPlus className="size-3.5" /> Follow</Button>
              )} />
          ))}
        </Group>
      )}
      <PeopleTab people={people} onOpen={openPerson} setPeople={setPeople}
        onChanged={() => { void load(); onChanged?.() }} />
    </>
  )
}
