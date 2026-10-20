// Check-in buddy: pick a friend who follows you back, tap "I'm heading out" with how long you'll
// be, then "I'm back". If you're not back 15 minutes after that, rabbt nudges you; 15 minutes
// later it tells your buddy. Nothing about where you ran is stored or sent.
import { useEffect, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Section } from '@/components/ui/section'
import { Card } from '@/components/plan/ui'
import { Sheet } from '@/components/ui/Sheet'
import { Choice } from './Choice'
import { PersonAvatar } from './Feed'
import { backSafe, getBuddy, setBuddy, startOut, type BuddyState } from '@/lib/buddycheck'
import { getPeople, type SocialUser } from '@/lib/social'

const TIMES: [string, string][] = [['30', '30 min'], ['45', '45 min'], ['60', '1 hour'], ['90', '1.5 hours'], ['120', '2 hours'], ['180', '3 hours']]

export function BuddyCheckCard() {
  const [s, setS] = useState<BuddyState | null>(null)
  const [pick, setPick] = useState(false)
  const [mins, setMins] = useState('60')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getBuddy().then(setS, () => setS(null)) }, [])
  async function run(fn: () => Promise<BuddyState>) {
    setBusy(true); setErr(null)
    try { setS(await fn()) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  if (!s) return null
  const backBy = s.active ? new Date(s.active.back_by * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : null
  return (
    <Section title="Check-in buddy" description="Running alone? A friend hears when you head out and when you're back. No location is shared.">
      <Card className="flex flex-col gap-3 p-4">
        {!s.buddy_user ? (
          <>
            <p className="text-small text-(--text-secondary)">Pick a friend who follows you back. They get a notification for each tap, and one if you're late.</p>
            <Button variant="default" className="h-11 gap-1.5 text-body" onClick={() => setPick(true)}><ShieldCheck className="size-5" aria-hidden /> Pick a buddy</Button>
          </>
        ) : s.active ? (
          <>
            <p className="text-body text-(--text)">You're out. {s.buddy_user.name} expects you back by {backBy}.</p>
            <Button variant="primary" className="h-12 text-body" loading={busy} onClick={() => void run(backSafe)}>I'm back</Button>
          </>
        ) : (
          <>
            <div className="flex items-center gap-3">
              <PersonAvatar u={s.buddy_user} size={36} />
              <p className="min-w-0 flex-1 text-body text-(--text)">{s.buddy_user.name} is your buddy</p>
              <Button variant="ghost" className="h-11 px-2 text-meta" onClick={() => setPick(true)}>Change</Button>
            </div>
            <div className="flex flex-col gap-1.5">
              <p className="text-meta text-(--text-muted)">Back in about</p>
              <Choice label="Back in about" value={mins} options={TIMES} onChange={setMins} />
            </div>
            <Button variant="default" className="h-11 text-body" loading={busy} onClick={() => void run(() => startOut(Number(mins)))}>I'm heading out</Button>
          </>
        )}
        {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
      </Card>
      {pick && <PickBuddy current={s.buddy} onClose={() => setPick(false)} onPick={(id) => { setPick(false); void run(() => setBuddy(id)) }} />}
    </Section>
  )
}

function PickBuddy({ current, onClose, onPick }: { current: string | null; onClose: () => void; onPick: (id: string | null) => void }) {
  const [friends, setFriends] = useState<SocialUser[] | null>(null)
  useEffect(() => {
    getPeople().then((p) => {
      const back = new Set(p.followers.map((e) => e.user?.id).filter(Boolean))
      setFriends(p.following.map((e) => e.user).filter((u): u is SocialUser => !!u && back.has(u.id)))
    }, () => setFriends([]))
  }, [])
  return (
    <Sheet title="Pick a check-in buddy" onClose={onClose}>
      {friends && friends.length === 0 && <p className="text-body text-(--text-secondary)">Your buddy has to be someone you follow who follows you back. Add a friend first.</p>}
      {friends && friends.length > 0 && (
        <Card>
          {friends.map((u) => (
            <button key={u.id} type="button" onClick={() => onPick(u.id)} aria-pressed={u.id === current}
              className="flex min-h-14 w-full items-center gap-3 border-b border-(--border) px-4 py-2 text-left last:border-b-0 active:bg-(--bg-inset)">
              <PersonAvatar u={u} size={32} />
              <span className="min-w-0 flex-1 truncate text-body text-(--text)">{u.name}</span>
              {u.id === current && <span className="text-meta text-(--accent)">Your buddy</span>}
            </button>
          ))}
        </Card>
      )}
      {current && <Button variant="ghost" className="h-11 text-body text-(--danger)" onClick={() => onPick(null)}>Stop using a buddy</Button>}
    </Sheet>
  )
}
