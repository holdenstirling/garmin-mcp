// Home: "Near you tonight", one or two club runs today that fit, right under the plan. "Swap
// today's run for this" RSVPs and counts the club run as today's session (the plan trims the
// week so the load stays about the same). Hidden when nothing is on today.
import { useEffect, useState } from 'react'
import { MapPin, Repeat } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Section } from '@/components/ui/section'
import { Card } from '@/components/plan/ui'
import { burst } from '@/components/anim'
import { getNearbyRuns, meetupWhen, rsvpMeetup, runTags, type Meetup } from '@/lib/community'
import { countClubRun } from '@/lib/plan'

export function NearTonight({ hasPlan, refreshKey = 0, onOpenClub, onPlanChanged }: {
  hasPlan: boolean; refreshKey?: number; onOpenClub: (clubId: string) => void; onPlanChanged?: () => void
}) {
  const [runs, setRuns] = useState<Meetup[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getNearbyRuns(24).then((r) => {
      if (!live) return
      const today = new Date().toDateString()
      setRuns(r.runs.filter((m) => m.next && new Date(m.next).toDateString() === today).slice(0, 2))
    }, () => { if (live) setRuns([]) })
    return () => { live = false }
  }, [refreshKey])
  if (!runs || runs.length === 0) return null
  async function swap(m: Meetup, el: HTMLElement) {
    if (!m.club) return
    if (m.waiver && !m.waiver_signed) { onOpenClub(m.club.id); return }  // the waiver is read on the club page
    setBusy(m.id); setErr(null)
    try {
      if (m.my_rsvp !== 'going') await rsvpMeetup(m.club.id, m.id, 'going')
      if (hasPlan) {
        await countClubRun(m.club.id, m.id)
        onPlanChanged?.()
        setDone((d) => ({ ...d, [m.id]: "Swapped. Today's plan is this club run now." }))
      } else setDone((d) => ({ ...d, [m.id]: "You're going." }))
      burst(el, 'kudos')
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <Section title="Near you tonight" description={hasPlan ? 'A club run today that could be your run.' : 'Club runs today you can join.'}>
      {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
      {runs.map((m) => (
        <Card key={m.id} className="flex flex-col gap-2 p-4">
          <button type="button" className="flex flex-col items-start gap-0.5 text-left" onClick={() => m.club && onOpenClub(m.club.id)}>
            <span className="text-meta font-semibold text-(--accent)">{m.next ? meetupWhen(m.next) : ''}
              {m.repeat === 'weekly' && <span className="ml-1.5 inline-flex items-center gap-0.5 font-normal text-(--text-muted)"><Repeat className="size-3.5" aria-hidden />weekly</span>}
            </span>
            <span className="text-lead font-medium text-(--text)">{m.title}</span>
            <span className="text-meta text-(--text-secondary)">{m.club?.emoji} {m.club?.name}</span>
            <span className="flex items-center gap-1 text-meta text-(--text-secondary)"><MapPin className="size-4 shrink-0" aria-hidden />{m.where}</span>
          </button>
          {runTags(m).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {runTags(m).map((t) => <span key={t} className="rounded-full bg-(--accent-subtle) px-2.5 py-1 text-meta text-(--accent)">{t}</span>)}
            </div>
          )}
          {done[m.id] ? <p className="text-small text-(--accent)" role="status">{done[m.id]}</p> : (
            <Button variant="default" className="h-11 text-body" loading={busy === m.id} onClick={(e) => void swap(m, e.currentTarget)}>
              {hasPlan ? "Swap today's run for this" : "I'm going"}
            </Button>
          )}
        </Card>
      ))}
    </Section>
  )
}
