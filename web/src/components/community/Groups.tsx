// Feed groups (feedgroups.py): small private circles for the feed ("Saturday long run crew").
// Create one from mutual friends (max 50 people, 10 groups each), see its members and feed,
// invite more, leave; the owner renames, removes people or deletes it. Group posts are only
// seen by the group.
import { useCallback, useEffect, useState } from 'react'
import { Check, LogOut, Pencil, Trash2, UserPlus, X } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'
import { EmptyRabbit, burst } from '@/components/anim'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Sheet } from '@/components/ui/Sheet'
import { Group, Row } from '@/components/settings/Grouped'
import { Field, Screen, inputCls } from '@/components/plan/ui'
import type { SocialUser } from '@/lib/social'
import {
  addToGroup, createGroup, deleteGroup, getGroup, groupFriends, leaveGroup, removeFromGroup, updateGroup,
  type FeedGroup,
} from '@/lib/community2'
import { cn } from '@/lib/utils'
import { CommunityFeed, PersonAvatar } from './Feed'

const EMOJIS = ['👟', '🏃', '🌅', '🚴', '🏊', '⛰️', '🔥', '☕', '🍻', '🐇', '💪', '🏁']

/** Create a group, or rename it (``initial``). */
export function GroupSheet({ initial, onClose, onSaved }: {
  initial?: FeedGroup; onClose: () => void; onSaved: (g: FeedGroup) => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [emoji, setEmoji] = useState(initial?.emoji ?? '👟')
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function save(el: HTMLElement) {
    setBusy(true); setErr(null)
    try {
      const r = initial ? await updateGroup(initial.id, { name: name.trim(), emoji }) : await createGroup({ name: name.trim(), emoji, members: picked })
      if (!initial) burst(el, 'kudos')
      onSaved(r.group)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Sheet title={initial ? 'Edit group' : 'New group'} onClose={onClose}
      bodyClassName="flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <Field label="Name">
        <input className={inputCls} maxLength={40} value={name} autoFocus placeholder="Saturday long run crew" onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Emoji">
        {EMOJIS.map((e) => (
          <button key={e} type="button" role="radio" aria-checked={emoji === e} aria-label={`Emoji ${e}`} onClick={() => setEmoji(e)}
            className={cn('hit-44 flex size-10 items-center justify-center rounded-xl text-[1.2rem]', emoji === e ? 'bg-(--accent-subtle) ring-1 ring-(--accent)' : 'bg-(--bg-inset)')}>{e}</button>
        ))}
      </div>
      {!initial && <FriendPicker picked={picked} onPick={setPicked} />}
      <p className="text-[0.6471rem] text-(--text-muted)">Only people in the group see what you post to it. They can leave any time.</p>
      {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      <Button variant="primary" className="h-11 text-[0.7647rem]" loading={busy} disabled={!name.trim()} onClick={(e) => void save(e.currentTarget)}>
        {initial ? 'Save' : picked.length ? `Start group with ${picked.length}` : 'Start group'}
      </Button>
    </Sheet>
  )
}

function FriendPicker({ picked, onPick, skip = [] }: { picked: string[]; onPick: (ids: string[]) => void; skip?: string[] }) {
  const [people, setPeople] = useState<SocialUser[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    groupFriends().then((r) => setPeople(r.people.filter((p): p is SocialUser => !!p)), (e) => setErr((e as Error).message))
  }, [])
  if (err) return <ErrorState compact message={err} />
  if (!people) return <RabbitLoader className="py-4" label="Loading friends" />
  const list = people.filter((p) => !skip.includes(p.id))
  if (!list.length) {
    return <p className="text-[0.7647rem] text-(--text-muted)">Groups are for friends who follow you back. Add friends in People first.</p>
  }
  return (
    <Group label="Friends who follow you back">
      {list.map((p) => {
        const on = picked.includes(p.id)
        return (
          <Row key={p.id} icon={<PersonAvatar u={p} size={30} />} title={p.name}
            trailing={on ? <Check className="size-5 text-(--accent)" aria-hidden /> : undefined}
            onClick={() => onPick(on ? picked.filter((x) => x !== p.id) : [...picked, p.id])} />
        )
      })}
    </Group>
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
    <Sheet title={`Add to ${group.name}`} onClose={onClose}
      bodyClassName="flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <FriendPicker picked={picked} onPick={setPicked} skip={have} />
      {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
      <Button variant="primary" className="h-11 text-[0.7647rem]" loading={busy} disabled={!picked.length} onClick={(e) => void add(e.currentTarget)}>
        Add {picked.length || ''}
      </Button>
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
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const load = useCallback(() => getGroup(id).then((r) => { setG(r.group); setError(null) }, (e) => setError((e as Error).message)), [id])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, done?: () => void) {
    setMsg(null)
    try { await fn(); onChanged?.(); if (done) done(); else void load() } catch (e) { setMsg({ text: (e as Error).message, ok: false }) }
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
                    onClick={() => { if (window.confirm(`Remove ${m.name} from ${g.name}?`)) void act(() => removeFromGroup(g.id, m.id)) }}>
                    <X className="size-4" />
                  </Button>
                ) : undefined} />
            ))}
          </Group>
          <Group>
            {g.owner && <Row icon={<Pencil className="size-4" />} title="Rename group" onClick={() => setSheet('edit')} />}
            <Row icon={<LogOut className="size-4" />} title="Leave group" danger
              onClick={() => { if (window.confirm(`Leave ${g.name}? You won't see its posts any more.`)) void act(() => leaveGroup(g.id), close) }} />
            {g.owner && (
              <Row icon={<Trash2 className="size-4" />} title="Delete group" danger
                onClick={() => { if (window.confirm(`Delete ${g.name} for everyone? Posts stay with their authors, seen by nobody else.`)) void act(() => deleteGroup(g.id), close) }} />
            )}
          </Group>
        </>
      )}
      {sheet === 'edit' && g && <GroupSheet initial={g} onClose={() => setSheet(null)} onSaved={(ng) => { setG(ng); setSheet(null); onChanged?.() }} />}
      {sheet === 'add' && g && <AddPeopleSheet group={g} onClose={() => setSheet(null)}
        onAdded={(ng) => { setG(ng); setSheet(null); setMsg({ text: 'Added. They can see the group now.', ok: true }) }} />}
    </Screen>
  )
}
