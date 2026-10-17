// A shared training block (server: blocks.py): a page in the stack. "new" = the create flow
// (pick a block, a start Monday, the crew, your plan); otherwise the block: week N of M, the
// group ring, each member's sessions done/planned this week (nothing else), one-tap cheers,
// the weekly check-in and the block's own feed (Community posts to club:b-<id>).
import { useEffect, useState } from 'react'
import { Check, LogOut, Megaphone, UserPlus, Users } from 'lucide-react'
import { Screen, Card, Field, Chip, ChipRow, OptionCard, inputCls } from '@/components/plan/ui'
import { Group, Icon, Row, Switch } from '@/components/settings/Grouped'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { WeekRing } from '@/components/progress/Progress'
import { PersonAvatar, CommunityFeed } from '@/components/community/Feed'
import { burst } from '@/components/anim'
import { cn } from '@/lib/utils'
import { useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { DraftRestored, useUnsavedGuard } from '@/components/ui/UnsavedGuard'
import {
  FEELS, FEEL_LABEL, declineBlock, endBlock, fmtDay, getBlock, getBlockNew, inviteToBlock,
  joinBlock, leaveBlock, needsPlanChoice, nudgeInBlock, setBlockCheckins, weekLine,
  type BlockCheckin, type BlockDetail, type BlockNew, type BlockPerson, type CreateBody, type Feel, type PlanChoice,
} from '@/lib/blocks'

export function BlockScreen({ id, imperial, onClose }: { id: string; imperial: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState(id)
  useEffect(() => setCurrent(id), [id])
  return current === 'new'
    ? <CreateBlock onClose={onClose} onCreated={setCurrent} />
    : <BlockPage id={current} imperial={imperial} onClose={onClose} />
}

// ---------------------------------------------------------------- create --
function CreateBlock({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [info, setInfo] = useState<BlockNew | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Choices are kept as a draft (lib/drafts) until the block starts or they're discarded.
  type B = { pick: string | null; start: string | null; crew: string[]; club: string | null; plan: 'new' | 'keep' | null }
  const [f, setF, draft] = useDraft<B>('block.new', { pick: null, start: null, crew: [], club: null, plan: null },
    { label: 'new block', isEmpty: (v) => !v.pick && !v.crew.length && !v.club })
  const { pick, start, crew, club, plan } = f
  const setPick = (pick: string | null) => setF((x) => ({ ...x, pick }))
  const setStart = (start: string | null) => setF((x) => ({ ...x, start }))
  const setCrew = (fn: (c: string[]) => string[]) => setF((x) => ({ ...x, crew: fn(x.crew) }))
  const setClub = (club: string | null) => setF((x) => ({ ...x, club }))
  const setPlan = (plan: 'new' | 'keep' | null) => setF((x) => ({ ...x, plan }))
  const guard = useUnsavedGuard(draft.dirty && !!(pick || crew.length || club), draft.discard)
  const [busy, setBusy] = useState(false)
  const [queued, setQueued] = useState(false)
  useEffect(() => {
    getBlockNew().then((r) => {
      setInfo(r)
      // A restored start that's no longer offered falls back to the first one (not a user edit).
      setF((x) => (x.start && r.starts.includes(x.start) ? x : { ...x, start: r.starts[0] ?? null }))
    }, (e) => setError((e as Error).message))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const hasGoal = !!info?.current.has_goal
  const ready = !!pick && !!start && (!hasGoal || !!plan)

  async function go() {
    if (!pick || !start) return
    setBusy(true); setError(null)
    const body: CreateBody = pick.startsWith('race:')
      ? { template: 'race', event_id: pick.slice(5), start }
      : { template: pick, start }
    body.invite = crew
    body.club = club
    body.plan = hasGoal ? (plan ?? undefined) : 'new'
    if (hasGoal && plan === 'new') body.confirm_replace = true
    setQueued(false)
    try {
      const r = await saveDurably<{ block: BlockDetail }>({ method: 'POST', path: '/api/blocks', body, label: 'block' },
        () => setQueued(true))
      draft.clear()
      onCreated(r.block.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false); setQueued(false)
    }
  }

  return (
    <Screen title="Start a block" subtitle="Same weeks, your own plans" onClose={guard.wrap(onClose)}
      footer={info ? (
        <div className="flex flex-col gap-2 px-4 pb-[max(12px,env(safe-area-inset-bottom))] pt-3">
          {error && <p role="alert" className="text-[0.7647rem] text-(--danger)">{error}</p>}
          {queued && <SaveStatus state="queued" />}
          <Button variant="primary" size="lg" className="hit-44 w-full" disabled={!ready || busy} loading={busy} onClick={() => void go()}>
            {crew.length || club ? 'Start and invite' : 'Start the block'}
          </Button>
        </div>
      ) : undefined}>
      <div className="mx-auto flex w-full max-w-xl flex-col gap-4 p-4">
        {guard.dialog}
        {draft.restored && <DraftRestored onDiscard={draft.discard} />}
        {!info && !error && <RabbitLoader className="py-10" label="Loading" cycle={['Lacing up', 'Finding your crew', 'Counting Mondays']} />}
        {!info && error && <ErrorState message={error} />}
        {info && (
          <>
            <Card>
              <Field label="Pick a block">
                <div className="flex flex-col gap-2">
                  {info.templates.map((t) => (
                    <OptionCard key={t.id} selected={pick === t.id} title={t.name} description={t.blurb} onClick={() => setPick(t.id)} />
                  ))}
                  {info.races.map((r) => (
                    <OptionCard key={r.id} selected={pick === `race:${r.id}`} title={`Our race: ${r.name}`}
                      description={`Everyone's plan targets ${fmtDay(r.date)} · about ${r.weeks} weeks`}
                      onClick={() => setPick(`race:${r.id}`)} />
                  ))}
                </div>
              </Field>
            </Card>
            <Card>
              <Field label="Start Monday" hint="Everyone's week 1 starts the same day.">
                <ChipRow>
                  {info.starts.map((s) => <Chip key={s} selected={start === s} onClick={() => setStart(s)}>{fmtDay(s)}</Chip>)}
                </ChipRow>
              </Field>
            </Card>
            <Card>
              <Field label="Who's in" hint={info.friends.length ? `Friends who follow you back. Up to ${info.max_members} people.` : 'Invite friends from Local → People first: they need to follow you back.'}>
                {info.friends.length > 0 && (
                  <ChipRow>
                    {info.friends.map((f) => (
                      <Chip key={f.id} selected={crew.includes(f.id)}
                        onClick={() => setCrew((c) => c.includes(f.id) ? c.filter((x) => x !== f.id) : [...c, f.id])}>
                        <span className="inline-flex items-center gap-1.5"><PersonAvatar u={f} size={20} />{f.name}</span>
                      </Chip>
                    ))}
                  </ChipRow>
                )}
              </Field>
              {info.clubs.length > 0 && (
                <Field label="Or open it to a club" hint="Club members can join without an invite.">
                  <ChipRow>
                    {info.clubs.map((c) => <Chip key={c.id} selected={club === c.id} onClick={() => setClub(club === c.id ? null : c.id)}>{c.name}</Chip>)}
                  </ChipRow>
                </Field>
              )}
            </Card>
            <PlanPick current={info.current} value={plan} onChange={setPlan} />
          </>
        )}
      </div>
    </Screen>
  )
}

/** Keep my plan, or build my own block plan (replaces the current goal, which is archived). */
function PlanPick({ current, value, onChange }: {
  current: BlockNew['current']; value: 'new' | 'keep' | null; onChange: (v: 'new' | 'keep') => void
}) {
  if (!current.has_goal) {
    return (
      <p className="px-1 text-[0.7647rem] leading-snug text-(--text-muted)">
        Rabbit builds your own plan for the block from your profile: your days, your paces, your volume.
      </p>
    )
  }
  return (
    <Card>
      <Field label="Your plan" hint="Nothing changes until you choose.">
        <div className="flex flex-col gap-2">
          <OptionCard selected={value === 'keep'} title={`Keep ${current.goal ?? 'my plan'}`}
            description="The block counts the sessions you already have planned." onClick={() => onChange('keep')} />
          <OptionCard selected={value === 'new'} title="Build me a block plan"
            description={`Replaces ${current.goal ?? 'your current goal'} as your active goal. It's archived, not deleted.`}
            onClick={() => onChange('new')} />
        </div>
      </Field>
    </Card>
  )
}

// ------------------------------------------------------------------ page --
function BlockPage({ id, imperial, onClose }: { id: string; imperial: boolean; onClose: () => void }) {
  const [b, setB] = useState<BlockDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)        // a polite status line
  const load = () => getBlock(id).then((r) => { setB(r.block); setError(null) }, (e) => setError((e as Error).message))
  useEffect(() => { setB(null); void load() }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Screen title={b?.name ?? 'Training block'} subtitle={b ? weekLine(b.week) : undefined} onClose={onClose}>
      <div className="mx-auto flex w-full max-w-xl flex-col gap-4 p-4">
        <p role="status" aria-live="polite" className={cn('text-[0.7647rem] text-(--accent)', !note && 'sr-only')}>{note}</p>
        {!b && !error && <RabbitLoader className="py-10" label="Loading" cycle={['Gathering the crew', 'Counting workouts']} />}
        {!b && error && <ErrorState message={error} onRetry={() => void load()} />}
        {b && !b.member && <Invite b={b} onJoined={(x) => setB(x)} onDeclined={onClose} />}
        {b && b.member && (
          <>
            <GroupHero b={b} />
            <Crew b={b} onChanged={setB} onNote={setNote} />
            {b.week.state !== 'upcoming' && <CheckIn b={b} onChanged={setB} onNote={setNote} />}
            {b.feed && (
              <section className="flex flex-col gap-2">
                <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Block feed</h2>
                <CommunityFeed imperial={imperial} clubId={b.feed} clubName={b.name} />
              </section>
            )}
            <Manage b={b} onChanged={setB} onLeft={onClose} onNote={setNote} />
          </>
        )}
      </div>
    </Screen>
  )
}

function GroupHero({ b }: { b: BlockDetail }) {
  const g = b.group
  return (
    <Card className="flex items-center gap-4 p-4">
      {g && g.target > 0 ? <WeekRing done={g.done} target={g.target} size={64} />
        : <span className="flex size-16 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)"><Users className="size-6" /></span>}
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[0.6471rem] uppercase tracking-widest text-(--text-muted)">
          {b.week.state === 'upcoming' ? 'Starts soon' : 'Together this week'}
        </p>
        {b.week.state === 'upcoming' ? (
          <p className="text-[0.9412rem] font-medium text-(--text)">Week 1 starts {fmtDay(b.week.monday)}</p>
        ) : g ? (
          <>
            <p className="text-[0.9412rem] font-medium text-(--text)">{g.done} of {g.target} sessions</p>
            <p className="text-[0.7647rem] text-(--text-muted)">{g.closed} of {g.count} closed their week</p>
          </>
        ) : null}
        {b.event && <p className="mt-0.5 truncate text-[0.7059rem] text-(--text-muted)">Race day: {b.event.name} · {fmtDay(b.event.date)}</p>}
        {(b.cheers?.length ?? 0) > 0 && (
          <p className="mt-1 flex items-center gap-1 text-[0.7059rem] text-(--accent)">
            <Megaphone className="size-3.5" aria-hidden />{cheerLine(b.cheers!)}
          </p>
        )}
      </div>
    </Card>
  )
}

const cheerLine = (cs: { name: string }[]) => {
  const names = [...new Set(cs.map((c) => c.name))]
  return names.length === 1 ? `${names[0]} cheered you on` : `${names[0]} and ${names.length - 1} more cheered you on`
}

function Crew({ b, onChanged, onNote }: { b: BlockDetail; onChanged: (b: BlockDetail) => void; onNote: (s: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  async function cheer(p: BlockPerson, el: HTMLElement) {
    setBusy(p.user_id)
    try {
      await nudgeInBlock(b.id, p.user_id)
      burst(el, 'kudos')
      onNote(`Cheered ${p.name} on`)
      const r = await getBlock(b.id); onChanged(r.block)
    } catch (e) {
      onNote((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  return (
    <Group label="The crew" footer="Only sessions done and planned this week. Never heart rate or health data.">
      {(b.people ?? []).map((p) => (
        <div key={p.user_id} className="settings-row flex items-center gap-3 px-4 py-2.5">
          <PersonAvatar u={p.user} size={36} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[0.9412rem] text-(--text)">{p.me ? 'You' : p.name}{p.owner ? ' · owner' : ''}</span>
            <span className="block text-[0.7647rem] text-(--text-muted)">
              {p.target == null ? 'No numbers yet' : p.closed ? 'Week closed' : `${p.done} of ${p.target} sessions`}
            </span>
          </span>
          {p.target != null && <WeekRing done={p.done ?? 0} target={p.target} size={32} />}
          {!p.me && p.behind && b.status === 'active' && (
            <button type="button" disabled={p.cheered || busy === p.user_id}
              onClick={(e) => void cheer(p, e.currentTarget)}
              className="hit-44 inline-flex min-h-11 items-center rounded-full px-1 disabled:opacity-50">
              <span className="rounded-full border border-(--accent)/40 bg-(--accent-subtle) px-3 py-1.5 text-[0.7059rem] font-medium text-(--accent)">
                {p.cheered ? 'Cheered' : 'Cheer'}
              </span>
            </button>
          )}
        </div>
      ))}
    </Group>
  )
}

function CheckIn({ b, onChanged, onNote }: { b: BlockDetail; onChanged: (b: BlockDetail) => void; onNote: (s: string) => void }) {
  const mine = b.my_checkin
  // The note is kept as a draft per block + week until it's shared.
  const [c, setC, draft] = useDraft<{ feel: Feel | null; text: string }>(`blockcheckin.${b.id}.${b.week.n}`,
    { feel: mine?.feel ?? null, text: mine?.note ?? '' }, { label: 'block check-in' })
  const { feel, text } = c
  const setFeel = (feel: Feel) => setC((x) => ({ ...x, feel }))
  const setText = (text: string) => setC((x) => ({ ...x, text }))
  const [busy, setBusy] = useState(false)
  const [queued, setQueued] = useState(false)
  const shown: BlockCheckin[] = (b.checkins?.length ? b.checkins : b.last_checkins) ?? []
  const lastWeek = !b.checkins?.length && (b.last_checkins?.length ?? 0) > 0
  async function share() {
    if (!feel) return
    setBusy(true); setQueued(false)
    try {
      const r = await saveDurably<{ block: BlockDetail }>({ method: 'POST', path: `/api/blocks/${b.id}/checkin`,
        body: { feel, note: text.trim() }, label: 'block check-in', coalesce: `blockcheckin.${b.id}` }, () => setQueued(true))
      draft.clear(); onChanged(r.block); onNote('Shared with your crew')
    }
    catch (e) { onNote((e as Error).message) }
    finally { setBusy(false); setQueued(false) }
  }
  return (
    <Card>
      <Field label={`How's week ${b.week.n} going?`} hint="Your crew sees how it felt and your note.">
        <ChipRow>
          {FEELS.map(([k, label]) => <Chip key={k} selected={feel === k} onClick={() => setFeel(k)}>{label}</Chip>)}
        </ChipRow>
        <input className={inputCls} maxLength={140} placeholder="Add a short note (optional)" value={text} onChange={(e) => setText(e.target.value)} />
        <Button variant="primary" className="hit-44 self-start" disabled={!feel || busy} loading={busy} onClick={() => void share()}>
          {mine ? 'Update check-in' : 'Share check-in'}
        </Button>
        {queued && <SaveStatus state="queued" />}
      </Field>
      {shown.length > 0 && (
        <ul className="flex flex-col border-t border-(--border)">
          {lastWeek && <li className="px-4 pt-2.5 font-mono text-[0.6471rem] uppercase tracking-widest text-(--text-muted)">Last week</li>}
          {shown.map((c) => (
            <li key={c.user_id} className="flex items-start gap-2.5 px-4 py-2.5">
              <PersonAvatar u={c.user} size={28} />
              <span className="min-w-0 flex-1 text-[0.8235rem] text-(--text)">
                <span className="font-medium">{c.me ? 'You' : c.name}</span> · {FEEL_LABEL[c.feel]}
                {c.note && <span className="block text-[0.7647rem] text-(--text-secondary)">{c.note}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Manage({ b, onChanged, onLeft, onNote }: {
  b: BlockDetail; onChanged: (b: BlockDetail) => void; onLeft: () => void; onNote: (s: string) => void
}) {
  const [confirm, setConfirm] = useState<'leave' | 'end' | null>(null)
  const [inviting, setInviting] = useState(false)
  async function toggle(on: boolean) {
    onChanged({ ...b, checkins_on: on })
    try { await setBlockCheckins(b.id, on) } catch (e) { onChanged({ ...b }); onNote((e as Error).message) }
  }
  async function act() {
    try {
      if (confirm === 'leave') { await leaveBlock(b.id); onLeft() }
      else if (confirm === 'end') { await endBlock(b.id); const r = await getBlock(b.id); onChanged(r.block); onNote('Block ended. Your plans stay yours.') }
    } catch (e) { onNote((e as Error).message) }
    setConfirm(null)
  }
  return (
    <>
      <Group footer="Leaving or ending never touches your plan.">
        <Row title="Sunday check-in" subtitle="A one-tap question Sunday afternoon (never in quiet hours)"
          trailing={<Switch label="Sunday check-in" checked={b.checkins_on !== false} onChange={(v) => void toggle(v)} />} />
        {b.owner && b.status === 'active' && (
          <Row icon={<Icon><UserPlus /></Icon>} title="Invite friends" onClick={() => setInviting(true)} />
        )}
        <Row icon={<Icon tone="danger"><LogOut /></Icon>} title="Leave block" danger onClick={() => setConfirm('leave')} />
        {b.owner && b.status === 'active' && <Row icon={<Icon tone="danger"><Check /></Icon>} title="End block for everyone" danger onClick={() => setConfirm('end')} />}
      </Group>
      {confirm && (
        <Sheet title={confirm === 'leave' ? 'Leave this block?' : 'End this block?'} onClose={() => setConfirm(null)}
          bodyClassName="flex flex-col gap-3 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <p className="text-[0.8235rem] text-(--text-secondary)">
            {confirm === 'leave' ? 'Your plan stays yours. You can be invited again later.' : 'Everyone keeps their own plan; the block page stops counting.'}
          </p>
          <Button variant="destructive" size="lg" className="hit-44 w-full" onClick={() => void act()}>
            {confirm === 'leave' ? 'Leave block' : 'End block'}
          </Button>
        </Sheet>
      )}
      {inviting && <InviteSheet b={b} onClose={() => setInviting(false)} onDone={(x) => { onChanged(x); setInviting(false); onNote('Invites sent') }} />}
    </>
  )
}

function InviteSheet({ b, onClose, onDone }: { b: BlockDetail; onClose: () => void; onDone: (b: BlockDetail) => void }) {
  const [info, setInfo] = useState<BlockNew | null>(null)
  const [pick, setPick] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getBlockNew().then(setInfo, (e) => setError((e as Error).message)) }, [])
  const taken = new Set([...(b.people ?? []).map((p) => p.user_id), ...(b.invited ?? []).map((u) => u?.id)])
  const open = (info?.friends ?? []).filter((f) => !taken.has(f.id))
  async function send() {
    try { const r = await inviteToBlock(b.id, pick); onDone(r.block) } catch (e) { setError((e as Error).message) }
  }
  return (
    <Sheet title="Invite friends" onClose={onClose} bodyClassName="flex flex-col gap-3 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      {error && <ErrorState compact message={error} />}
      {!info && !error && <RabbitLoader inline label="Loading" />}
      {info && open.length === 0 && <p className="text-[0.8235rem] text-(--text-muted)">Everyone who follows you back is already in or invited.</p>}
      <ChipRow>
        {open.map((f) => (
          <Chip key={f.id} selected={pick.includes(f.id)} onClick={() => setPick((p) => p.includes(f.id) ? p.filter((x) => x !== f.id) : [...p, f.id])}>
            <span className="inline-flex items-center gap-1.5"><PersonAvatar u={f} size={20} />{f.name}</span>
          </Chip>
        ))}
      </ChipRow>
      <Button variant="primary" size="lg" className="hit-44 w-full" disabled={!pick.length} onClick={() => void send()}>Send invites</Button>
    </Sheet>
  )
}

// ---------------------------------------------------------------- invite --
function Invite({ b, onJoined, onDeclined }: { b: BlockDetail; onJoined: (b: BlockDetail) => void; onDeclined: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [choose, setChoose] = useState<{ goal: string | null } | null>(null)
  async function join(c: PlanChoice) {
    setBusy(true); setError(null)
    try {
      const r = await joinBlock(b.id, c)
      setChoose(null)
      onJoined(r.block)
    } catch (e) {
      if (needsPlanChoice(e)) {
        const cur = await getBlockNew().then((x) => x.current, () => null)
        setChoose({ goal: cur?.goal ?? null })
      } else setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Card className="flex flex-col gap-3 p-4">
        {b.invited_by && (
          <p className="flex items-center gap-2 text-[0.8235rem] text-(--text-secondary)">
            <PersonAvatar u={b.invited_by} size={28} />{b.invited_by.name} invited you
          </p>
        )}
        {b.club && !b.invited_by && <p className="text-[0.8235rem] text-(--text-secondary)">Open to {b.club.name}</p>}
        <p className="text-[0.9412rem] text-(--text)">
          {b.weeks} weeks from {fmtDay(b.start)} · {b.members} {b.members === 1 ? 'person' : 'people'} so far
        </p>
        {b.event && <p className="text-[0.7647rem] text-(--text-muted)">Everyone trains for {b.event.name} on {fmtDay(b.event.date)}.</p>}
        <p className="text-[0.7647rem] text-(--text-muted)">You train on your own plan, built from your numbers, on the same weeks as the crew.</p>
        {error && <p role="alert" className="text-[0.7647rem] text-(--danger)">{error}</p>}
        <div className="flex gap-2">
          <Button variant="primary" size="lg" className="hit-44 flex-1" loading={busy} disabled={busy} onClick={() => void join({})}>Join the block</Button>
          {b.invited_by && (
            <Button variant="ghost" size="lg" className="hit-44" onClick={() => void declineBlock(b.id).then(onDeclined, () => onDeclined())}>Not now</Button>
          )}
        </div>
      </Card>
      {choose && (
        <Sheet title="Your plan for this block" onClose={() => setChoose(null)}
          bodyClassName="flex flex-col gap-2 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <p className="text-[0.8235rem] text-(--text-secondary)">You already have {choose.goal ?? 'a goal'}. Nothing changes until you pick.</p>
          <OptionCard selected={false} title={`Keep ${choose.goal ?? 'my plan'}`}
            description="Join and count the sessions you already have planned." onClick={() => void join({ plan: 'keep' })} />
          <OptionCard selected={false} title="Build me a block plan"
            description={`Replaces ${choose.goal ?? 'your goal'} as your active goal (archived, not deleted).`}
            onClick={() => void join({ plan: 'new', confirm_replace: true })} />
        </Sheet>
      )}
    </>
  )
}
