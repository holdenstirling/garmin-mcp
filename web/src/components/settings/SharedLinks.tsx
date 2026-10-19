// Settings › Shared links: every link you've texted (workouts, events, clubs, invites) with how
// many times it was opened, and Turn off per link (the page stops working at once). Plus
// "Invite a friend by text" (a share link with your join invite when you can invite).
import { useEffect, useState } from 'react'
import { Link2, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ShareSheet } from '@/components/ui/ShareSheet'
import { SHARE_KIND_LABEL, listShareLinks, revokeShareLink, type SharedLinkRow } from '@/lib/sharelinks'
import { Icon, Row } from './Grouped'

export function SharedLinks() {
  const [links, setLinks] = useState<SharedLinkRow[] | null>(null)
  const [inviting, setInviting] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = () => listShareLinks().then((r) => setLinks(r.links), () => setLinks([]))
  useEffect(() => { void load() }, [])

  async function off(id: string) {
    setBusy(id); setErr(null)
    try { await revokeShareLink(id); setLinks((xs) => (xs ?? []).filter((x) => x.id !== id)) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }

  return (
    <>
      <Row icon={<Icon><UserPlus /></Icon>} title="Invite a friend by text" subtitle="Send a link that opens rabbt's invite page"
        onClick={() => setInviting(true)} />
      {(links ?? []).slice(0, 30).map((l) => (
        <div key={l.id} className="flex min-h-16 items-center gap-3.5 px-4 py-3">
          <Icon><Link2 /></Icon>
          <span className="min-w-0 flex-1">
            <span className="block text-body-lg font-medium leading-snug text-(--text)">{l.title || SHARE_KIND_LABEL[l.kind]}</span>
            <span className="block text-small text-(--text-secondary)">
              {SHARE_KIND_LABEL[l.kind]}, shared {new Date(l.created * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })}
            </span>
            <span className="block text-small text-(--text-secondary)">Opened {l.views} {l.views === 1 ? 'time' : 'times'}</span>
          </span>
          <Button variant="ghost" className="h-11 px-3 text-small text-(--danger)" loading={busy === l.id}
            aria-label={`Turn off the link to ${l.title || SHARE_KIND_LABEL[l.kind]}`} onClick={() => void off(l.id)}>Turn off</Button>
        </div>
      ))}
      {links && links.length === 0 && (
        <p className="px-4 py-3.5 text-body text-(--text-secondary)">No shared links yet. Use Share on a workout, event or club to text it to someone.</p>
      )}
      {err && <p className="px-4 pb-3 text-small text-(--danger)" role="alert">{err}</p>}
      {inviting && <ShareSheet target={{ kind: 'invite', label: '' }} onClose={() => { setInviting(false); void load() }} />}
    </>
  )
}
