// Coach side: your athletes, and for each one an overview, their plan, messages, notes,
// stats and (only if the athlete allowed it) their Rabbit chats.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarDays, ChevronRight, Eye, Lock, Map as MapIcon, MessageSquare, Pin, Plus, StickyNote, Trash2, Users } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { RabbitLogo } from '@/components/RabbitLogo'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Switch } from '@/components/settings/Grouped'
import { Card, Choice, Field, Screen, areaCls } from '@/components/plan/ui'
import { PlanEditor } from '@/components/plan/PlanEditor'
import { StatsBody } from '@/components/stats/StatsScreen'
import { cn } from '@/lib/utils'
import type { Me } from '@/lib/api'
import { fmtPace, KM_PER_MI, kgToLb, planApi } from '@/lib/plan'
import { fmtClimb } from '@/lib/format'
import { DISTANCE_LABEL, TYPE_LABEL, countdown, daysUntil } from '@/lib/events'
import {
  addNote, chatApi, coachBase, deleteNote, getAthlete, getAthleteStats, getAthletes, getRabbitThread, getRabbitThreads,
  timeAgo, updateNote, type AthleteCard, type AthleteOverview, type Note, type ThreadSummary,
} from '@/lib/coach'
import type { Stats } from '@/lib/stats'
import { photoUrl } from '@/lib/photo'
import type { RaceEvent } from '@/lib/events'
import { ThreadView } from './ThreadView'
import { RaceGradeLine } from '@/components/events/Readiness'
import { getAthleteReadiness, mainRace, type RaceGrade } from '@/lib/readiness'
import { ThreadList } from './CoachInbox'
import { PlanImportHub } from '@/components/plan/PlanImport'
import { importApi } from '@/lib/planimport'

/** Coach home: the athlete list. ``onClose`` when shown over an athlete's own app. */
export function CoachApp({ me, onClose, onSignOut }: { me: Me; onClose?: () => void; onSignOut?: () => void }) {
  const [athletes, setAthletes] = useState<AthleteCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const load = useCallback(() => {
    getAthletes().then((r) => setAthletes(r.athletes), (e) => setError((e as Error).message))
  }, [])
  useEffect(load, [load])

  const body = (
    <>
      {athletes === null && !error && <RabbitLoader className="py-16" label="Finding your athletes…" />}
      {error && <p className="px-1 text-[0.8235rem] text-(--danger)">{error}</p>}
      {athletes?.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <Users className="size-8 text-(--text-muted)" />
          <p className="text-[0.8824rem] text-(--text)">No athletes yet</p>
          <p className="max-w-xs text-[0.7647rem] text-(--text-muted)">Athletes add you from Settings › Coaches in their Rabbit app, using {me.profile.name ? 'your' : 'this'} Google email.</p>
        </div>
      )}
      {(athletes ?? []).map((a) => (
        <button key={a.athlete_id} type="button" onClick={() => setOpen(a.athlete_id)}
          className="flex w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
          <Avatar name={a.profile.name || 'Athlete'} picture={a.profile.picture} photo={photoUrl(a.photo, a.athlete_id)} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[0.9412rem] font-medium text-(--text)">{a.profile.name || 'Athlete'}</span>
            <span className="block truncate text-[0.7059rem] text-(--text-muted)">
              {a.goal ? `${a.goal.title}${a.goal.date ? ` · ${countdown(a.goal.date)}` : ''}` : 'No goal set'}
            </span>
          </span>
          {a.unread > 0 && <span className="rounded-full bg-(--accent) px-2 py-0.5 text-[0.6471rem] font-semibold text-(--on-fill)">{a.unread}</span>}
          <ChevronRight className="size-4 shrink-0 text-(--text-muted)" />
        </button>
      ))}
      {open && <AthleteDetail aid={open} onClose={() => { setOpen(null); load() }} />}
    </>
  )

  if (onClose) {
    return <Screen title="Your athletes" subtitle="Coaching" closing={closing} onClose={() => { setClosing(true); setTimeout(onClose, 200) }}>{body}</Screen>
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 items-center gap-2.5 border-b border-(--border) px-3 pb-2.5 pt-[max(10px,env(safe-area-inset-top))]">
        <span className="logo-tile flex size-[38px] shrink-0 items-center justify-center rounded-[11px] bg-(--brand) shadow-sm"><RabbitLogo size={32} /></span>
        <span className="min-w-0 flex-1">
          <span className="block font-display text-lg leading-tight text-(--brand)">Rabbit for coaches</span>
          <span className="block truncate text-[0.6471rem] text-muted-foreground">{me.profile.name || 'Coach'}</span>
        </span>
        {onSignOut && <Button variant="ghost" className="h-8 px-2 text-[0.7059rem]" onClick={onSignOut}>Sign out</Button>}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-xl flex-col gap-3 px-4 py-5">
          <h2 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Your athletes</h2>
          {body}
        </div>
      </div>
    </div>
  )
}

type Tab = 'overview' | 'plan' | 'stats' | 'messages' | 'notes' | 'rabbit'

function AthleteDetail({ aid, onClose }: { aid: string; onClose: () => void }) {
  const [o, setO] = useState<AthleteOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [closing, setClosing] = useState(false)
  const [planOpen, setPlanOpen] = useState(false)
  const [thread, setThread] = useState<string | null>(null)
  const api = useMemo(() => planApi(coachBase(aid)), [aid])
  const chat = useMemo(() => chatApi(`${coachBase(aid)}/chat`), [aid])
  const imports = useMemo(() => importApi(coachBase(aid)), [aid])
  const [planKey, setPlanKey] = useState(0)
  const load = useCallback(() => {
    getAthlete(aid).then(setO, (e) => setError((e as Error).message))
  }, [aid])
  useEffect(load, [load])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const name = o?.profile.name || 'Athlete'

  async function messageAbout(session?: { id: string }) {
    try {
      const r = await chat.open(session ? { session_id: session.id } : {})
      setThread(r.thread.id); setTab('messages'); setPlanOpen(false)
    } catch (e) { setError((e as Error).message) }
  }

  const tabs: [Tab, string][] = [['overview', 'Overview'], ['plan', 'Plan'], ['stats', 'Stats'], ['messages', 'Messages'], ['notes', 'Notes'],
    ...(o?.link.can_see_rabbit_chats ? [['rabbit', 'Rabbit'] as [Tab, string]] : [])]

  return (
    <>
      <Screen title={name} subtitle={o?.goal ? o.goal.title : undefined} closing={closing} onClose={close} onBack={close}
        headerExtra={
          <div className="no-scrollbar mx-auto mt-2.5 flex max-w-xl gap-1 overflow-x-auto rounded-lg bg-(--bg-elevated) p-1">
            {tabs.map(([t, l]) => (
              <button key={t} type="button" onClick={() => { setTab(t); setThread(null) }} aria-pressed={tab === t}
                className={cn('hit-44 h-8 shrink-0 flex-1 rounded-md px-2 text-[0.7059rem] font-medium', tab === t ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>
                {l}{t === 'messages' && o?.unread ? ` (${o.unread})` : ''}
              </button>
            ))}
          </div>}>
        {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
        {!o && !error && <RabbitLoader className="py-16" label="Reading their training…" />}
        {o && tab === 'overview' && <Overview o={o} onOpenPlan={() => setTab('plan')} onMessage={() => void messageAbout()} />}
        {o && tab === 'plan' && <PlanImportHub key={planKey} api={imports} plans={api} who="coach" athleteName={name} onOpenPlan={() => setPlanOpen(true)} onChanged={load} />}
        {o && tab === 'stats' && <AthleteStats aid={aid} />}
        {o && tab === 'messages' && (thread
          ? <><Button variant="ghost" className="h-8 w-fit px-2 text-[0.7059rem]" onClick={() => setThread(null)}>‹ All conversations</Button>
              <ThreadView api={chat} threadId={thread} me="coach" otherName={name.split(' ')[0]!} /></>
          : <Messages chat={chat} onOpen={setThread} onNew={() => void messageAbout()} name={name} />)}
        {o && tab === 'notes' && <Notes aid={aid} notes={o.notes} events={o.events} onChanged={load} myEmail={o.link.email} />}
        {o && tab === 'rabbit' && <RabbitChats aid={aid} />}
      </Screen>
      {planOpen && o && (
        <PlanEditor me={{} as Me} goalTitle={o.goal?.title ?? 'Race'} api={api} coachMode readOnly={!o.link.can_edit_plan}
          onClose={() => { setPlanOpen(false); setPlanKey((k) => k + 1) }} onRebuild={() => {}} onAsk={() => {}} onChanged={() => {}} onMeChanged={() => {}}
          onOpenEvents={() => {}} onMessage={(s) => void messageAbout(s)} messageLabel={`Message ${name.split(' ')[0]}`} />
      )}
    </>
  )
}

function Overview({ o, onOpenPlan, onMessage }: { o: AthleteOverview; onOpenPlan: () => void; onMessage: () => void }) {
  const a = o.athlete as Record<string, unknown>
  const imperial = a.units !== 'metric'
  const facts: [string, string | null][] = [
    ['Level', typeof a.level === 'string' ? ({ new: 'New', intermediate: 'A few seasons', advanced: 'Experienced' } as Record<string, string>)[a.level] ?? null : null],
    ['Hours now', typeof a.weekly_hours === 'number' ? `${a.weekly_hours} h/week` : null],
    ['Age', typeof a.age === 'number' ? String(a.age) : null],
    ['Weight', typeof a.weight_kg === 'number' ? (imperial ? `${kgToLb(a.weight_kg)} lb` : `${a.weight_kg} kg`) : null],
    ['Threshold HR', typeof a.threshold_hr === 'number' ? `${a.threshold_hr} bpm` : null],
    ['Max / rest HR', typeof a.max_hr === 'number' ? `${a.max_hr} / ${a.resting_hr ?? '?'} bpm` : null],
    ['FTP', typeof a.ftp_w === 'number' ? `${a.ftp_w} W` : null],
    ['Run threshold', typeof a.run_threshold_pace === 'number' ? `${fmtPace(imperial ? a.run_threshold_pace * KM_PER_MI : a.run_threshold_pace)}/${imperial ? 'mi' : 'km'}` : null],
    ['Swim CSS', typeof a.swim_css === 'number' ? `${fmtPace(a.swim_css)}/100m` : null],
    ['Training days', Array.isArray(a.available_days) ? (a.available_days as string[]).join(', ') : null],
    ['Favorite sports', Array.isArray(a.favorite_sports) && (a.favorite_sports as string[]).length ? (a.favorite_sports as string[]).join(', ').replace(/_/g, ' ') : null],
  ]
  const upcoming = o.events.filter((e) => daysUntil(e.date) >= 0)
  const elev = typeof a.home_elevation_m === 'number' ? fmtClimb(a.home_elevation_m, imperial) : null
  const list = (v: unknown) => Array.isArray(v) && v.length ? (v as string[]).join(', ').replace(/_/g, ' ') : null
  facts.push(
    ['Home', [typeof a.home_location === 'string' && a.home_location ? a.home_location : null, elev].filter(Boolean).join(' · ') || null],
    ['Years training', typeof a.years_training === 'number' ? String(a.years_training) : null],
    ['Strengths', list(a.strengths)],
    ['Limiters', list(a.limiters)],
    ['Heat / sweat', [typeof a.heat_tolerance === 'string' ? `${a.heat_tolerance} heat tolerance` : null, typeof a.sweat === 'string' ? `${a.sweat} sweater` : null].filter(Boolean).join(', ') || null],
    ['Season goal', typeof a.season_goal === 'string' && a.season_goal ? a.season_goal : null],
  )
  return (
    <>
      <div className="flex items-center gap-3 px-1">
        <Avatar name={o.profile.name || 'Athlete'} picture={o.profile.picture} photo={photoUrl(o.photo, o.athlete_id)} size={48} />
        <span className="min-w-0 flex-1 truncate text-[0.9412rem] font-medium text-(--text)">{o.profile.name || 'Athlete'}</span>
      </div>
      <div className="flex gap-2">
        <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={onOpenPlan}><MapIcon className="size-4" /> Plan</Button>
        <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={onMessage}><MessageSquare className="size-4" /> Message</Button>
      </div>
      {!o.link.can_edit_plan && <p className="px-1 text-[0.7059rem] text-(--text-muted)"><Lock className="inline size-3" /> View only: the athlete hasn't given you edit access to the plan.</p>}
      <AthleteGrade aid={o.athlete_id} />
      {upcoming.length > 0 && (
        <Card>
          <Field label="Events">
            <div className="flex flex-col gap-2">
              {upcoming.map((e) => (
                <div key={e.id} className="flex items-center gap-2 text-[0.8235rem]">
                  <CalendarDays className="size-4 shrink-0 text-(--accent)" />
                  <span className="min-w-0 flex-1 truncate">{e.main ? '★ ' : ''}{e.name}</span>
                  <span className="shrink-0 text-[0.7059rem] text-(--text-muted)">
                    {TYPE_LABEL[e.type]}{e.distance && e.distance !== 'other' ? ` · ${DISTANCE_LABEL[e.distance] ?? e.distance}` : ''} · {countdown(e.date)}{e.main ? '' : ` · ${e.priority}`}
                  </span>
                </div>
              ))}
            </div>
          </Field>
        </Card>
      )}
      {(o.checkins?.length ?? 0) > 0 && (
        <Card>
          <Field label="Recent check-ins">
            <ul className="flex flex-col gap-1.5">
              {o.checkins!.map((c, i) => (
                <li key={`${c.date}-${i}`} className="flex gap-2 text-[0.7647rem]">
                  <span className="w-16 shrink-0 text-(--text-muted)">{c.date.slice(5)}</span>
                  <span className={cn('min-w-0 flex-1', c.pain_flag ? 'text-(--warning-text)' : 'text-(--text)')}>
                    {c.summary}{c.feel != null ? ` (feel ${c.feel}/5)` : ''}{c.pain_flag ? ' · pain flagged' : ''}
                  </span>
                </li>
              ))}
            </ul>
          </Field>
        </Card>
      )}
      <Card>
        <Field label="Profile">
          <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-[0.7647rem]">
            {facts.filter(([, v]) => v).map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-(--text-muted)">{k}</dt><dd className="text-(--text)">{v}</dd></div>
            ))}
          </dl>
        </Field>
        {typeof a.injuries === 'string' && a.injuries && (
          <Field label="Injuries or limits" className="border-t border-(--border)"><p className="text-[0.8235rem] text-(--text)">{a.injuries}</p></Field>
        )}
      </Card>
    </>
  )
}

/** The athlete's main race readiness grade (deterministic, from their Garmin training and plan). */
function AthleteGrade({ aid }: { aid: string }) {
  const [g, setG] = useState<RaceGrade | null>(null)
  useEffect(() => { getAthleteReadiness(aid).then((r) => setG(mainRace(r.races)), () => setG(null)) }, [aid])
  if (!g) return null
  return <Card><Field label="Race readiness"><div className="-mx-4 -my-3"><RaceGradeLine g={g} /></div></Field></Card>
}

function AthleteStats({ aid }: { aid: string }) {
  const [s, setS] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getAthleteStats(aid).then(setS, (e) => setError((e as Error).message)) }, [aid])
  if (error) return <p className="px-1 text-[0.7647rem] text-(--danger)">{error}</p>
  if (!s) return <RabbitLoader className="py-16" label="Loading their stats" />
  return <StatsBody s={s} loadBase={coachBase(aid)} />
}

function Messages({ chat, onOpen, onNew, name }: {
  chat: ReturnType<typeof chatApi>; onOpen: (id: string) => void; onNew: () => void; name: string
}) {
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null)
  useEffect(() => { chat.list().then((r) => setThreads(r.threads), () => setThreads([])) }, [chat])
  return (
    <>
      <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" onClick={onNew}><MessageSquare className="size-4" /> Message {name.split(' ')[0]}</Button>
      <p className="px-1 text-[0.7059rem] text-(--text-muted)">To talk about one workout, open the plan, tap the session and choose Message.</p>
      {threads && threads.length > 0 && <ThreadList threads={threads} onOpen={onOpen} me="coach" />}
    </>
  )
}

function Notes({ aid, notes, events, onChanged, myEmail }: { aid: string; notes: Note[]; events: RaceEvent[]; onChanged: () => void; myEmail: string }) {
  const [text, setText] = useState('')
  const [shared, setShared] = useState(true)
  const [eventId, setEventId] = useState<string | null>(null)
  const upcoming = events.filter((e) => daysUntil(e.date) >= 0)
  const evName = (id: string | null | undefined) => events.find((e) => e.id === id)?.name
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key); setError(null)
    try { await fn(); onChanged() } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <>
      <Card>
        <Field label="Add a note" hint={shared ? 'Shared: the athlete sees it, and Rabbit follows it in briefs and chats.' : 'Private: only you see it.'}>
          <textarea className={areaCls} value={text} maxLength={2000} onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Keep long runs under 2:30 until December; HR cap 150 on easy days" />
          {upcoming.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[0.7059rem] text-(--text-muted)">For a race (optional): the athlete sees it in that race's Race fit view.</span>
              <Choice value={eventId} allowNone options={upcoming.map((e) => [e.id, e.name] as [string, string])} onChange={setEventId} />
            </div>
          )}
          <div className="flex items-center gap-3">
            <span className="flex flex-1 items-center gap-2 text-[0.7647rem] text-(--text-secondary)">
              <Switch label="Share with athlete and Rabbit" checked={shared} onChange={setShared} /> {shared ? 'Shared' : 'Private'}
            </span>
            <Button variant="primary" className="h-9 gap-1 px-3 text-[0.7647rem]" disabled={!text.trim()} loading={busy === 'add'}
              onClick={() => void run('add', () => addNote(aid, { text: text.trim(), shared, ...(eventId ? { event_id: eventId } : {}) }).then(() => { setText(''); setEventId(null) }))}>
              <Plus className="size-4" /> Add
            </Button>
          </div>
        </Field>
      </Card>
      {error && <p className="px-1 text-[0.7647rem] text-(--danger)">{error}</p>}
      {notes.map((n) => (
        <Card key={n.id} className="px-4 py-3">
          <p className="whitespace-pre-wrap text-[0.8235rem] leading-snug text-(--text)">{n.text}</p>
          <div className="mt-2 flex items-center gap-2 text-[0.6471rem] text-(--text-muted)">
            {n.shared ? <Eye className="size-3.5" /> : <Lock className="size-3.5" />}
            <span className="flex-1">{n.shared ? 'Shared' : 'Private'} · {n.coach === myEmail ? 'You' : n.coach.split('@')[0]} · {timeAgo(n.ts)}{evName(n.event_id) ? ` · ${evName(n.event_id)}` : ''}</span>
            {n.coach === myEmail && <>
            <button type="button" aria-label={n.pinned ? 'Unpin' : 'Pin'} onClick={() => void run(n.id, () => updateNote(aid, n.id, { pinned: !n.pinned }))}
              className={cn('hit-44 rounded p-1', n.pinned ? 'text-(--accent)' : 'text-(--text-muted)')}><Pin className="size-3.5" /></button>
            <button type="button" aria-label={n.shared ? 'Make private' : 'Share'} onClick={() => void run(n.id, () => updateNote(aid, n.id, { shared: !n.shared }))}
              className="hit-44 rounded p-1 text-(--text-muted)"><StickyNote className="size-3.5" /></button>
            <button type="button" aria-label="Delete note" onClick={() => void run(n.id, () => deleteNote(aid, n.id))}
              className="hit-44 rounded p-1 text-(--danger)"><Trash2 className="size-3.5" /></button>
            </>}
          </div>
        </Card>
      ))}
    </>
  )
}

function RabbitChats({ aid }: { aid: string }) {
  const [threads, setThreads] = useState<{ id: string; kind: string; title: string; updated: number }[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [turns, setTurns] = useState<Awaited<ReturnType<typeof getRabbitThread>>['turns'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getRabbitThreads(aid).then((r) => setThreads(r.threads), (e) => setError((e as Error).message)) }, [aid])
  useEffect(() => {
    if (!open) return
    setTurns(null)
    getRabbitThread(aid, open).then((r) => setTurns(r.turns), (e) => setError((e as Error).message))
  }, [aid, open])
  if (error) return <p className="px-1 text-[0.7647rem] text-(--danger)">{error}</p>
  if (open) {
    return (
      <>
        <Button variant="ghost" className="h-8 w-fit px-2 text-[0.7059rem]" onClick={() => setOpen(null)}>‹ All chats</Button>
        <p className="px-1 text-[0.6471rem] text-(--text-muted)">Read-only. Shared by your athlete.</p>
        {(turns ?? []).map((t) => {
          const reply = (t.parts ?? []).filter((p) => p.type === 'text').map((p) => p.text).join('')
          return (
            <div key={t.id} className="flex flex-col gap-1.5">
              {t.user && <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-(--bg-elevated) px-3.5 py-2 text-[0.8235rem]">{t.user}</div>}
              {reply && <div className="chat-text prose prose-sm max-w-[92%] rounded-2xl rounded-bl-sm border border-(--border) bg-(--bg-surface) px-3.5 py-2 text-[0.8235rem] text-foreground"><Markdown remarkPlugins={[remarkGfm]}>{reply}</Markdown></div>}
              <span className="px-1 text-[0.6471rem] text-(--text-muted)">{t.label ? `${t.label} · ` : ''}{timeAgo(t.ts)}</span>
            </div>
          )
        })}
      </>
    )
  }
  return (
    <Card>
      <div className="divide-y divide-(--border)">
        {(threads ?? []).map((t) => (
          <button key={t.id} type="button" onClick={() => setOpen(t.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[0.8824rem] text-(--text)">{t.kind === 'coach' ? 'Rabbit (briefs and notes)' : t.title || 'Chat'}</span>
              <span className="block text-[0.6471rem] text-(--text-muted)">{timeAgo(t.updated)}</span>
            </span>
            <ChevronRight className="size-4 text-(--text-muted)" />
          </button>
        ))}
        {threads?.length === 0 && <p className="px-4 py-3 text-[0.7647rem] text-(--text-muted)">No chats yet.</p>}
      </div>
    </Card>
  )
}
