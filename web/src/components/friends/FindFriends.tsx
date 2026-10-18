// Find friends: one place to add people. Search (@handle, name, exact email or phone), three
// big ways in (Invite friends by text or any app, From contacts, My QR code), People you may
// know (follow or hide), follow requests waiting for you, and how people can find you.
// Opened from the Feed, Me, search, + Add and the first-run steps (lib/friends openFindFriends);
// a QR / follow link (/app/?add=CODE) opens it with that person on top.
import { useCallback, useEffect, useRef, useState } from 'react'
import { AtSign, BookUser, ChevronRight, QrCode as QrIcon, Search as SearchIcon, Send, Users, X } from 'lucide-react'
import { Screen } from '@/components/plan/ui'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { ShareSheet } from '@/components/ui/ShareSheet'
import { PersonAvatar } from '@/components/people/PersonLink'
import { HopIn } from '@/components/anim'
import { ContactsSheet } from './ContactsSheet'
import { FindMeSheet } from './FindMeSheet'
import { QrSheet } from './QrSheet'
import { FollowButton, PersonRow } from './PersonRows'
import {
  dismissSuggestion, getFindMe, getSuggestedPeople, searchPeople, whoseCode,
  type FindMe, type FindRow, type FindStatus, type FindUser,
} from '@/lib/friends'
import { acceptRequest, declineRequest, follow as followByCode, getPeople, type PersonEdge } from '@/lib/social'
import { openPlace } from '@/lib/nav'

type Sheet = 'invite' | 'contacts' | 'qr' | 'me' | null

export function FindFriends({ onClose, section, add, q: q0 }: { onClose: () => void; section?: 'me'; add?: string; q?: string }) {
  const [q, setQ] = useState(q0 ?? '')
  const [results, setResults] = useState<FindRow[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [sug, setSug] = useState<FindRow[] | null>(null)
  const [requests, setRequests] = useState<PersonEdge[]>([])
  const [me, setMe] = useState<FindMe | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sheet, setSheet] = useState<Sheet>(section === 'me' ? 'me' : null)
  const [code, setCode] = useState<string | null>(add ?? null)
  const seq = useRef(0)

  const load = useCallback(() => {
    setErr(null)
    getSuggestedPeople().then((r) => setSug(r.people), (e) => { setSug([]); setErr((e as Error).message) })
    getPeople().then((p) => setRequests(p.pending_in), () => {})
    getFindMe().then(setMe, () => {})
  }, [])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    const text = q.trim()
    if (text.length < 2) { setResults(null); setSearching(false); return }
    const n = ++seq.current
    setSearching(true)
    const t = window.setTimeout(() => {
      searchPeople(text).then((r) => { if (n === seq.current) { setResults(r.people); setSearching(false) } },
        (e) => { if (n === seq.current) { setErr((e as Error).message); setSearching(false) } })
    }, 250)
    return () => window.clearTimeout(t)
  }, [q])

  const hide = (uid: string) => {
    setSug((s) => s && s.filter((r) => r.user.id !== uid))
    void dismissSuggestion(uid).catch(() => {})
  }
  const answer = async (e: PersonEdge, yes: boolean) => {
    setRequests((r) => r.filter((x) => x.edge_id !== e.edge_id))
    try { await (yes ? acceptRequest(e.edge_id) : declineRequest(e.edge_id)) } catch (x) { setErr((x as Error).message); load() }
  }
  const searchOn = q.trim().length >= 2

  return (
    <Screen title="Find friends" onClose={onClose}>
      <div className="flex flex-col gap-5 pb-[max(16px,env(safe-area-inset-bottom))]">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 size-5 -translate-y-1/2 text-(--text-muted)" aria-hidden />
          <input type="text" inputMode="search" role="searchbox" value={q} onChange={(e) => setQ(e.target.value)} enterKeyHint="search"
            aria-label="Search people by name, @handle, email or phone" placeholder="Name, @handle, email or phone"
            autoCapitalize="none" autoCorrect="off" spellCheck={false}
            className="h-12 w-full rounded-full border border-(--border) bg-(--bg-surface) pl-11 pr-11 text-base text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--accent)/40" />
          {q && (
            <button type="button" onClick={() => setQ('')} aria-label="Clear search"
              className="absolute right-1.5 top-1/2 flex size-9 -translate-y-1/2 items-center justify-center rounded-full text-(--text-muted) active:bg-(--bg-inset)">
              <X className="size-4" aria-hidden />
            </button>
          )}
        </div>

        {code && <AddByCode code={code} onDone={() => { setCode(null); load() }} />}

        {searchOn ? (
          <section aria-label="Search results" aria-busy={searching}>
            {results === null ? <RabbitLoader inline label="Searching" className="px-2 py-3" /> : results.length ? (
              <ul className="divide-y divide-(--border) overflow-hidden rounded-2xl border border-(--border) bg-(--bg-surface)">
                {results.map((r) => (
                  <PersonRow key={r.user.id} user={r.user} reason={r.reason || (r.follows_you ? 'Follows you' : '')} status={r.status}
                    followsYou={r.follows_you} onError={setErr} />
                ))}
              </ul>
            ) : (
              <EmptyState compact mode="think" title={`No one found for “${q.trim()}”`}
                body="Try their @handle, full email or phone number. Not on Rabbit yet? Invite them."
                action="Invite friends" onAction={() => setSheet('invite')} />
            )}
          </section>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2">
              <WayIn icon={<Send />} label="Invite friends" onClick={() => setSheet('invite')} primary />
              <WayIn icon={<BookUser />} label="From contacts" onClick={() => setSheet('contacts')} />
              <WayIn icon={<QrIcon />} label="QR code" onClick={() => setSheet('qr')} />
            </div>

            {requests.length > 0 && (
              <section aria-labelledby="ff-req" className="flex flex-col gap-2">
                <h2 id="ff-req" className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Want to follow you</h2>
                <ul className="divide-y divide-(--border) overflow-hidden rounded-2xl border border-(--border) bg-(--bg-surface)">
                  {requests.map((e) => e.user && (
                    <li key={e.edge_id} className="flex min-h-16 items-center gap-3 px-3.5 py-2.5">
                      <PersonAvatar p={e.user} size={44} />
                      <span className="min-w-0 flex-1 truncate text-[0.9412rem] font-medium text-(--text)">{e.user.name}</span>
                      <button type="button" onClick={() => void answer(e, true)}
                        className="h-9 shrink-0 rounded-full bg-(--accent) px-3.5 text-[0.7647rem] font-semibold text-(--on-fill) active:opacity-80">Accept</button>
                      <button type="button" onClick={() => void answer(e, false)} aria-label={`Decline ${e.user.name}`}
                        className="flex size-9 shrink-0 items-center justify-center rounded-full text-(--text-muted) active:bg-(--bg-inset)"><X className="size-4" aria-hidden /></button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section aria-labelledby="ff-sug" className="flex flex-col gap-2">
              <h2 id="ff-sug" className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">People you may know</h2>
              {sug === null ? <RabbitLoader className="py-8" label="Finding people you may know" cycle={['Finding your crew…', 'Lacing up…']} />
                : sug.length ? (
                  <ul className="divide-y divide-(--border) overflow-hidden rounded-2xl border border-(--border) bg-(--bg-surface)">
                    {sug.map((r) => (
                      <PersonRow key={r.user.id} user={r.user} reason={r.reason} status={r.status} followsYou={r.follows_you}
                        onDismiss={() => hide(r.user.id)} onError={setErr} />
                    ))}
                  </ul>
                ) : (
                  <EmptyState compact card mode="wave" title="No suggestions yet"
                    body="Join a club, add your next race, or invite a friend, and people you may know show up here."
                    action="Invite friends" onAction={() => setSheet('invite')} />
                )}
            </section>
          </>
        )}

        {err && <ErrorState compact message={err} onRetry={load} />}

        <button type="button" onClick={() => setSheet('me')}
          className="flex min-h-14 w-full items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)"><AtSign className="size-4" aria-hidden /></span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[0.8824rem] font-medium text-(--text)">{me ? `You're @${me.handle}` : 'Your @handle'}</span>
            <span className="block text-[0.7059rem] text-(--text-muted)">Change it, and choose how people can find you</span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
        <button type="button" onClick={() => { onClose(); openPlace('people') }}
          className="flex min-h-14 w-full items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--bg-inset) text-(--text-secondary)"><Users className="size-4" aria-hidden /></span>
          <span className="min-w-0 flex-1">
            <span className="block text-[0.8824rem] font-medium text-(--text)">Following and followers</span>
            <span className="block text-[0.7059rem] text-(--text-muted)">Manage who you follow, requests you sent, and blocks</span>
          </span>
          <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
      </div>

      {sheet === 'invite' && <ShareSheet target={{ kind: 'invite', label: 'Rabbit' }} onClose={() => setSheet(null)} />}
      {sheet === 'contacts' && <ContactsSheet onClose={() => { setSheet(null); load() }} />}
      {sheet === 'qr' && <QrSheet onClose={() => setSheet(null)} onScanned={(c) => { setSheet(null); setCode(c) }} />}
      {sheet === 'me' && <FindMeSheet onClose={() => setSheet(null)} onSaved={setMe} />}
    </Screen>
  )
}

function WayIn({ icon, label, onClick, primary }: { icon: React.ReactNode; label: string; onClick: () => void; primary?: boolean }) {
  return (
    <button type="button" onClick={onClick}
      className={primary
        ? 'flex min-h-[88px] flex-col items-center justify-center gap-1.5 rounded-2xl bg-(--accent) px-2 text-center text-[0.7647rem] font-semibold text-(--on-fill) active:opacity-85 [&>svg]:size-6'
        : 'flex min-h-[88px] flex-col items-center justify-center gap-1.5 rounded-2xl border border-(--border) bg-(--bg-surface) px-2 text-center text-[0.7647rem] font-semibold text-(--text) active:bg-(--bg-inset) [&>svg]:size-6 [&>svg]:text-(--accent)'}>
      {icon}{label}
    </button>
  )
}

/** Someone's QR code or follow link: who it is, and Follow. */
function AddByCode({ code, onDone }: { code: string; onDone: () => void }) {
  const [who, setWho] = useState<{ user: FindUser; status: FindStatus | 'self'; follows_you: boolean } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  useEffect(() => { whoseCode(code).then(setWho, (e) => setErr((e as Error).message)) }, [code])
  async function go() {
    setBusy(true)
    try { const r = await followByCode(code); setDone(r.message) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  if (err) return <ErrorState compact message={err} />
  if (!who) return <RabbitLoader inline label="Looking them up" className="px-2 py-3" />
  return (
    <HopIn className="flex flex-col items-center gap-2 rounded-2xl border border-(--accent)/30 bg-(--accent-subtle) p-4 text-center">
      <PersonAvatar p={who.user} size={64} />
      <p className="text-[1rem] font-semibold text-(--text)">{who.user.name}</p>
      {who.user.handle && <p className="-mt-1.5 text-[0.7647rem] text-(--text-muted)">@{who.user.handle}</p>}
      {who.status === 'self' ? <p className="text-[0.7647rem] text-(--text-secondary)">That&rsquo;s your own code.</p>
        : done ? <p role="status" className="text-[0.8235rem] font-medium text-(--accent)">{done}</p>
        : who.status !== 'none' ? <FollowButton uid={who.user.id} status={who.status} />
        : (
          <button type="button" disabled={busy} onClick={() => void go()}
            className="h-11 rounded-full bg-(--accent) px-6 text-[0.8824rem] font-semibold text-(--on-fill) active:opacity-80 disabled:opacity-60">
            {who.follows_you ? 'Follow back' : 'Follow'}
          </button>
        )}
      <button type="button" onClick={onDone} className="hit-44 text-[0.7059rem] text-(--text-muted)">Done</button>
    </HopIn>
  )
}
