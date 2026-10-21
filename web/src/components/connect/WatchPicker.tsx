// "Which watch do you wear?": where every generic "Connect your watch" button lands
// (requestWatchPicker in lib/connections; screens/Chat.tsx shows it). Big tiles, one tap:
// Garmin, Apple Watch and Oura open their own connect popup (requestConnect), COROS opens the
// coming-soon sheet ("I want this"), and "Something else" says what works without one.
import { useEffect, useState } from 'react'
import { ChevronRight, Clock, PencilLine } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { AppTile } from '@/components/connect/ConnectSheet'
import { SoonSheet, SoonTile } from '@/components/connect/SoonSheet'
import { RabbitNap } from '@/components/anim'
import { getConnections, requestConnect, type ConnApp, type Connections, type SoonApp } from '@/lib/connections'
import { cn } from '@/lib/utils'

const WATCHES: { app: ConnApp; name: string; line: string }[] = [
  { app: 'garmin', name: 'Garmin', line: 'Sign in once. Workouts, sleep and recovery sync on their own.' },
  { app: 'apple', name: 'Apple Watch', line: 'A 5 minute iPhone Shortcut sends each workout to rabbt.' },
  { app: 'oura', name: 'Oura ring', line: 'Sleep, readiness and the workouts your ring picks up.' },
]

export function WatchPicker({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Connections | null>(null)
  const [soon, setSoon] = useState<SoonApp | null>(null)
  const [other, setOther] = useState(false)
  useEffect(() => {
    let live = true
    getConnections().then((c) => { if (live) setData(c) }, () => {})
    return () => { live = false }
  }, [])

  if (soon) return <SoonSheet app={soon} onClose={() => setSoon(null)} onChanged={setSoon} />

  const on = (app: ConnApp) => !!data?.apps.find((a) => a.id === app)?.connected
  const shown = WATCHES.filter((w) => !data || data.apps.some((a) => a.id === w.app && (a.available || a.connected)))
  const coros = data?.soon?.find((a) => a.id === 'coros') ?? null
  const pick = (app: ConnApp) => { onClose(); window.setTimeout(() => requestConnect(app), 0) }

  return (
    <Sheet title="Connect your watch" onClose={onClose} bodyClassName="gap-4">
      <div className="flex flex-col items-center gap-1.5 pt-1 text-center">
        <RabbitNap size={48} mode="cheer" />
        <p className="font-display text-title leading-tight text-(--brand)">Which watch do you wear?</p>
        <p className="max-w-xs text-body leading-snug text-(--text-secondary)">
          Pick yours and your workouts show up on their own. You can add more later.
        </p>
      </div>
      <ul className="flex flex-col gap-2.5" aria-label="Watches and rings">
        {shown.map((w) => (
          <li key={w.app}>
            <button type="button" onClick={() => pick(w.app)}
              className="flex min-h-[76px] w-full items-center gap-3.5 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3 text-left shadow-[var(--shadow-sm)] transition-transform active:scale-[0.98] active:bg-(--bg-inset)">
              <AppTile app={w.app} size={48} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-body-lg font-semibold leading-snug text-(--text)">
                  {w.name}
                  {on(w.app) && <span className="rounded-full bg-(--accent-subtle) px-2 py-0.5 text-caption font-semibold text-(--accent)">Connected</span>}
                </span>
                <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">{w.line}</span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
            </button>
          </li>
        ))}
        {coros && (
          <li>
            <button type="button" onClick={() => setSoon(coros)}
              className="flex min-h-[76px] w-full items-center gap-3.5 rounded-xl border border-dashed border-(--border) px-4 py-3 text-left active:bg-(--bg-inset)">
              <SoonTile app="coros" size={48} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-body-lg font-semibold leading-snug text-(--text)">
                  COROS
                  <span className="inline-flex items-center gap-1 rounded-full bg-(--bg-inset) px-2 py-0.5 text-caption font-medium text-(--text-secondary)">
                    <Clock className="size-3" aria-hidden />Soon
                  </span>
                </span>
                <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">Not ready yet. Tap “I want this” so we build it next.</span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
            </button>
          </li>
        )}
        <li>
          <button type="button" onClick={() => setOther((o) => !o)} aria-expanded={other}
            className="flex min-h-14 w-full items-center gap-3.5 rounded-xl px-4 py-2.5 text-left active:bg-(--bg-inset)">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-[22%] bg-(--bg-inset) text-(--text-secondary)" aria-hidden>
              <PencilLine className="size-5" />
            </span>
            <span className="min-w-0 flex-1 text-body font-medium text-(--text)">Something else, or no watch</span>
            <ChevronRight className={cn('size-5 shrink-0 text-(--text-muted) transition-transform', other && 'rotate-90')} aria-hidden />
          </button>
          {other && (
            <p className="mx-4 mt-1 rounded-xl bg-(--bg-inset) px-3.5 py-3 text-small leading-snug text-(--text-secondary)">
              No problem. Plans, clubs, events and friends all work without one, and you can still
              post a workout to the Feed with a photo and a few words.
            </p>
          )}
        </li>
      </ul>
      <p className="text-center text-caption text-(--text-muted)">Change these any time in Me, Connected apps.</p>
    </Sheet>
  )
}
