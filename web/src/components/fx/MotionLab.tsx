// Dev-only "Motion lab" (Settings -> Dev): trigger each effect of the motion kit by hand.
import { useState } from 'react'
import { Moon, Waves, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'
import { HopPrints } from './HopPrints'
import { EmptyRabbit, HopIn, RabbitHop, Shake } from '@/components/anim'
import { StreakFlame } from './StreakFlame'
import { TodayFx, type TodayFxTone } from './TodayFx'
import { celebrate, reducedMotion, signalReplyDone, type BurstKind } from './motion'

const KINDS: BurstKind[] = ['xp', 'checkin', 'race', 'plan', 'challenge', 'badge', 'level']
const chip = 'hit-44 rounded-full border border-(--border-strong) bg-(--bg-surface) px-3 py-1.5 text-[0.7059rem] text-(--text) active:bg-(--bg-inset)'

export function MotionLab() {
  const [bar, setBar] = useState(20)
  const [peek, setPeek] = useState(0)
  const [flame, setFlame] = useState(0)
  const [risk, setRisk] = useState(false)
  const [today, setToday] = useState<{ tone: TodayFxTone; n: number } | null>(null)
  const [leap, setLeap] = useState(0)
  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      {reducedMotion() && <p className="text-[0.7059rem] text-(--warning-text)">Reduce motion is on: effects are off or static.</p>}
      <Lab label="Carrot burst">
        {KINDS.map((k) => <button key={k} type="button" className={chip} onClick={(e) => celebrate(e.currentTarget, k)}>{k}</button>)}
      </Lab>
      <Lab label="Hop prints">
        <span className="fx-bar min-w-0 flex-1">
          <span className="block h-1.5 overflow-hidden rounded-full bg-(--bg-elevated)">
            <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-700" style={{ width: `${bar}%` }} />
          </span>
          <HopPrints pct={bar} />
        </span>
        <button type="button" className={chip} onClick={() => setBar((b) => (b >= 100 ? 10 : Math.min(100, b + 20)))}>+20%</button>
      </Lab>
      <Lab label="Rabbit hop (progress bar)">
        <span className="fx-bar mt-4 min-w-0 flex-1">
          <span className="block h-1.5 overflow-hidden rounded-full bg-(--bg-elevated)">
            <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-500" style={{ width: `${bar}%` }} />
          </span>
          <RabbitHop pct={bar} />
        </span>
      </Lab>
      <Lab label="Empty rabbit · hop in · shake · tab wiggle">
        <EmptyRabbit key={`e${peek}`} size={44} mode={peek % 2 ? 'peek' : 'sleep'} />
        <HopIn key={`h${peek}`} index={1} className="rounded-lg border border-(--border) px-3 py-2 text-[0.7059rem] text-(--text)">Card</HopIn>
        <Shake trigger={peek}><span className="rounded-lg bg-(--danger-subtle) px-3 py-2 text-[0.7059rem] text-(--danger)">Oops</span></Shake>
        <button type="button" className={chip} onClick={() => setPeek((n) => n + 1)}>Replay</button>
        <button type="button" className={chip} onClick={signalReplyDone}>Wiggle Rabbit tab</button>
      </Lab>
      <Lab label="Streak flame">
        <span className="text-(--accent)"><StreakFlame streak={0} atRisk={risk} replay={flame} className="size-6" /></span>
        <button type="button" className={chip} onClick={() => setFlame((n) => n + 1)}>Flicker</button>
        <button type="button" className={chip} aria-pressed={risk} onClick={() => setRisk((r) => !r)}>At risk {risk ? 'on' : 'off'}</button>
      </Lab>
      <Lab label="Today card">
        {([['go', Zap], ['easy', Waves], ['rest', Moon]] as const).map(([t, I]) => (
          <button key={t} type="button" className={chip} onClick={() => setToday((x) => ({ tone: t, n: (x?.n ?? 0) + 1 }))}>
            <I className="mr-1 inline size-3.5" />{t}
          </button>
        ))}
        {today && (
          <span key={today.n} className="relative flex h-10 w-full items-center gap-2 rounded-xl border border-(--border) px-3">
            <TodayFx tone={today.tone} />
            <span className={cn('flex size-7 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)', today.tone === 'easy' && 'fx-sway')}>
              <Waves className="size-4" />
            </span>
            <span className="text-[0.7059rem] text-(--text-muted)">Today · {today.tone}</span>
          </span>
        )}
      </Lab>
      <Lab label="Level-up leap · press squish">
        <span className="relative h-10 w-28"><span key={leap} className="fx-leap-lane" style={{ top: 4 }}>
          {leap > 0 && <span className="fx-leap"><RabbitLogo size={28} /></span>}
        </span></span>
        <button type="button" className={chip} onClick={() => setLeap((n) => n + 1)}>Leap</button>
        <Button variant="primary" className="h-9 px-4">Press me</Button>
      </Lab>
      <p className="text-[0.6471rem] text-(--text-muted)">Pull to refresh: pull down at the top of Progress (touch only).</p>
    </div>
  )
}

function Lab({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}
