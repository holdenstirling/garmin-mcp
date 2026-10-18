// "Find friends from your contacts". Android (Chrome): the phone's own contact picker. iPhone
// and everywhere else: paste numbers or emails, or open a contact card file (.vcf). Rabbit
// compares them with people on Rabbit and keeps nothing; what comes back is who's here (Follow,
// Follow all) and who isn't yet (Text or Email them an invite, one tap each).
import { useRef, useState } from 'react'
import { BookUser, FileUp, Mail, MessageSquare, Users } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { FollowButton } from './PersonRows'
import { PersonAvatar } from '@/components/people/PersonLink'
import { canPickContacts, chunks, followPerson, matchContacts, parsePasted, parseVcf, pickContacts, type Contact, type FindStatus, type FindUser } from '@/lib/friends'
import { createShareLink } from '@/lib/sharelinks'

type Found = { contact: Contact; user: FindUser; status: FindStatus; follows_you: boolean }

export function ContactsSheet({ onClose }: { onClose: () => void }) {
  const [paste, setPaste] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [found, setFound] = useState<Found[] | null>(null)
  const [invite, setInvite] = useState<Contact[]>([])
  const [link, setLink] = useState<{ url: string; text: string } | null>(null)
  const [followAll, setFollowAll] = useState<'idle' | 'busy' | 'done'>('idle')
  const file = useRef<HTMLInputElement>(null)
  const picker = canPickContacts()

  async function check(list: Contact[]) {
    if (!list.length) { setErr("Couldn't find any phone numbers or emails in that."); return }
    setBusy(true); setErr(null)
    try {
      const hits: Found[] = []
      let fallback = ''
      for (const part of chunks(list)) {
        const r = await matchContacts(part)
        fallback = r.invite_link
        for (const h of r.on_rabbit) hits.push({ contact: part[h.index], user: h.user, status: h.status, follows_you: h.follows_you })
      }
      const matched = new Set(hits.map((h) => h.contact))
      setFound(hits)
      setInvite(list.filter((c) => !matched.has(c)))
      try { const l = await createShareLink({ kind: 'invite', label: 'Rabbit' }); setLink({ url: l.url, text: l.text }) }
      catch { setLink({ url: fallback, text: 'Train with me on Rabbit.' }) }
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function pick() {
    const list = await pickContacts()
    if (list) await check(list)
  }
  async function onFile(f: File | undefined) {
    if (!f) return
    if (f.size > 5_000_000) { setErr('That file is too big. Share fewer contacts at a time.'); return }
    await check(parseVcf(await f.text()))
  }
  async function followEveryone() {
    if (!found) return
    setFollowAll('busy')
    const next = [...found]
    for (const [i, f] of next.entries()) {
      if (f.status !== 'none') continue
      try { const r = await followPerson(f.user.id); next[i] = { ...f, status: r.status } }
      catch { /* that one stays */ }
    }
    setFound(next); setFollowAll('done')
  }
  const sms = (c: Contact) => link && c.phones[0]
    ? `sms:${c.phones[0].replace(/[^\d+]/g, '')}?&body=${encodeURIComponent(`${link.text} ${link.url}`)}` : null
  const mail = (c: Contact) => link && c.emails[0]
    ? `mailto:${c.emails[0]}?subject=${encodeURIComponent('Join me on Rabbit')}&body=${encodeURIComponent(`${link.text} ${link.url}`)}` : null
  const toFollow = (found ?? []).filter((f) => f.status === 'none').length

  return (
    <Sheet title="Find friends from contacts" onClose={onClose} portal className="modal--tall">
      <div className="flex flex-col gap-4 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
        {busy ? <RabbitLoader className="py-10" label="Checking your contacts" cycle={['Checking who’s on Rabbit…', 'Almost there…']} /> : found ? (
          <>
            <section aria-labelledby="ff-on" className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <h3 id="ff-on" className="min-w-0 flex-1 text-[0.8824rem] font-semibold text-(--text)">
                  {found.length ? `On Rabbit (${found.length})` : 'None of them are on Rabbit yet'}
                </h3>
                {toFollow > 1 && followAll !== 'done' && (
                  <Button variant="primary" className="h-9 px-3.5 text-[0.7647rem]" loading={followAll === 'busy'} onClick={() => void followEveryone()}>Follow all</Button>
                )}
              </div>
              {found.length > 0 && (
                <ul className="divide-y divide-(--border) overflow-hidden rounded-2xl border border-(--border) bg-(--bg-surface)">
                  {found.map((f) => (
                    <li key={f.user.id} className="flex min-h-16 items-center gap-3 px-3.5 py-2.5">
                      <PersonAvatar p={f.user} size={44} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[0.9412rem] font-medium text-(--text)">{f.user.name}</span>
                        <span className="block truncate text-[0.7059rem] text-(--text-muted)">{[f.user.handle ? `@${f.user.handle}` : '', f.contact.name && !f.contact.name.toLowerCase().startsWith(f.user.name.toLowerCase()) ? `In your contacts as ${f.contact.name}` : 'In your contacts'].filter(Boolean).join(' · ')}</span>
                      </span>
                      <FollowButton key={f.status} uid={f.user.id} status={f.status} followsYou={f.follows_you} onError={setErr} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
            {invite.length > 0 && (
              <section aria-labelledby="ff-inv" className="flex flex-col gap-2">
                <h3 id="ff-inv" className="text-[0.8824rem] font-semibold text-(--text)">Invite to Rabbit ({invite.length})</h3>
                <ul className="divide-y divide-(--border) overflow-hidden rounded-2xl border border-(--border) bg-(--bg-surface)">
                  {invite.slice(0, 200).map((c, i) => {
                    const s = sms(c), m = mail(c)
                    return (
                      <li key={i} className="flex min-h-14 items-center gap-3 px-3.5 py-2">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[0.9412rem] text-(--text)">{c.name || c.phones[0] || c.emails[0]}</span>
                          {c.name && <span className="block truncate text-[0.7059rem] text-(--text-muted)">{c.phones[0] ?? c.emails[0]}</span>}
                        </span>
                        {s ? (
                          <a href={s} className="inline-flex h-9 shrink-0 items-center gap-1 rounded-full border border-(--border) px-3 text-[0.7647rem] font-medium text-(--accent) active:bg-(--bg-inset)">
                            <MessageSquare className="size-3.5" aria-hidden /> Text
                          </a>
                        ) : m ? (
                          <a href={m} className="inline-flex h-9 shrink-0 items-center gap-1 rounded-full border border-(--border) px-3 text-[0.7647rem] font-medium text-(--accent) active:bg-(--bg-inset)">
                            <Mail className="size-3.5" aria-hidden /> Email
                          </a>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
                <p className="text-[0.7059rem] leading-snug text-(--text-muted)">Opens your Messages or Mail with an invite link. Rabbit never texts or emails anyone for you.</p>
              </section>
            )}
            <Button variant="default" className="h-11" onClick={() => { setFound(null); setInvite([]); setPaste(''); setFollowAll('idle') }}>Check more contacts</Button>
          </>
        ) : (
          <>
            <div className="flex items-start gap-3 rounded-2xl bg-(--accent-subtle) p-3.5">
              <Users className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden />
              <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
                Rabbit checks these against people on Rabbit and <b className="text-(--text)">doesn&rsquo;t keep them</b>. People who turned off &ldquo;find me by email or phone&rdquo; won&rsquo;t show up.
              </p>
            </div>
            {picker && (
              <Button variant="primary" className="h-12 gap-2 text-[0.9412rem]" onClick={() => void pick()}>
                <BookUser className="size-5" aria-hidden /> Choose from my contacts
              </Button>
            )}
            <section className="flex flex-col gap-2">
              <label htmlFor="ff-paste" className="text-[0.8235rem] font-semibold text-(--text)">
                {picker ? 'Or paste numbers or emails' : 'Paste numbers or emails'}
              </label>
              <textarea id="ff-paste" rows={4} value={paste} onChange={(e) => setPaste(e.target.value)}
                placeholder={'Jesse 303-555-1234\nsam@example.com'}
                className="w-full rounded-xl border border-input bg-transparent p-3 text-base text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
              <Button variant="primary" className="h-11" disabled={!paste.trim()} onClick={() => void check(parsePasted(paste))}>Find them on Rabbit</Button>
            </section>
            <section className="flex flex-col gap-2">
              <input ref={file} type="file" accept=".vcf,text/vcard,text/x-vcard" className="sr-only" tabIndex={-1} aria-hidden
                onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = '' }} />
              <Button variant="default" className="h-11 gap-2" onClick={() => file.current?.click()}>
                <FileUp className="size-4" aria-hidden /> Open a contacts file (.vcf)
              </Button>
              {!picker && (
                <p className="text-[0.7059rem] leading-snug text-(--text-muted)">
                  On iPhone: in Contacts, open a contact (or a list), tap Share Contact, then Save to Files, and pick that file here.
                </p>
              )}
            </section>
          </>
        )}
        {err && <p role="alert" className="text-[0.7647rem] text-(--danger)">{err}</p>}
      </div>
    </Sheet>
  )
}
