// Local: "Post a club run" (pick one of the clubs you organize, then the 30-second sheet) and
// "Runs near you" with filters (beginner friendly, walkers, women only, pace groups).
import { useCallback, useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { Section } from '@/components/ui/section'
import { Card, Chip, ChipRow } from '@/components/plan/ui'
import { getClubs, getNearbyRuns, type ClubSummary, type Meetup } from '@/lib/community'
import { OrganizeSheet, RunCard, RunSheet } from './ClubRun'

type Filter = 'beginner' | 'walk' | 'women' | 'groups'
const FILTERS: [Filter, string][] = [['beginner', 'No one left behind'], ['walk', 'Walkers welcome'], ['women', 'Women only'], ['groups', 'Pace groups']]

export function PostRunButton({ onPosted }: { onPosted?: () => void }) {
  const [clubs, setClubs] = useState<ClubSummary[] | null>(null)
  const [pick, setPick] = useState(false)
  const [club, setClub] = useState<ClubSummary | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  async function start() {
    setErr(null); setDone(null)
    try {
      const v = await getClubs()
      const mine = v.clubs.filter((c) => c.kind === 'club' && (c.role === 'owner' || c.role === 'admin'))
      setClubs(mine)
      if (mine.length === 1) setClub(mine[0]); else setPick(true)
    } catch (e) { setErr((e as Error).message) }
  }
  return (
    <>
      <Button variant="primary" className="h-12 w-full gap-1.5 text-body" onClick={() => void start()}>
        <Plus className="size-5" aria-hidden /> Post a club run
      </Button>
      {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
      {done && <p className="text-meta text-(--accent)" role="status">{done}</p>}
      {pick && clubs && (
        <Sheet title="Post a club run" onClose={() => setPick(false)}>
          {clubs.length === 0 ? (
            <p className="text-body text-(--text-secondary)">Club runs are posted by a club's organizers. Start a club under Your clubs below, then post its first run here.</p>
          ) : (
            <>
              <p className="text-small text-(--text-secondary)">Which club is it for?</p>
              <Card>
                {clubs.map((c) => (
                  <button key={c.id} type="button" onClick={() => { setPick(false); setClub(c) }}
                    className="flex min-h-14 w-full items-center gap-3 border-b border-(--border) px-4 py-3 text-left last:border-b-0 active:bg-(--bg-inset)">
                    <span className="text-title" aria-hidden>{c.emoji || '🐇'}</span>
                    <span className="min-w-0 flex-1 truncate text-body text-(--text)">{c.name}</span>
                  </button>
                ))}
              </Card>
            </>
          )}
        </Sheet>
      )}
      {club && (
        <RunSheet clubId={club.id} privateClub={club.visibility === 'private'} onClose={() => setClub(null)}
          onSaved={(m) => { setClub(null); setDone(`Posted to ${club.name}.${m.see === 'public' ? ' Open the club to copy its link.' : ''}`); onPosted?.() }} />
      )}
    </>
  )
}

export function NearbyRuns({ refreshKey = 0 }: { refreshKey?: number }) {
  const [runs, setRuns] = useState<Meetup[] | null>(null)
  const [on, setOn] = useState<Set<Filter>>(new Set())
  const [msg, setMsg] = useState<string | null>(null)
  const [organize, setOrganize] = useState<Meetup | null>(null)
  const load = useCallback(() => { getNearbyRuns(72).then((r) => setRuns(r.runs), () => setRuns([])) }, [])
  useEffect(load, [load, refreshKey])
  if (!runs || runs.length === 0) return null
  const shown = runs.filter((m) => [...on].every((f) => f === 'groups' ? (m.groups ?? []).length > 0 : !!m[f]))
  const toggle = (f: Filter) => setOn((s) => { const n = new Set(s); if (n.has(f)) n.delete(f); else n.add(f); return n })
  return (
    <Section title="Club runs near you" description="The next three days, from your clubs and open clubs in your city.">
      <ChipRow>
        {FILTERS.map(([f, label]) => <Chip key={f} selected={on.has(f)} onClick={() => toggle(f)}>{label}</Chip>)}
      </ChipRow>
      {msg && <p className="text-meta text-(--text-secondary)" role="status">{msg}</p>}
      <div className="flex flex-col gap-3">
        {shown.length === 0 && <p className="text-small text-(--text-muted)">No runs match those filters. Try fewer.</p>}
        {shown.map((m) => m.club && (
          <div key={m.id} className="flex flex-col gap-1">
            <p className="px-1 text-meta text-(--text-muted)">{m.club.emoji} {m.club.name}</p>
            <RunCard m={m} clubId={m.club.id} clubName={m.club.name} admin={m.mine} onChanged={load} onError={setMsg}
              onOrganize={setOrganize} />
          </div>
        ))}
      </div>
      {organize?.club && <OrganizeSheet clubId={organize.club.id} run={organize} onClose={() => setOrganize(null)} onChanged={load} />}
    </Section>
  )
}
