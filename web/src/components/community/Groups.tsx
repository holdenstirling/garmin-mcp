// Feed groups (feedgroups.py): small private circles for the feed ("Saturday long run crew").
// Create one from mutual friends (max 50 people, 10 groups each), see its members and feed,
// invite more, leave; the owner renames, removes people or deletes it. Group posts are only
// seen by the group.
import { useCallback, useEffect, useState } from 'react'
import { Check, LogOut, Pencil, Search as SearchIcon, Trash2, UserPlus, X } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyRabbit, burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Sheet } from '@/components/ui/Sheet'
import { Group, Row } from '@/components/settings/Grouped'
import { Field, Screen, inputCls } from '@/components/plan/ui'
import type { SocialUser } from '@/lib/social'
import { TAB_SHOWN_EVENT, openPlace } from '@/lib/nav'
import {
  addToGroup, deleteGroup, getGroup, groupFriends, leaveGroup, removeFromGroup,
  type FeedGroup,
} from '@/lib/community2'
import { cn } from '@/lib/utils'
import { CommunityFeed, PersonAvatar } from './Feed'
import { useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { DraftRestored, useUnsavedGuard } from '@/components/ui/UnsavedGuard'

const EMOJIS = ['👟', '🏃', '🌅', '🚴', '🏊', '⛰️', '🔥', '☕', '🍻', '🐇', '💪', '🏁']

/** Create a group, or rename it (``initial``). The primary button is pinned in the sheet's
 *  footer (always visible, above the keyboard) and says what's missing until it can go. */
export function GroupSheet({ initial, onClose, onSaved }: {
  initial?: FeedGroup; onClose: () => void; onSaved: (g: FeedGroup) => void
}) {
  type G = { name: string; emoji: string; picked: string[] }
  const [g, setG, draft] = useDraft<G>(`group.${initial?.id ?? 'new'}`,
    () => ({ name: initial?.name ?? '', emoji: initial?.emoji ?? '👟', picked: [] }), { label: initial ? 'group changes' : 'new group' })
  const { name, emoji, picked } = g
  const setName = (name: string) => setG((x) => ({ ...x, name }))
  const setEmoji = (emoji: string) => setG((x) => ({ ...x, emoji }))
  const setPicked = (picked: string[]) => setG((x) => ({ ...x, picked }))
  const guard = useUnsavedGuard(draft.dirty, draft.discard)
  const [busy, setBusy] = useState(false)
  const [queued, setQueued] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const missing = !name.trim() ? 'Give your group a name' : !initial && !picked.length ? 'Pick at least one person' : null
  async function save(el: HTMLElement) {
    if (missing) return
    setBusy(true); setErr(null); setQueued(false)
    try {
      const r = await saveDurably<{ group: FeedGroup }>(initial
        ? { method: 'PATCH', path: `/api/community/groups/${encodeURIComponent(initial.id)}`, body: { name: name.trim(), emoji }, label: 'group', coalesce: `group.${initial.id}` }
        : { method: 'POST', path: '/api/community/groups', body: { name: name.trim(), emoji, members: picked }, label: 'group' },
      () => setQueued(true))
      draft.clear()
      if (!initial) burst(el, 'kudos')
      onSaved(r.group)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false); setQueued(false) }
  }
  return (
    <Sheet title={initial ? 'Edit group' : 'New group'} onClose={guard.wrap(onClose)} extra={guard.dialog}
      bodyClassName="settings flex flex-col gap-3 overflow-y-auto p-4"
      footer={
        <div className="flex flex-col gap-1.5">
          {queued && <SaveStatus state="queued" />}
          {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
          {missing && !busy && <p className="text-center text-[0.7059rem] text-(--text-muted)" aria-live="polite">{missing}</p>}
          <Button variant="primary" className="h-12 text-[0.8235rem]" loading={busy} disabled={!!missing}
            onClick={(e) => void save(e.currentTarget)}>
            {initial ? 'Save changes' : picked.length ? `Create group with ${picked.length} ${picked.length === 1 ? 'person' : 'people'}` : 'Create group'}
          </Button>
        </div>
      }>
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      <Field label="Group name">
        <input className={inputCls} maxLength={40} value={name} placeholder="Saturday long run crew" enterKeyHint="next"
          onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Group emoji">
        {EMOJIS.map((e) => (
          <button key={e} type="button" role="radio" aria-checked={emoji === e} aria-label={`Emoji ${e}`} onClick={() => setEmoji(e)}
            className={cn('hit-44 flex size-10 items-center justify-center rounded-xl text-[1.1765rem]', emoji === e ? 'bg-(--accent-subtle) ring-1 ring-(--accent)' : 'bg-(--bg-inset)')}>{e}</button>
        ))}
      </div>
      {!initial && <FriendPicker picked={picked} onPick={setPicked} />}
      <p className="text-[0.6471rem] text-(--text-muted)">Only people in the group see what's posted to it. Anyone can leave any time.</p>
    </Sheet>
  )
}

/** Searchable picker of mutual friends; picked people show as removable chips on top. */
function FriendPicker({ picked, onPick, skip = [] }: { picked: string[]; onPick: (ids: string[]) => void; skip?: string[] }) {
  const [people, setPeople] = useState<SocialUser[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const load = useCallback(() => {
    setErr(null)
    groupFriends().then((r) => setPeople(r.people.filter((p): p is SocialUser => !!p)), (e) => setErr((e as Error).message))
  }, [])
  useEffect(() => { load() }, [load])
  // Back from finding friends (the Feed tab stays mounted): pick up anyone just followed.
  useEffect(() => {
    const on = () => load()
    window.addEventListener(TAB_SHOWN_EVENT, on)
    return () => window.removeEventListener(TAB_SHOWN_EVENT, on)
  }, [load])
  if (err) return <ErrorState compact message={err} onRetry={load} />
  if (!people) return <RabbitLoader className="py-4" label="Loading friends" />
  const list = people.filter((p) => !skip.includes(p.id))
  if (!list.length) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-[0.7647rem] text-(--text-muted)">Groups are for friends who follow you back. Follow each other first, then come back to pick them.</p>
        <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.7647rem]" onClick={() => openPlace('people')}>
          <UserPlus className="size-4" aria-hidden /> Find friends
        </Button>
      </div>
    )
  }
  const toggle = (id: string) => onPick(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id])
  const term = q.trim().toLowerCase()
  const shown = term ? list.filter((p) => p.name.toLowerCase().includes(term)) : list
  const chosen = list.filter((p) => picked.includes(p.id))
  return (
    <section aria-label="People in the group" className="flex flex-col gap-2">
      <p className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
        People {picked.length > 0 && `· ${picked.length} picked`}
      </p>
      {chosen.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Picked">
          {chosen.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => toggle(p.id)} aria-label={`Remove ${p.name}`}
                className="hit-44 inline-flex items-center gap-1.5 rounded-full bg-(--accent-subtle) py-1 pl-1 pr-2.5 text-[0.7647rem] font-medium text-(--accent)">
                <PersonAvatar u={p} size={22} />{p.name}<X className="size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      {list.length > 6 && (
        <label className="flex h-11 items-center gap-2 rounded-full border border-(--border) bg-(--bg-surface) px-3.5 focus-within:ring-1 focus-within:ring-(--accent)">
          <SearchIcon className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
          <input type="text" inputMode="search" value={q} onChange={(e) => setQ(e.target.value.slice(0, 40))} placeholder="Search friends"
            aria-label="Search friends" className="min-w-0 flex-1 bg-transparent text-[0.8235rem] text-(--text) outline-none placeholder:text-(--text-muted)" />
        </label>
      )}
      <ul className="flex flex-col divide-y divide-(--border) overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
        {shown.map((p) => {
          const on = picked.includes(p.id)
          return (
            <li key={p.id}>
              <button type="button" role="checkbox" aria-checked={on} onClick={() => toggle(p.id)}
                className={cn('flex min-h-12 w-full items-center gap-3 px-3.5 py-2 text-left active:bg-(--bg-inset)', on && 'bg-(--accent-subtle)')}>
                <PersonAvatar u={p} size={30} />
                <span className="min-w-0 flex-1 truncate text-[0.8235rem] text-(--text)">{p.name}</span>
                <span aria-hidden className={cn('flex size-6 shrink-0 items-center justify-center rounded-full border',
                  on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')}>
                  {on && <Check className="size-3.5" />}
                </span>
              </button>
            </li>
          )
        })}
        {shown.length === 0 && <li className="px-3.5 py-3 text-[0.7647rem] text-(--text-muted)">No friends match “{q.trim()}”.</li>}
      </ul>
    </section>
  )
}

/** One consistent "are you sure?" for leaving, removing and deleting (no browser pop-ups). */
function ConfirmSheet({ title, body, action, onConfirm, onClose }: {
  title: string; body: string; action: string; onConfirm: () => Promise<void>; onClose: () => void
}) {
  const [busy, setBusy] = useState(false)
  return (
    <Sheet title={title} onClose={onClose} portal
      footer={
        <div className="flex gap-2">
          <Button variant="default" className="h-11 flex-1 text-[0.7647rem]" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="destructive" className="h-11 flex-1 text-[0.7647rem]" loading={busy}
            onClick={() => { setBusy(true); void onConfirm().finally(() => setBusy(false)) }}>{action}</Button>
        </div>
      }>
      <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">{body}</p>
    </Sheet>
  )
}

function AddPeopleSheet({ group, onClose, onAdded }: { group: FeedGroup; onClose: () => void; onAdded: (g: FeedGroup) => void }) {
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const have = group.members.map((m) => m?.id ?? '')
  async function add(el: HTMLElement) {
    setBusy(true); setErr(null)
    try { const r = await addToGroup(group.id, picked); burst(el, 'kudos'); onAdded(r.group) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Sheet title={`Add to ${group.name}`} onClose={onClose} bodyClassName="settings flex flex-col gap-3 overflow-y-auto p-4"
      footer={
        <div className="flex flex-col gap-1.5">
          {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
          <Button variant="primary" className="h-12 text-[0.8235rem]" loading={busy} disabled={!picked.length} onClick={(e) => void add(e.currentTarget)}>
            {picked.length ? `Add ${picked.length} to the group` : 'Pick people to add'}
          </Button>
        </div>
      }>
      <FriendPicker picked={picked} onPick={setPicked} skip={have} />
    </Sheet>
  )
}

/** A group's page: its feed, members, invite more, leave (owner: edit, remove, delete). */
export function GroupPage({ id, imperial, onClose, onChanged }: {
  id: string; imperial: boolean; onClose: () => void; onChanged?: () => void
}) {
  const [g, setG] = useState<FeedGroup | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [view, setView] = useState<'feed' | 'members'>('feed')
  const [sheet, setSheet] = useState<'edit' | 'add' | null>(null)
  const [confirm, setConfirm] = useState<{ title: string; body: string; action: string; run: () => Promise<void> } | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const load = useCallback(() => getGroup(id).then((r) => { setG(r.group); setError(null) }, (e) => setError((e as Error).message)), [id])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, done?: () => void) {
    setMsg(null)
    try { await fn(); onChanged?.(); setConfirm(null); if (done) done(); else void load() }
    catch (e) { setConfirm(null); setMsg({ text: (e as Error).message, ok: false }) }
  }
  const seg = (
    <div role="tablist" aria-label="Group" className="mx-auto mt-2 flex max-w-xl gap-1 rounded-full bg-(--bg-inset) p-0.5">
      {([['feed', 'Feed'], ['members', 'Members']] as const).map(([v, label]) => (
        <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
          className={cn('min-h-11 flex-1 rounded-full text-[0.7059rem] font-medium', view === v ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>
          {label}{v === 'members' && g ? ` · ${g.count}` : ''}
        </button>
      ))}
    </div>
  )
  return (
    <Screen title={g ? `${g.emoji} ${g.name}` : 'Group'} subtitle={g ? `${g.count} of ${g.max} · only the group sees posts here` : undefined}
      closing={closing} onBack={close} onClose={close} headerExtra={seg}>
      {error && <ErrorState compact message={error} onRetry={() => void load()} />}
      {!g && !error && <RabbitLoader className="py-10" label="Loading group" />}
      {msg && <p className={cn('px-1 text-[0.7647rem]', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</p>}
      {g && view === 'feed' && <CommunityFeed imperial={imperial} groupId={g.id} groupName={g.name} />}
      {g && view === 'members' && (
        <>
          <Button variant="primary" className="h-11 gap-1.5 text-[0.7647rem]" onClick={() => setSheet('add')}>
            <UserPlus className="size-4" /> Invite friends
          </Button>
          <Group label="Members">
            {g.members.length === 0 && <EmptyRabbit size={40} mode="peek" title="Just you so far" body="Invite friends who follow you back." />}
            {g.members.map((m, i) => (
              <Row key={m?.id ?? i} icon={<PersonAvatar u={m} size={30} />} title={m?.name ?? 'Member'}
                subtitle={m?.id === g.owner_id ? 'Owner' : undefined}
                trailing={g.owner && m && m.id !== g.owner_id ? (
                  <Button variant="ghost" className="h-11 w-11 p-0" aria-label={`Remove ${m.name}`}
                    onClick={() => setConfirm({ title: `Remove ${m.name}?`, body: `${m.name} won't see ${g.name}'s posts any more. You can add them back later.`,
                      action: 'Remove', run: () => act(() => removeFromGroup(g.id, m.id)) })}>
                    <X className="size-4" />
                  </Button>
                ) : undefined} />
            ))}
          </Group>
          <Group>
            {g.owner && <Row icon={<Pencil className="size-4" />} title="Rename or change emoji" onClick={() => setSheet('edit')} />}
            <Row icon={<LogOut className="size-4" />} title="Leave group" danger
              onClick={() => setConfirm({ title: `Leave ${g.name}?`, body: "You won't see its posts any more. A member can add you back.",
                action: 'Leave group', run: () => act(() => leaveGroup(g.id), close) })} />
            {g.owner && (
              <Row icon={<Trash2 className="size-4" />} title="Delete group" danger
                onClick={() => setConfirm({ title: `Delete ${g.name}?`, body: 'The group goes away for everyone. Posts stay with their authors, seen by nobody else.',
                  action: 'Delete group', run: () => act(() => deleteGroup(g.id), close) })} />
            )}
          </Group>
        </>
      )}
      {confirm && <ConfirmSheet title={confirm.title} body={confirm.body} action={confirm.action} onConfirm={confirm.run} onClose={() => setConfirm(null)} />}
      {sheet === 'edit' && g && <GroupSheet initial={g} onClose={() => setSheet(null)} onSaved={(ng) => { setG(ng); setSheet(null); onChanged?.() }} />}
      {sheet === 'add' && g && <AddPeopleSheet group={g} onClose={() => setSheet(null)}
        onAdded={(ng) => { setG(ng); setSheet(null); setMsg({ text: 'Added. They can see the group now.', ok: true }) }} />}
    </Screen>
  )
}
