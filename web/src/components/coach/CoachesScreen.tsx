// Settings > Coaches (athlete side): invite a coach by email, choose what they can do,
// remove them. The coach signs in at this app with their Google account.
import { useEffect, useState } from 'react'
import { Copy, Search, Trash2, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Group, Row, Switch } from '@/components/settings/Grouped'
import { Card, Field, Screen, inputCls } from '@/components/plan/ui'
import { getCoaches, inviteCoach, removeCoach, updateCoach, type CoachLink } from '@/lib/coach'

export function CoachesScreen({ onClose, onChanged, onFindCoach }: {
  onClose: () => void; onChanged: () => void
  /** "Find a coach" link when there's no coach yet */
  onFindCoach?: () => void
}) {
  const [coaches, setCoaches] = useState<CoachLink[] | null>(null)
  const [closing, setClosing] = useState(false)
  const [email, setEmail] = useState('')
  const [canEdit, setCanEdit] = useState(true)
  const [canSee, setCanSee] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const link = `${window.location.origin}/app/`

  useEffect(() => { getCoaches().then((r) => setCoaches(r.coaches), (e) => setMsg({ text: (e as Error).message, ok: false })) }, [])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  async function run(key: string, fn: () => Promise<{ coaches: CoachLink[] }>, ok?: string): Promise<boolean> {
    setBusy(key); setMsg(null)
    try { const r = await fn(); setCoaches(r.coaches); onChanged(); if (ok) setMsg({ text: ok, ok: true }); return true }
    catch (e) { setMsg({ text: (e as Error).message, ok: false }); return false }
    finally { setBusy(null) }
  }

  return (
    <Screen title="Coaches" subtitle="People who help you train" closing={closing} onClose={close}>
      {(coaches ?? []).length > 0 && (
        <section className="flex flex-col gap-3">
          {coaches!.map((c) => (
            <Group key={c.email} label={c.status === 'active' ? 'Coach' : 'Invited'}
              footer={c.status === 'invited' ? "They haven't signed in yet." : undefined}>
              <Row title={c.email} subtitle={c.status === 'active' ? 'Can message you and see your plan, events, stats and shared notes' : 'Waiting for them to sign in'} />
              <Row title="Edit my plan" subtitle="Change, move, add or delete sessions"
                trailing={<Switch label="Coach can edit my plan" checked={c.can_edit_plan} disabled={busy != null}
                  onChange={(v) => void run(c.email, () => updateCoach(c.email, { can_edit_plan: v }))} />} />
              <Row title="See my rabbt chats" subtitle="Read-only. Off keeps your chats with rabbt private."
                trailing={<Switch label="Coach can see my rabbt chats" checked={c.can_see_rabbit_chats} disabled={busy != null}
                  onChange={(v) => void run(c.email, () => updateCoach(c.email, { can_see_rabbit_chats: v }))} />} />
              {confirm === c.email ? (
                <div className="flex flex-wrap items-center gap-3 px-4 py-3.5">
                  <span className="min-w-0 basis-full break-words text-body">Remove {c.email}? They lose access right away.</span>
                  <Button variant="default" size="sm" onClick={() => setConfirm(null)}>Keep</Button>
                  <Button variant="destructive" size="sm" loading={busy === c.email}
                    onClick={() => void run(c.email, () => removeCoach(c.email), 'Coach removed.').then((ok) => { if (ok) setConfirm(null) })}>Remove</Button>
                </div>
              ) : (
                <Row title={<span className="inline-flex items-center gap-1.5"><Trash2 className="size-5" /> Remove coach</span>} danger center
                  onClick={() => setConfirm(c.email)} />
              )}
            </Group>
          ))}
        </section>
      )}

      {coaches !== null && coaches.length === 0 && onFindCoach && (
        <Group footer="rabbt doesn't take a cut; you contact coaches directly.">
          <Row icon={<Search className="size-6 text-(--accent)" />} title="Don't have a coach yet?" subtitle="Find one who fits your race"
            onClick={onFindCoach} />
        </Group>
      )}
      <Card>
        <Field label="Invite a coach" hint="Use the email of their Google account. They'll see your plan, events, stats and anything you share. Your rabbt chats stay private unless you turn that on.">
          <input className={inputCls} type="email" inputMode="email" autoComplete="off" placeholder="coach@example.com"
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Row title="Can edit my plan" trailing={<Switch label="Can edit my plan" checked={canEdit} onChange={setCanEdit} />} />
        <Row title="Can see my rabbt chats" trailing={<Switch label="Can see my rabbt chats" checked={canSee} onChange={setCanSee} />} />
        <div className="px-4 pb-4 pt-1">
          <Button variant="primary" className="h-11 w-full gap-1.5 text-body" loading={busy === 'invite'} disabled={!email.trim()}
            onClick={() => void run('invite', () => inviteCoach({ email: email.trim(), can_edit_plan: canEdit, can_see_rabbit_chats: canSee }),
              'Invited. Send them the link below.').then((ok) => { if (ok) setEmail('') })}>
            <UserPlus className="size-5" /> Invite coach
          </Button>
        </div>
      </Card>
      {msg && <p className={`px-1 text-small ${msg.ok ? 'text-(--accent)' : 'text-(--danger)'}`} role="status">{msg.text}</p>}
      <Card className="p-4">
        <p className="text-small text-(--text-secondary)">Your coach signs in here with Google:</p>
        <div className="mt-2 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-md bg-(--bg-inset) px-2 py-1.5 text-small">{link}</code>
          <Button variant="default" size="icon" className="size-9" aria-label="Copy link"
            onClick={() => { void navigator.clipboard?.writeText(link).then(() => setMsg({ text: 'Link copied.', ok: true }), () => {}) }}>
            <Copy className="size-5" />
          </Button>
        </div>
      </Card>
    </Screen>
  )
}
