// Search everywhere: one box for people, clubs, races and events, plan sessions and past
// workouts (server: search.py). SearchButton is the header launcher (next to the Me avatar on
// every tab); it owns the sheet. Picking a result fires lib/search openSearchResult, which
// screens/Chat.tsx routes to the right tab or page.
import { useEffect, useRef, useState } from 'react'
import { Clock, Flag, Search as SearchIcon, Users, X } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { EmptyState } from '@/components/ui/EmptyState'
import { Avatar } from '@/components/Avatar'
import { SPORT_ICON, fmtDay } from '@/components/plan/PlanParts'
import type { Sport } from '@/lib/api'
import { fmtDist, fmtDuration } from '@/lib/format'
import { photoUrl } from '@/lib/photo'
import {
  MIN_QUERY, clearSearches, openSearchResult, recentSearches, rememberSearch, search,
  type SearchPick, type SearchResults,
} from '@/lib/search'

export function SearchButton({ imperial }: { imperial: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" data-tour="search" aria-label="Search" onClick={() => setOpen(true)}
        className="flex size-11 shrink-0 items-center justify-center rounded-full text-(--text-secondary) active:bg-(--bg-inset)">
        <SearchIcon className="size-5" aria-hidden />
      </button>
      {open && <SearchSheet imperial={imperial} onClose={() => setOpen(false)} />}
    </>
  )
}

const sportIcon = (s: string) => SPORT_ICON[(s in SPORT_ICON ? s : 'other') as Sport]

export function SearchSheet({ imperial, onClose }: { imperial: boolean; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState<SearchResults | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const [recent, setRecent] = useState(recentSearches)
  const input = useRef<HTMLInputElement>(null)
  const seq = useRef(0)

  useEffect(() => { const t = window.setTimeout(() => input.current?.focus(), 250); return () => window.clearTimeout(t) }, [])
  useEffect(() => {
    const t = q.trim()
    if (t.length < MIN_QUERY) { setRes(null); setBusy(false); setError(false); return }
    const n = ++seq.current
    setBusy(true)
    const timer = window.setTimeout(() => {
      search(t).then((r) => { if (n === seq.current) { setRes(r); setError(false) } },
        () => { if (n === seq.current) setError(true) })
        .finally(() => { if (n === seq.current) setBusy(false) })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [q])

  function pick(p: SearchPick) {
    rememberSearch(q)
    onClose()
    openSearchResult(p)
  }

  const total = res ? res.people.length + res.clubs.length + res.events.length + res.sessions.length + res.workouts.length : 0
  const short = q.trim().length < MIN_QUERY

  return (
    <Sheet onClose={onClose} label="Search" portal
      header={<h2 className="modal-title sr-only">Search</h2>}
      below={
        <div className="px-4 pb-2">
          <label className="flex h-11 items-center gap-2 rounded-full border border-(--border) bg-(--bg-inset) px-3.5 focus-within:ring-1 focus-within:ring-(--accent)">
            <SearchIcon className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
            <input ref={input} type="search" value={q} onChange={(e) => setQ(e.target.value)} enterKeyHint="search"
              onKeyDown={(e) => { if (e.key === 'Enter') rememberSearch(q) }}
              placeholder="People, clubs, races, workouts…" aria-label="Search people, clubs, races, sessions and workouts"
              className="min-w-0 flex-1 bg-transparent text-[0.9412rem] text-(--text) outline-none placeholder:text-(--text-muted)" />
            {q && (
              <button type="button" aria-label="Clear search" onClick={() => { setQ(''); input.current?.focus() }}
                className="-mr-2 flex size-11 items-center justify-center text-(--text-muted)"><X className="size-4" aria-hidden /></button>
            )}
          </label>
        </div>
      }>
      <div aria-live="polite" className="pb-4">
        {short ? (
          recent.length > 0 ? (
            <section className="px-1">
              <div className="flex items-center justify-between">
                <h3 className="px-3 text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Recent</h3>
                <button type="button" className="min-h-11 px-3 text-[0.7059rem] text-(--accent)"
                  onClick={() => { clearSearches(); setRecent([]) }}>Clear</button>
              </div>
              {recent.map((r) => (
                <button key={r} type="button" onClick={() => setQ(r)}
                  className="flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-[0.8235rem] text-(--text) active:bg-(--bg-inset)">
                  <Clock className="size-4 shrink-0 text-(--text-muted)" aria-hidden />{r}
                </button>
              ))}
            </section>
          ) : (
            <EmptyState compact icon={<SearchIcon className="size-6" />} title="Search everything"
              body="Friends, clubs, races, your plan's sessions and past workouts. Try “tempo”, a friend's name or your race." />
          )
        ) : error ? (
          <p role="alert" className="px-4 py-6 text-center text-[0.7647rem] text-(--danger)">Couldn't search right now. Check your connection and try again.</p>
        ) : res && total === 0 && !busy ? (
          <EmptyState compact title={`Nothing for “${q.trim()}”`} body="Try a shorter word, a first name, or a sport like “swim”." />
        ) : res ? (
          <div className={busy ? 'opacity-60' : undefined}>
            <Group title="People" n={res.people.length}>
              {res.people.map((p) => (
                <Row key={p.id} onClick={() => pick({ kind: 'person', id: p.id })}
                  icon={<Avatar name={p.name} picture={p.picture ?? ''} photo={photoUrl(p.photo ?? null, p.id)} size={32} />}
                  title={p.name} sub={p.relation === 'following' ? 'You follow' : 'Follows you'} />
              ))}
            </Group>
            <Group title="Clubs & groups" n={res.clubs.length}>
              {res.clubs.map((c) => (
                <Row key={`${c.source}:${c.id}`} onClick={() => pick({ kind: 'club', id: c.id, source: c.source })}
                  icon={<Tile><Users className="size-4" /></Tile>} title={c.name}
                  sub={[c.mine ? 'Your club' : c.kind ?? 'Club', c.city, c.members ? `${c.members} members` : ''].filter(Boolean).join(' · ')} />
              ))}
            </Group>
            <Group title="Races & events" n={res.events.length}>
              {res.events.map((e) => (
                <Row key={e.id} onClick={() => pick({ kind: 'event', id: e.id })}
                  icon={<Tile><Flag className="size-4" /></Tile>} title={e.title}
                  sub={[e.date ? fmtDay(e.date, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Date to be set', e.location, e.past ? 'Done' : ''].filter(Boolean).join(' · ')} />
              ))}
            </Group>
            <Group title="Your plan" n={res.sessions.length}>
              {res.sessions.map((s) => {
                const Icon = sportIcon(s.sport)
                return (
                  <Row key={s.id} onClick={() => pick({ kind: 'session', id: s.id, date: s.date })}
                    icon={<Tile><Icon className="size-4" /></Tile>} title={s.title}
                    sub={[fmtDay(s.date), s.minutes ? fmtDuration(s.minutes) : ''].filter(Boolean).join(' · ')} />
                )
              })}
            </Group>
            <Group title="Past workouts" n={res.workouts.length}>
              {res.workouts.map((w) => {
                const Icon = sportIcon(w.sport)
                return (
                  <Row key={w.id} onClick={() => pick({ kind: 'workout', id: w.id })}
                    icon={<Tile><Icon className="size-4" /></Tile>} title={w.name}
                    sub={[fmtDay(w.date), w.km ? fmtDist(w.km, imperial, w.sport) : '', w.minutes ? fmtDuration(w.minutes) : ''].filter(Boolean).join(' · ')} />
                )
              })}
            </Group>
          </div>
        ) : (
          <p className="px-4 py-6 text-center text-[0.7647rem] text-(--text-muted)">Searching…</p>
        )}
      </div>
    </Sheet>
  )
}

function Group({ title, n, children }: { title: string; n: number; children: React.ReactNode }) {
  if (!n) return null
  return (
    <section className="mt-2 px-1">
      <h3 className="px-3 pb-1 text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{title}</h3>
      <ul>{children}</ul>
    </section>
  )
}

function Tile({ children }: { children: React.ReactNode }) {
  return <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-(--bg-inset) text-(--text-secondary)">{children}</span>
}

function Row({ icon, title, sub, onClick }: { icon: React.ReactNode; title: string; sub?: string; onClick: () => void }) {
  return (
    <li>
      <button type="button" onClick={onClick}
        className="flex min-h-12 w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left active:bg-(--bg-inset)">
        {icon}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.8235rem] text-(--text)">{title}</span>
          {sub && <span className="block truncate text-[0.7059rem] text-(--text-muted)">{sub}</span>}
        </span>
      </button>
    </li>
  )
}
