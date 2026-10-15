// Challenges on the Progress tab: this week's and month's joined challenges with live
// progress, a small celebration when one is done, friend invites and the group leaderboard.
// "Pick a challenge" opens a sheet with 3 personal suggestions per period (easy, stretch, fun).
import { useCallback, useEffect, useState } from 'react'
import { Carrot, Check, ChevronDown, ChevronRight, Flame, Mountain, Plus, Target, Trophy, UserPlus, X } from 'lucide-react'
import { Card } from '@/components/plan/ui'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Sheet as UISheet } from '@/components/ui/Sheet'
import { cn } from '@/lib/utils'
import {
  acceptInvite, daysLeft, declineInvite, getChallenges, inviteFriends, joinChallenge, leaveChallenge, progressLine,
  targetLine, type ChallengePeriod, type ChallengesView, type Joined, type Suggestion,
} from '@/lib/challenges'
import { getPeople, type PersonEdge } from '@/lib/social'
import { HopPrints } from '@/components/fx/HopPrints'
import { RabbitHop, RabbitNap } from '@/components/anim'
import { celebrate } from '@/components/fx/motion'
import { useTrackRefresh } from '@/components/stats/refresh'

const SEEN_KEY = 'rabbit.challenges.celebrated'
const KIND_LABEL: Record<Suggestion['kind'], string> = { easy: 'Easy', stretch: 'Stretch', fun: 'Fun' }

function celebratedIds(): string[] {
  try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '[]') as string[] } catch { return [] }
}
function markCelebrated(ids: string[]) {
  try { localStorage.setItem(SEEN_KEY, JSON.stringify([...new Set([...celebratedIds(), ...ids])].slice(-60))) } catch { /* private mode */ }
}

export function ChallengesCard({ imperial = false, loadKey = 0, collapsible = false }: {
  imperial?: boolean
  /** bump to re-read (Progress refresh) */
  loadKey?: number
  /** Progress: one summary row ("2 active · 60%") or "Pick a challenge" that expands */
  collapsible?: boolean
}) {
  const [v, setV] = useState<ChallengesView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picking, setPicking] = useState<ChallengePeriod | null>(null)
  const [inviting, setInviting] = useState<Joined | null>(null)
  const [party, setParty] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [open, setOpen] = useState(!collapsible)
  const track = useTrackRefresh()

  const load = useCallback(() => {
    track(getChallenges().then((r) => {
      setV(r); setError(null)
      const seen = celebratedIds()
      const fresh = r.joined.filter((c) => c.done && !seen.includes(c.id))
      if (fresh.length) { setParty(fresh[0]!.id); markCelebrated(fresh.map((c) => c.id)) }
    }, (e) => setError((e as Error).message)))
  }, [track])
  useEffect(() => load(), [load, loadKey])
  useEffect(() => { if (party) setOpen(true) }, [party])
  useEffect(() => {
    if (!party) return
    // Carrot burst from the finished challenge's row (components/fx).
    const el = document.querySelector(`[data-challenge="${CSS.escape(party)}"]`)
    const b = window.setTimeout(() => celebrate(el, 'challenge'), 150)
    return () => window.clearTimeout(b)
  }, [party])
  useEffect(() => {
    if (!party) return
    const t = window.setTimeout(() => setParty(null), 2600)
    return () => window.clearTimeout(t)
  }, [party])

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key)
    try { await fn(); load() } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  if (!v) {
    return (
      <section className="flex flex-col gap-2">
        <Label />
        {error ? <ErrorState message={`Couldn't load challenges: ${error}`} onRetry={load} compact />
          : <div className="skeleton h-20" aria-hidden="true" />}
      </section>
    )
  }

  const weekly = v.joined.filter((c) => c.period === 'week')
  const monthly = v.joined.filter((c) => c.period === 'month')
  const canAdd = (p: ChallengePeriod) => v.periods[p].joined < v.periods[p].limit
  const streak = v.streak.week
  const sheets = <>
    {picking && (
      <PickSheet v={v} initial={picking} imperial={imperial} onClose={() => setPicking(null)}
        onJoined={(r) => { setV(r); setPicking(null); setOpen(true) }} />
    )}
    {inviting && <InviteSheet c={inviting} onClose={() => setInviting(null)} onSent={() => { setInviting(null); load() }} />}
  </>

  if (collapsible && !open) {
    const n = v.joined.length
    if (n === 0 && v.invites.length === 0) {
      return (
        <section>
          <button type="button" onClick={() => setPicking(canAdd('week') ? 'week' : 'month')}
            className="flex min-h-11 w-full items-center gap-3 rounded-xl border border-dashed border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
            <Target className="size-4 shrink-0 text-(--accent)" aria-hidden />
            <span className="min-w-0 flex-1 text-[0.7647rem] font-medium text-(--accent)">Pick a challenge</span>
            <span className="shrink-0 text-[0.6471rem] text-(--text-muted)">+{v.xp.week} XP</span>
            <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
          </button>
          {sheets}
        </section>
      )
    }
    const avg = n ? Math.round(v.joined.reduce((a, c) => a + (c.done ? 100 : c.pct), 0) / n) : 0
    const bits = [n ? `${n} active · ${avg}%` : null,
      v.invites.length ? `${v.invites.length} invite${v.invites.length === 1 ? '' : 's'}` : null,
      streak > 0 ? `${streak}-week streak` : null].filter(Boolean)
    return (
      <section>
        <button type="button" onClick={() => setOpen(true)} aria-expanded={false}
          className="flex min-h-11 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
          <Trophy className="size-4 shrink-0 text-(--accent)" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-[0.7647rem] font-medium text-(--text)">Challenges</span>
            <span className="block truncate text-[0.7059rem] text-(--text-muted)">{bits.join(' · ')}</span>
          </span>
          <ChevronDown className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
        {sheets}
      </section>
    )
  }

  return (
    <section className="flex flex-col gap-2">
      {collapsible ? (
        <button type="button" onClick={() => setOpen(false)} aria-expanded
          className="hit-44 flex items-center justify-between text-left">
          <Label streak={streak} />
          <ChevronDown className="size-4 shrink-0 rotate-180 text-(--text-muted)" aria-hidden />
        </button>
      ) : <Label streak={streak} />}
      {error && <p className="px-1 text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
      {v.invites.map((inv) => (
        <Card key={inv.id} className="flex items-center gap-3 px-4 py-3">
          <UserPlus className="size-5 shrink-0 text-(--accent)" />
          <div className="min-w-0 flex-1">
            <p className="text-[0.8235rem] font-medium leading-snug text-(--text)">{inv.from.name} challenged you: {inv.name}</p>
            <p className="text-[0.7059rem] text-(--text-muted)">{targetLine(inv, imperial)} · +{inv.xp} XP</p>
          </div>
          <button type="button" aria-label="No thanks" disabled={busy !== null}
            onClick={() => void act(`d${inv.id}`, () => declineInvite(inv.id))}
            className="hit-44 flex size-9 items-center justify-center rounded-full text-(--text-muted) hover:bg-(--bg-inset)">
            <X className="size-4" />
          </button>
          <Button className="hit-44" disabled={busy !== null} onClick={() => void act(`a${inv.id}`, () => acceptInvite(inv.id))}>Join</Button>
        </Card>
      ))}
      {v.joined.length > 0 && (
        <Card className="relative overflow-hidden">
          {[...weekly, ...monthly].map((c, i) => (
            <JoinedRow key={c.id} c={c} first={i === 0} imperial={imperial} party={party === c.id}
              canInvite={v.can_invite && !c.done}
              onInvite={() => setInviting(c)}
              onLeave={() => { if (window.confirm(`Leave "${c.name}"?`)) void act(`l${c.id}`, () => leaveChallenge(c.id)) }} />
          ))}
        </Card>
      )}
      {(canAdd('week') || canAdd('month')) && (
        <button type="button" onClick={() => setPicking(canAdd('week') ? 'week' : 'month')}
          className={cn('hit-44 flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-(--border) bg-(--bg-surface) py-3 text-[0.7647rem] font-medium text-(--accent) active:bg-(--bg-inset)',
            v.joined.length === 0 && v.invites.length === 0 && 'flex-col pt-4')}>
          {v.joined.length === 0 && v.invites.length === 0 && <RabbitNap size={40} mode="peek" />}
          <span className="inline-flex items-center gap-1.5">{weekly.length === 0 ? <><Target className="size-4" /> Pick this week's challenge</> : <><Plus className="size-4" /> Add a challenge</>}</span>
        </button>
      )}
      {v.recent.length > 0 && v.joined.length === 0 && (
        <p className="px-1 text-[0.6471rem] text-(--text-muted)">Last done: {v.recent[0]!.name} · {new Date(v.recent[0]!.completed_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}</p>
      )}
      {sheets}
    </section>
  )
}

function Label({ streak }: { streak?: number }) {
  return (
    <div className="flex items-center justify-between px-1">
      <h3 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Challenges</h3>
      {!!streak && streak > 0 && (
        <span className="inline-flex items-center gap-1 text-[0.6471rem] font-medium text-(--accent)">
          <Flame className="size-3" /> {streak}-week challenge streak
        </span>
      )}
    </div>
  )
}

function JoinedRow({ c, first, imperial, party, canInvite, onInvite, onLeave }: {
  c: Joined; first: boolean; imperial: boolean; party: boolean; canInvite: boolean
  onInvite: () => void; onLeave: () => void
}) {
  const board = c.leaderboard && c.leaderboard.length > 1 ? c.leaderboard : null
  return (
    <div data-challenge={c.id} className={cn('relative flex flex-col gap-2 px-4 py-3', !first && 'border-t border-(--border)')}>
      <div className="flex items-start gap-3">
        <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full',
          c.done ? 'bg-(--brand) text-(--on-fill)' : 'bg-(--bg-elevated) text-(--accent)', party && 'celebrate')}>
          {c.done ? <Check className="size-5" /> : c.metric === 'climb_m' ? <Mountain className="size-4" /> : <Target className="size-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[0.8235rem] font-medium leading-snug text-(--text)">{c.name}</p>
          <p className="text-[0.7059rem] text-(--text-muted)">{targetLine(c, imperial)}</p>
        </div>
        <span className={cn('shrink-0 text-[0.7059rem] font-medium', c.done ? 'text-(--brand)' : 'text-(--text-muted)')}>
          {c.done ? `+${c.xp} XP` : `${c.pct}%`}
        </span>
      </div>
      <span className="fx-bar">
        <span className="block h-1.5 w-full overflow-hidden rounded-full bg-(--bg-elevated)" role="progressbar"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={c.pct} aria-label={`${c.name} progress`}>
          <span className={cn('block h-full rounded-full transition-[width] duration-700 motion-reduce:transition-none', c.done ? 'bg-(--brand)' : 'bg-(--accent)')}
            style={{ width: `${Math.max(2, c.pct)}%` }} />
        </span>
        <HopPrints pct={c.pct} storeKey={`challenge.${c.id}`} />
        <RabbitHop pct={Math.max(2, c.pct)} value={c.pct} size={12} storeKey={`challenge.${c.id}`} />
      </span>
      <div className="flex items-center gap-2 text-[0.7059rem] text-(--text-muted)">
        <span className="min-w-0 flex-1">{c.done ? 'Done. Nice work.' : `${progressLine(c, imperial)} · ${daysLeft(c.days_left)}`}</span>
        {canInvite && (
          <button type="button" onClick={onInvite} className="hit-44 inline-flex items-center gap-1 font-medium text-(--accent)">
            <UserPlus className="size-3.5" /> Invite
          </button>
        )}
        {!c.done && (
          <button type="button" onClick={onLeave} className="hit-44 inline-flex items-center font-medium text-(--text-muted)">Leave</button>
        )}
      </div>
      {board && (
        <ol className="flex flex-col gap-1.5 rounded-lg bg-(--bg-inset) px-3 py-2" aria-label="Leaderboard">
          {board.map((r, i) => (
            <li key={r.user_id} className="flex items-center gap-2 text-[0.7059rem]">
              <span className="w-4 text-(--text-muted)">{i === 0 && (r.pct ?? 0) > 0 ? <Trophy className="size-3.5 text-(--accent)" /> : i + 1}</span>
              <span className={cn('w-20 truncate', r.me ? 'font-semibold text-(--text)' : 'text-(--text-secondary)')}>{r.me ? 'You' : r.name}</span>
              <span className="block h-1 flex-1 overflow-hidden rounded-full bg-(--bg-elevated)">
                <span className="block h-full rounded-full bg-(--accent)" style={{ width: `${Math.max(2, r.pct ?? 0)}%` }} />
              </span>
              <span className="w-9 text-right text-(--text-muted)">{r.pct == null ? '–' : `${r.pct}%`}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/** A short burst of dots. Hidden entirely for reduced motion (the check pop is enough). */
// ------------------------------------------------------------------ sheets --
function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return <UISheet portal title={title} label={title} onClose={onClose}>{children}</UISheet>
}

function PickSheet({ v, initial, imperial, onClose, onJoined }: {
  v: ChallengesView; initial: ChallengePeriod; imperial: boolean; onClose: () => void
  onJoined: (r: ChallengesView) => void
}) {
  const [tab, setTab] = useState<ChallengePeriod>(initial)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const p = v.periods[tab]
  const full = p.joined >= p.limit
  async function join(s: Suggestion) {
    setBusy(s.template); setError(null)
    try { onJoined(await joinChallenge(s.template, s.period)) } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <Sheet title="Pick a challenge" onClose={onClose}>
      <div className="flex gap-1 rounded-lg bg-(--bg-inset) p-1" role="tablist">
        {(['week', 'month'] as const).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cn('hit-44 flex-1 rounded-md py-2 text-[0.7647rem] font-medium',
              tab === t ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>
            {t === 'week' ? 'This week' : 'This month'}
          </button>
        ))}
      </div>
      <p className="text-[0.7059rem] text-(--text-muted)">
        {tab === 'week' ? `${daysLeft(p.days_left)} this week` : `${daysLeft(p.days_left)} this month`} · join up to {p.limit}
        {full ? ' (you have)' : ''}. Every workout this {tab} counts, even ones before you join.
      </p>
      {p.notice && <p className="rounded-lg bg-(--bg-inset) px-3 py-2 text-[0.7647rem] text-(--text-secondary)">{p.notice}</p>}
      {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
      {p.suggestions.length === 0 && !p.notice && (
        <p className="py-4 text-center text-[0.7647rem] text-(--text-muted)">Nothing new to pick right now.</p>
      )}
      {p.suggestions.map((s) => (
        <Card key={s.template} className="flex flex-col gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className={cn('rounded-full px-2 py-0.5 text-[0.6471rem] font-semibold uppercase tracking-wide',
              s.kind === 'stretch' ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-elevated) text-(--text-secondary)')}>
              {KIND_LABEL[s.kind]}
            </span>
            <span className="ml-auto inline-flex items-center gap-1 text-[0.7059rem] font-medium text-(--brand)"><Carrot className="size-3" aria-hidden /> +{s.xp} XP</span>
          </div>
          <p className="text-[0.8824rem] font-semibold leading-snug text-(--text)">{s.name}</p>
          <p className="text-[0.7647rem] text-(--text-secondary)">{targetLine(s, imperial)}</p>
          <p className="text-[0.6471rem] text-(--text-muted)">{s.why}</p>
          <Button className="hit-44 self-start" disabled={full || busy !== null} onClick={() => void join(s)}>
            {busy === s.template ? 'Joining…' : 'Join'}
          </Button>
        </Card>
      ))}
    </Sheet>
  )
}

function InviteSheet({ c, onClose, onSent }: { c: Joined; onClose: () => void; onSent: () => void }) {
  const [people, setPeople] = useState<PersonEdge[] | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    getPeople().then((r) => setPeople(r.following.filter((p) => p.user_id && p.user)), (e) => setError((e as Error).message))
  }, [])
  const already = new Set((c.leaderboard ?? []).map((r) => r.user_id))
  async function send() {
    setBusy(true); setError(null)
    try { await inviteFriends(c.id, picked); onSent() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Sheet title="Challenge a friend" onClose={onClose}>
      <p className="text-[0.7647rem] text-(--text-secondary)">
        Friends you follow can join "{c.name}" with the same target. Only people in the challenge see the leaderboard (progress %, nothing else).
      </p>
      {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
      {!people && !error && <RabbitLoader className="py-6" label="Finding your friends" />}
      {people && people.length === 0 && (
        <p className="py-4 text-center text-[0.7647rem] text-(--text-muted)">Follow a friend first (Me → Friends), then invite them here.</p>
      )}
      {people?.map((p) => {
        const id = p.user_id!
        const on = picked.includes(id)
        const inIt = already.has(id)
        return (
          <button key={id} type="button" disabled={inIt} aria-pressed={on}
            onClick={() => setPicked((x) => (on ? x.filter((y) => y !== id) : [...x, id].slice(0, 10)))}
            className={cn('hit-44 flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left',
              on ? 'border-(--accent) bg-(--bg-inset)' : 'border-(--border) bg-(--bg-surface)', inIt && 'opacity-50')}>
            <span className="min-w-0 flex-1 truncate text-[0.8235rem] text-(--text)">{p.user!.name}</span>
            {inIt ? <span className="text-[0.6471rem] text-(--text-muted)">In it</span>
              : on && <Check className="size-4 text-(--accent)" />}
          </button>
        )
      })}
      {people && people.length > 0 && (
        <Button disabled={!picked.length || busy} onClick={() => void send()}>
          {busy ? 'Sending…' : picked.length ? `Invite ${picked.length}` : 'Pick friends'}
        </Button>
      )}
    </Sheet>
  )
}
