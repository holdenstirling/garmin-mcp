// Home "Readiness snapshot": last night's sleep, HRV against your usual, the readiness score
// (Garmin training readiness or Oura, per the recovery source you chose) and form (from the
// fitness/fatigue series), then one plain call for today: Push today / Normal day / Ease off.
// Deterministic (lib/homedata readinessCall); Oura numbers are only displayed, never sent to
// Rabbit's AI. Tap: Progress (recovery detail).
import { useEffect, useState } from 'react'
import { ChevronRight, Gauge, HeartPulse, Moon, Zap } from 'lucide-react'
import { getRecovery, type RecoveryData } from '@/lib/sources'
import { fmtH, homeLoad, readinessCall, type Call } from '@/lib/homedata'
import { cn } from '@/lib/utils'

const CALL: Record<Call, { label: string; cls: string }> = {
  push: { label: 'Push today', cls: 'text-(--accent)' },
  normal: { label: 'Normal day', cls: 'text-(--text)' },
  ease: { label: 'Ease off', cls: 'text-(--warning-text)' },
}

type Data = { rec: RecoveryData | null; tsb: number | null; source: string | null }

function Cell({ icon: Icon, value, label }: { icon: typeof Moon; value: string; label: string }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center gap-0.5 px-1">
      <Icon className="size-3.5 text-(--text-muted)" aria-hidden />
      <span className="font-mono text-[0.8824rem] font-semibold tabular-nums text-(--text)">{value}</span>
      <span className="truncate text-[0.6471rem] text-(--text-muted)">{label}</span>
    </div>
  )
}

export function ReadinessSnapshot({ refreshKey, onOpen, onConnect }: {
  refreshKey: number; onOpen: () => void; onConnect: () => void
}) {
  const [data, setData] = useState<Data | null>(null)
  useEffect(() => {
    let live = true
    Promise.allSettled([getRecovery(), homeLoad(refreshKey)]).then(([r, l]) => {
      if (!live) return
      let rec: RecoveryData | null = null
      let source: string | null = null
      if (r.status === 'fulfilled') {
        const want = r.value.sources.recovery
        const pick = want === 'oura' ? r.value.oura ?? r.value.garmin : r.value.garmin ?? r.value.oura
        if (pick?.latest) { rec = pick; source = pick === r.value.oura ? 'Oura' : 'Garmin' }
      }
      const tsb = l.status === 'fulfilled' ? l.value.now?.tsb ?? null : null
      setData({ rec, tsb: tsb == null ? null : Math.round(tsb), source })
    })
    return () => { live = false }
  }, [refreshKey])

  if (!data) return <div className="skeleton h-[118px] rounded-xl" aria-label="Loading readiness" />
  const latest = data.rec?.latest ?? null
  if (!latest && data.tsb == null) {
    return (
      <button type="button" onClick={onConnect}
        className="flex min-h-14 w-full items-center gap-3 rounded-xl border border-dashed border-(--border-strong) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
        <HeartPulse className="size-5 shrink-0 text-(--accent)" aria-hidden />
        <span className="min-w-0 flex-1 text-[0.7647rem] text-(--text-secondary)">
          Connect Garmin or Oura to see sleep, HRV and how ready you are today.
        </span>
        <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
      </button>
    )
  }
  const hrvBase = data.rec?.baseline?.hrv ?? (latest as { hrv_week?: number } | null)?.hrv_week ?? null
  const { call, why } = readinessCall({
    readiness: latest?.readiness ?? null, sleepH: latest?.sleep_hours ?? null,
    hrv: latest?.hrv ?? null, hrvBase, tsb: data.tsb,
  })
  const hrvPct = latest?.hrv != null && hrvBase ? Math.round(((latest.hrv - hrvBase) / hrvBase) * 100) : null
  const cells: { icon: typeof Moon; value: string; label: string }[] = []
  if (latest?.sleep_hours != null) cells.push({ icon: Moon, value: fmtH(latest.sleep_hours), label: 'sleep' })
  if (latest?.hrv != null) cells.push({ icon: HeartPulse, value: `${latest.hrv}`, label: hrvPct == null ? 'HRV ms' : `HRV ${hrvPct >= 0 ? '+' : ''}${hrvPct}%` })
  if (latest?.readiness != null) cells.push({ icon: Gauge, value: `${latest.readiness}`, label: data.source === 'Oura' ? 'Oura readiness' : 'readiness' })
  if (data.tsb != null) cells.push({ icon: Zap, value: `${data.tsb > 0 ? '+' : ''}${data.tsb}`, label: 'form' })
  const label = `Readiness: ${CALL[call].label}. ${why} ${cells.map((c) => `${c.label} ${c.value}`).join(', ')}. Open Progress`
  return (
    <button type="button" onClick={onOpen} aria-label={label}
      className="flex w-full flex-col gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
      <span className="flex w-full items-start gap-2" aria-hidden>
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Today's readiness</span>
          <span className={cn('block text-[1rem] font-semibold leading-snug', CALL[call].cls)}>{CALL[call].label}</span>
          <span className="block text-[0.7059rem] leading-snug text-(--text-secondary)">{why}</span>
        </span>
        <ChevronRight className="mt-1 size-4 shrink-0 text-(--text-muted)" />
      </span>
      {cells.length > 0 && (
        <span className="flex w-full divide-x divide-(--border) rounded-lg bg-(--bg-inset) py-2" aria-hidden>
          {cells.map((c) => <Cell key={c.label} {...c} />)}
        </span>
      )}
    </button>
  )
}
