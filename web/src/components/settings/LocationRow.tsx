// Settings: the location Explore uses. Shows what's stored from "Use my location" (town,
// state, zip only) with "Forget my location".
import { useEffect, useState } from 'react'
import { MapPin } from 'lucide-react'
import { forgetLocation, getLocation, type LocationState } from '@/lib/explore2'
import { Icon, Row } from './Grouped'

export function LocationRow() {
  const [s, setS] = useState<LocationState | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getLocation().then(setS, () => {}) }, [])
  if (!s) return null
  const d = s.device
  const where = d ? [d.city, d.state].filter(Boolean).join(', ') || d.zip : s.resolved.label
  return (
    <>
      <Row icon={<Icon><MapPin /></Icon>} title="Location for Explore"
        subtitle={d ? `${where} · from your device (town and zip only)` : where ? `${where} · from your profile` : 'Not set. Explore can ask when you tap "Use my location".'} />
      {d && (
        <Row title="Forget my location" danger center disabled={busy}
          onClick={() => { setBusy(true); forgetLocation().then(setS, () => {}).finally(() => setBusy(false)) }} />
      )}
    </>
  )
}
