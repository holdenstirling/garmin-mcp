// "My area" for Local (clubs, leagues, meetups) and Schedule > Discover: one tappable bar at the
// top ("Near Denver, CO · within 10 mi") that opens a sheet with "Use my location" (the browser
// asks; the server keeps only a rough spot, lib/explore2), a zip fallback when location is
// blocked, and how far to look (2-50 mi, shown in the athlete's units). Every change fires
// AREA_CHANGED_EVENT so each screen showing results reloads for the new area.
import { useEffect, useState } from 'react'
import { ChevronRight, LocateFixed, MapPin } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Chip, Field, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { radiusLabel } from '@/lib/activity'
import {
  forgetLocation, getLocation, saveZipLocation, setAreaRadius, shareDeviceLocation, type LocationState,
} from '@/lib/explore2'

export const AREA_CHANGED_EVENT = 'rabbit:area-changed'
const RADII = [2, 5, 10, 25, 50]

function announce(s: LocationState) {
  try { window.dispatchEvent(new CustomEvent<LocationState>(AREA_CHANGED_EVENT, { detail: s })) } catch { /* old browsers */ }
}

/** Reload when the area changes (the detail is the new location state). */
export function useAreaChanged(fn: (s: LocationState) => void) {
  useEffect(() => {
    const on = (e: Event) => fn((e as CustomEvent<LocationState>).detail)
    window.addEventListener(AREA_CHANGED_EVENT, on)
    return () => window.removeEventListener(AREA_CHANGED_EVENT, on)
  }, [fn])
}

export function areaLabel(s: LocationState | null): string {
  const d = s?.saved
  if (d) return [d.city, d.state].filter(Boolean).join(', ') || d.zip
  return s?.resolved.label || ''
}

export function AreaBar({ imperial, what = 'clubs, leagues and meetups', className }: {
  imperial: boolean
  /** "clubs, leagues and meetups" / "races and events": shown in the sheet */
  what?: string
  className?: string
}) {
  const [s, setS] = useState<LocationState | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => { getLocation().then(setS, () => {}) }, [])
  useAreaChanged(setS)
  const where = areaLabel(s)
  const r = s?.radius_mi ?? 10
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog"
        aria-label={where ? `Your area: near ${where}, within ${radiusLabel(r, imperial)}. Change` : 'Set your area'}
        className={cn('flex min-h-14 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-2.5 text-left active:bg-(--bg-inset)', className)}>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
          <MapPin className="size-5" />
        </span>
        <span className="min-w-0 flex-1" aria-hidden>
          {s === null ? <span className="block text-body text-(--text-muted)">Finding your area…</span>
            : where ? <>
                <span className="block text-body font-semibold leading-snug text-(--text)">Near {where}</span>
                <span className="block text-meta text-(--text-muted)">Within {radiusLabel(r, imperial)}</span>
              </>
            : <span className="block text-body font-semibold text-(--accent)">Set your area to see what's near you</span>}
        </span>
        <span className="shrink-0 text-body font-semibold text-(--accent)" aria-hidden>{where ? 'Change' : 'Set'}</span>
        <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
      </button>
      {open && <AreaSheet state={s} imperial={imperial} what={what} onClose={() => setOpen(false)}
        onChanged={(n) => { setS(n); announce(n) }} />}
    </>
  )
}

function AreaSheet({ state, imperial, what, onClose, onChanged }: {
  state: LocationState | null; imperial: boolean; what: string; onClose: () => void; onChanged: (s: LocationState) => void
}) {
  const [busy, setBusy] = useState<'locate' | 'zip' | 'radius' | 'forget' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [zip, setZip] = useState('')
  const [zipOpen, setZipOpen] = useState(false)
  const where = areaLabel(state)
  const r = state?.radius_mi ?? 10
  const saved = state?.saved

  async function act(k: NonNullable<typeof busy>, fn: () => Promise<LocationState>) {
    setBusy(k); setErr(null)
    try { onChanged(await fn()) } catch (e) {
      setErr((e as Error).message)
      if (k === 'locate') setZipOpen(true) // blocked or failed: offer the zip right away
    } finally { setBusy(null) }
  }

  return (
    <Sheet title="Your area" onClose={onClose}
      footer={
        <div className="border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          <Button variant="primary" className="h-11 w-full text-body" onClick={onClose}>Done</Button>
        </div>
      }>
      <div className="flex flex-col gap-4">
        <p className="text-small leading-snug text-(--text-secondary)">
          {where ? <>Showing {what} near <span className="font-semibold text-(--text)">{where}</span>.</> : `Pick where to look for ${what}.`}
          {' '}rabbt keeps only a rough spot (about 1 km), never your exact location.
        </p>

        <Button variant="default" className="h-12 justify-start gap-2.5 px-4 text-body" loading={busy === 'locate'}
          onClick={() => void act('locate', shareDeviceLocation)}>
          <LocateFixed className="size-5 text-(--accent)" aria-hidden />
          {saved?.source === 'device' ? 'Update to where I am now' : 'Use my location'}
        </Button>
        {busy === 'locate' && <RabbitLoader className="py-1" label="Finding you" cycle={['Asking your phone…', 'Finding your neighborhood…']} />}

        {zipOpen ? (
          <Field label="Or enter a zip code">
            <div className="flex items-center gap-2">
              <input className={inputCls} inputMode="numeric" autoComplete="postal-code" maxLength={5} placeholder="80223" value={zip}
                onChange={(e) => setZip(e.target.value.replace(/\D/g, '').slice(0, 5))}
                onKeyDown={(e) => { if (e.key === 'Enter' && zip.length === 5) void act('zip', () => saveZipLocation(zip)) }} />
              <Button variant="default" className="h-11 shrink-0 px-4 text-small" loading={busy === 'zip'} disabled={zip.length !== 5}
                onClick={() => void act('zip', () => saveZipLocation(zip))}>Use zip</Button>
            </div>
          </Field>
        ) : (
          <button type="button" className="hit-44 self-start text-small font-medium text-(--accent)" onClick={() => setZipOpen(true)}>
            Enter a zip code instead
          </button>
        )}
        {err && <p className="text-small text-(--danger)" role="alert">{err}</p>}

        <Field label="How far to look">
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="How far to look">
            {RADII.map((mi) => (
              <Chip key={mi} selected={r === mi} disabled={busy != null}
                onClick={() => { if (mi !== r) void act('radius', () => setAreaRadius(mi)) }}>
                {radiusLabel(mi, imperial)}
              </Chip>
            ))}
          </div>
        </Field>

        {saved && (
          <button type="button" className="hit-44 self-start text-meta text-(--text-muted) underline-offset-2 hover:underline"
            disabled={busy != null} onClick={() => void act('forget', forgetLocation)}>
            Forget this spot and use my home city
          </button>
        )}
      </div>
    </Sheet>
  )
}
