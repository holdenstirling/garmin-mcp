import { useEffect, useRef, useState } from 'react'
import { Bell, CalendarCheck, Clock, FlaskConical, Play, Sunrise, Watch } from 'lucide-react'
import { Group, Icon, Row, Switch } from '@/components/settings/Grouped'
import { postJSON, type CoachSettings, type Me } from '@/lib/api'
import { SaveStatus, useSaver } from '@/components/ui/SaveStatus'
import { MotionLab } from '@/components/fx/MotionLab'

export function CoachingSettings({ me, onChange, onDevDone }: {
  me: Me; onChange: () => void; onDevDone: () => void
}) {
  const [s, setS] = useState<CoachSettings>(me.settings)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [lab, setLab] = useState(false)

  const sRef = useRef(s)
  sRef.current = s
  // Saves can overlap: only the newest one's reply (or failure) is applied.
  const seq = useRef(0)
  // Durable PUT (lib/outbox): a subtle "Saved" tick, or "Not saved yet — we'll retry" while
  // offline (the switch keeps what they picked; queued patches are merged and sent later).
  const saver = useSaver<CoachSettings>()
  async function save(patch: Partial<CoachSettings>, prev: CoachSettings = sRef.current) {
    const n = ++seq.current
    setS((cur) => ({ ...cur, ...patch }))
    try {
      const r = await saver.run({ method: 'PUT', path: '/api/settings', body: patch, label: 'settings', coalesce: 'settings' })
      if (!r.ok || n !== seq.current) return
      setS(r.data)
      onChange()
    } catch (e) {
      if (n !== seq.current) return
      setS(prev)
      setMsg((e as Error).message)
    }
  }
  const saveRef = useRef(save)
  saveRef.current = save

  // The time picker fires on every scroll of its wheel: save once it settles (or on blur).
  const timeTimer = useRef<number | null>(null)
  const pendingTime = useRef<{ value: string; prev: CoachSettings } | null>(null)
  const flushTime = () => {
    if (timeTimer.current) window.clearTimeout(timeTimer.current)
    timeTimer.current = null
    const p = pendingTime.current
    pendingTime.current = null
    if (p) void saveRef.current({ brief_time: p.value }, p.prev)
  }
  const flushRef = useRef(flushTime)
  flushRef.current = flushTime
  useEffect(() => () => flushRef.current(), []) // closing settings still saves the last pick
  const changeTime = (value: string) => {
    if (!value) return
    pendingTime.current = { value, prev: pendingTime.current?.prev ?? sRef.current }
    setS((cur) => ({ ...cur, brief_time: value }))
    if (timeTimer.current) window.clearTimeout(timeTimer.current)
    timeTimer.current = window.setTimeout(() => flushRef.current(), 800)
  }

  async function dev(name: string, label: string) {
    setBusy(true)
    setMsg(`${label}… (rabbt is writing it)`)
    try {
      const r = await postJSON<{ result: unknown }>(`/api/dev/${name}`)
      setMsg(`${label}: ${JSON.stringify(r.result)}`)
      onDevDone()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const tz = s.timezone.split('/').pop()?.replace(/_/g, ' ') ?? s.timezone

  return (
    <>
      <div className="-mb-3 flex min-h-5 justify-end px-4"><SaveStatus state={saver.state} error={saver.error} /></div>
      <Group label="Coaching messages"
        footer={`rabbt can message you first; these arrive as notifications. Times are ${tz} time.`}>
        <Row icon={<Icon><Watch /></Icon>} title="Workout feedback" subtitle="A short note after each new activity"
          trailing={<Switch label="Workout feedback" checked={s.workout_feedback} onChange={(v) => void save({ workout_feedback: v })} />} />
        <Row icon={<Icon><Sunrise /></Icon>} title="Morning brief" subtitle="Today's plan, sleep and recovery"
          trailing={<Switch label="Morning brief" checked={s.brief_enabled} onChange={(v) => void save({ brief_enabled: v })} />} />
        {s.brief_enabled && (
          <Row icon={<Icon><Clock /></Icon>} title="Brief time"
            trailing={<input type="time" value={s.brief_time} step={300} aria-label="Brief time"
              onChange={(e) => changeTime(e.target.value)} onBlur={flushTime}
              className="rounded-lg bg-(--bg-inset) px-2.5 py-1 text-right text-[0.9412rem] text-(--text) [font-family:var(--font)]" />} />
        )}
        <Row icon={<Icon><CalendarCheck /></Icon>} title="Weekly recap (Sundays)" subtitle="Your week in review at 6 pm"
          trailing={<Switch label="Weekly recap" checked={s.recap_enabled !== false} onChange={(v) => void save({ recap_enabled: v })} />} />
        <Row icon={<Icon><Bell /></Icon>} title="rabbt nudges" subtitle="Streak at risk and race countdown alerts (max 2 a day, never 9 pm–7 am). Updates still show in chat."
          trailing={<Switch label="rabbt nudges" checked={s.moments_push !== false} onChange={(v) => void save({ moments_push: v })} />} />
      </Group>
      {me.dev.tools.length > 0 && (
        <Group label="Dev">
          {me.dev.tools.includes('simulate_workout') && (
            <Row icon={<Icon tone="muted"><FlaskConical /></Icon>} title="Simulate new workout" disabled={busy}
              onClick={() => void dev('simulate_workout', 'Simulated workout')} />
          )}
          {me.dev.tools.includes('brief_now') && (
            <Row icon={<Icon tone="muted"><FlaskConical /></Icon>} title="Send brief now" disabled={busy}
              onClick={() => void dev('brief_now', 'Morning brief')} />
          )}
          <Row icon={<Icon tone="muted"><Play /></Icon>} title="Motion lab" subtitle={lab ? 'Tap to close' : 'Try each animation'}
            onClick={() => setLab((v) => !v)} />
          {lab && <MotionLab />}
        </Group>
      )}
      {msg && <p className="-mt-4 break-words px-4 text-[0.7647rem] text-(--text-muted)">{msg}</p>}
    </>
  )
}
