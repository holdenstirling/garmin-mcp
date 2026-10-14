// Settings: the location Explore uses. Shows what's saved from "Use my location" or a typed zip
// (town, state, zip only; the server keeps a rough ~1 km spot), the "Use my location for local
// picks" toggle (Near you places and groups) and "Forget my location".
import { useEffect, useState } from 'react'
import { MapPin } from 'lucide-react'
import { forgetLocation, getLocation, setUseForLocal, type LocationState } from '@/lib/explore2'
import { Icon, Row, Switch } from './Grouped'

export function LocationRow() {
  const [s, setS] = useState<LocationState | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getLocation().then(setS, () => {}) }, [])
  if (!s) return null
  const d = s.saved ?? s.device
  const where = d ? [d.city, d.state].filter(Boolean).join(', ') || d.zip : s.resolved.label
  const from = d ? (d.source === 'manual' ? 'from the zip you entered' : 'from your device (town and zip only)') : 'from your profile'
  const toggle = (on: boolean) => {
    setBusy(true)
    setUseForLocal(on).then(setS, () => {}).finally(() => setBusy(false))
  }
  return (
    <>
      <Row icon={<Icon><MapPin /></Icon>} title="Location for Explore"
        subtitle={where ? `${where} · ${from}` : 'Not set. Explore shows races across the US until you add one.'} />
      <Row title="Use my location for local picks" subtitle="Courts, tracks, trailheads and group runs near you"
        trailing={<Switch label="Use my location for local picks" checked={s.use_for_local} disabled={busy} onChange={toggle} />} />
      {d && (
        <Row title="Forget my location" danger center disabled={busy}
          onClick={() => { setBusy(true); forgetLocation().then(setS, () => {}).finally(() => setBusy(false)) }} />
      )}
    </>
  )
}
