// A person's profile (server: people.py profile): photo, name, city, what you have in common,
// their recent workouts (only if you follow them, per their sharing settings: never heart rate
// or where they trained), clubs, public races; Message, Follow, Train together, Block / Report.
// Opened from any name or avatar (lib/people openPerson), on the page stack (back returns).
import { useCallback, useEffect, useState } from 'react'
import { Ban, Flag, Footprints, MessageCircle, Ellipsis, UserCheck, UserPlus, Users } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Screen } from '@/components/plan/ui'
import { SectionLabel, Stat } from '@/components/ui/brand'
import { Related } from '@/components/nav/Related'
import { fmtDay } from '@/components/plan/PlanParts'
import { fmtDist, fmtDuration } from '@/lib/format'
import { messagePeople } from '@/lib/dm'
import { openActivity } from '@/lib/activitynav'
import { blockPerson, followPerson, getProfile, openTarget, personPhoto, reportPerson, sportWord, type Profile } from '@/lib/people'
import { sportIcon } from '@/lib/sportIcon'


export function PersonScreen({ uid, imperial, onClose }: { uid: string; imperial: boolean; onClose: () => void }) {
  const [p, setP] = useState<Profile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [menu, setMenu] = useState<null | 'menu' | 'block' | 'report'>(null)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const load = useCallback(() => { setError(null); getProfile(uid).then(setP, (e: Error) => setError(e.message)) }, [uid])
  useEffect(() => { load() }, [load])
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  async function toggleFollow() {
    if (!p) return
    setBusy(true)
    try {
      const r = await followPerson(uid, !(p.following || p.pending))
      if ('person' in r) setP(r); else close()
    } catch (e) { setNote((e as Error).message) } finally { setBusy(false) }
  }
  async function doBlock() {
    setBusy(true)
    try { await blockPerson(uid); close() } catch (e) { setNote((e as Error).message) } finally { setBusy(false); setMenu(null) }
  }
  async function doReport() {
    setBusy(true)
    try { await reportPerson(uid, reason); setNote('Thanks. We got your report.') } catch (e) { setNote((e as Error).message) } finally { setBusy(false); setMenu(null) }
  }

  const name = p?.person.name ?? 'Profile'
  return (
    <Screen title={name} subtitle={p?.city || undefined} onClose={close} closing={closing}
      headerExtra={p && !p.me ? (
        <Button variant="ghost" size="icon" aria-label="More" onClick={() => setMenu('menu')}><Ellipsis className="size-6" /></Button>
      ) : undefined}
      footer={p && !p.me ? (
        <>
          <Button variant="primary" className="h-11 flex-1 gap-1.5 text-body" onClick={() => messagePeople([uid])}>
            <MessageCircle className="size-5" aria-hidden /> {p.can_message === 'request' ? 'Send a message request' : 'Message'}
          </Button>
          <Button variant="default" className="h-11 flex-1 gap-1.5 text-body" loading={busy} onClick={() => void toggleFollow()}
            aria-pressed={p.following}>
            {p.following ? <UserCheck className="size-5" aria-hidden /> : <UserPlus className="size-5" aria-hidden />}
            {p.following ? 'Following' : p.pending ? 'Requested' : p.follows_you ? 'Follow back' : 'Follow'}
          </Button>
        </>
      ) : undefined}>
      {!p && !error && (
        <div className="flex flex-col gap-3" aria-busy="true">
          <div className="skeleton h-[120px] rounded-2xl" aria-hidden />
          <div className="skeleton h-[160px] rounded-xl" aria-hidden />
          <RabbitLoader className="py-4" label="Loading their profile" cycle={['Finding them…', 'Lacing up…']} />
        </div>
      )}
      {error && <p className="py-12 text-center text-body text-(--text-muted)" role="alert">{error}</p>}
      {p && (
        <div className="flex flex-col gap-7">
          <section className="flex items-center gap-4 rounded-2xl border border-(--border) bg-(--bg-surface) p-4">
            <Avatar name={p.person.name} picture={p.person.picture ?? ''} photo={personPhoto(p.person)} size={64} />
            <div className="min-w-0 flex-1">
              <p className="font-display text-title-lg leading-tight text-(--brand)">{p.person.name}</p>
              {p.city && <p className="text-small text-(--text-muted)">{p.city}</p>}
              <p className="mt-1 text-small text-(--text-secondary)">
                {p.me ? 'This is you' : (p.follows_you && p.following ? 'You follow each other' : p.follows_you ? 'Follows you' : p.following ? 'You follow them' : 'On rabbt')}
              </p>
              {!p.me && p.in_common.clubs.length > 0 && (
                <p className="text-small text-(--text-muted)">{p.in_common.clubs.length} club{p.in_common.clubs.length === 1 ? '' : 's'} in common</p>
              )}
            </div>
          </section>
          {note && <p className="rounded-lg bg-(--accent-subtle) px-3 py-2 text-small text-(--accent)" role="status">{note}</p>}

          {p.stats && (
            <section className="flex justify-around rounded-xl border border-(--border) bg-(--bg-surface) px-2 py-3" aria-label="Last 4 weeks">
              <Stat value={String(p.stats.workouts_4w)} label="workouts, 4 wks" className="items-center" />
              {p.stats.km_4w != null && <Stat value={fmtDist(p.stats.km_4w, imperial, 'run', { decimals: 0 })} label="distance" className="items-center" />}
              {p.stats.minutes_4w != null && <Stat value={fmtDuration(p.stats.minutes_4w)} label="time" className="items-center" />}
            </section>
          )}

          <section className="flex flex-col gap-3" aria-label="Recent workouts">
            <SectionLabel>Recent workouts</SectionLabel>
            {p.workouts_hidden ? (
              <p className="rounded-xl border border-dashed border-(--border-strong) px-3.5 py-3 text-small text-(--text-muted)">
                Follow {p.person.name} to see their workouts (as much as they share).
              </p>
            ) : p.workouts_private ? (
              <p className="rounded-xl border border-dashed border-(--border-strong) px-3.5 py-3 text-small text-(--text-muted)">
                {p.person.name} keeps their workouts private for now. They show up here once {p.person.name.split(' ')[0]} turns on sharing.
              </p>
            ) : p.workouts.length === 0 ? (
              <p className="px-1 text-small text-(--text-muted)">Nothing shared in the last few weeks.</p>
            ) : (
              <ul className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
                {p.workouts.map((w) => {
                  const sw = sportWord(w.sport)
                  const I = sportIcon(sw)
                  const line = [w.km != null ? fmtDist(w.km, imperial, w.sport.includes('swim') ? 'swim' : 'run') : '', w.minutes ? fmtDuration(w.minutes) : ''].filter(Boolean).join(', ')
                  const inner = (
                    <>
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)"><I className="size-5" aria-hidden /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-body-lg font-medium leading-snug text-(--text)">{w.title}</span>
                        <span className="block text-meta text-(--text-muted)">{fmtDay(w.date, { weekday: 'short', month: 'short', day: 'numeric' })}</span>
                        {line && <span className="block text-meta text-(--text-secondary)">{line}</span>}
                      </span>
                    </>
                  )
                  return (
                    <li key={w.id}>
                      {p.me || p.following ? (
                        <button type="button" onClick={() => openActivity(w.id, p.me ? null : uid)} className="flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">{inner}</button>
                      ) : <div className="flex min-h-14 items-center gap-3 px-4 py-3">{inner}</div>}
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          {p.races.length > 0 && (
            <section className="flex flex-col gap-3" aria-label="Upcoming events">
              <SectionLabel>Upcoming</SectionLabel>
              <ul className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
                {p.races.map((r) => (
                  <li key={r.key} className="flex min-h-14 items-center gap-3 px-4 py-3">
                    <Flag className="size-5 shrink-0 text-(--accent)" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block text-body-lg font-medium leading-snug text-(--text)">{r.name}</span>
                      <span className="block text-meta text-(--text-muted)">{fmtDay(r.date, { weekday: 'short', month: 'short', day: 'numeric' })}{r.neighborhood ? ` · ${r.neighborhood}` : ''}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <Related items={[
            ...(!p.me ? [{ key: 'chat', icon: <MessageCircle className="size-5" />, label: `Chat with ${p.person.name}`, onClick: () => messagePeople([uid]) }] : []),
            ...p.clubs.map((c) => ({ key: `club:${c.id}`, icon: <Users className="size-5" />, label: c.name,
              sub: c.shared ? 'Club you share' : `${c.members ?? ''} members`.trim(), onClick: () => openTarget({ k: 'club', id: c.id }) })),
            ...(!p.me ? [{ key: 'buddies', icon: <Footprints className="size-5" />, label: 'Train together', sub: 'Training buddies near you', onClick: () => openTarget({ k: 'people' }) }] : []),
          ]} link={{ kind: 'person', id: uid }} />
        </div>
      )}

      {menu === 'menu' && p && (
        <Sheet title={p.person.name} onClose={() => setMenu(null)} portal>
          <div className="flex flex-col gap-2 p-4">
            <Button variant="default" className="h-11 justify-start gap-2" onClick={() => setMenu('report')}><Flag className="size-5" aria-hidden /> Report</Button>
            <Button variant="default" className="h-11 justify-start gap-2 text-(--danger)" onClick={() => setMenu('block')}><Ban className="size-5" aria-hidden /> Block {p.person.name}</Button>
          </div>
        </Sheet>
      )}
      {menu === 'block' && p && (
        <Sheet title={`Block ${p.person.name}?`} onClose={() => setMenu(null)} portal
          footer={<div className="flex gap-2 p-4"><Button variant="default" className="h-11 flex-1" onClick={() => setMenu(null)}>Cancel</Button>
            <Button variant="primary" className="h-11 flex-1" loading={busy} onClick={() => void doBlock()}>Block</Button></div>}>
          <p className="p-4 text-body text-(--text-secondary)">You won't see each other anywhere on rabbt, and they can't message you. They aren't told.</p>
        </Sheet>
      )}
      {menu === 'report' && p && (
        <Sheet title={`Report ${p.person.name}`} onClose={() => setMenu(null)} portal
          footer={<div className="flex gap-2 p-4"><Button variant="default" className="h-11 flex-1" onClick={() => setMenu(null)}>Cancel</Button>
            <Button variant="primary" className="h-11 flex-1" loading={busy} disabled={!reason.trim()} onClick={() => void doReport()}>Send report</Button></div>}>
          <div className="p-4">
            <label className="flex flex-col gap-1.5 text-small text-(--text-secondary)">What's wrong?
              <textarea className="min-h-24 rounded-lg border border-(--border) bg-(--bg) p-3 text-body text-(--text)" maxLength={300}
                value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
          </div>
        </Sheet>
      )}
    </Screen>
  )
}
