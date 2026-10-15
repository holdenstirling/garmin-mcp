// Me -> "Share my workouts with friends" (community.py `share_workouts`): each newly synced
// workout goes to the people who follow you as a compact card (sport, time, distance; never
// heart rate, maps or where). Hidden until the setting loads (and for coach accounts).
import { useEffect, useState } from 'react'
import { Share2 } from 'lucide-react'
import { Icon, Row, Switch } from '@/components/settings/Grouped'
import { getCommunitySettings, putCommunitySettings, sharingWorkouts } from '@/lib/community'

export function ShareWorkoutsRow() {
  const [on, setOn] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getCommunitySettings().then((r) => { if (live) setOn(sharingWorkouts(r.settings)) }, () => {})
    return () => { live = false }
  }, [])
  if (on === null) return null
  async function change(v: boolean) {
    const prev = on
    setOn(v); setError(null)
    try { setOn(sharingWorkouts((await putCommunitySettings({ share_workouts: v })).settings)) }
    catch (e) { setOn(prev); setError((e as Error).message) }
  }
  return (
    <Row icon={<Icon><Share2 /></Icon>} title="Share my workouts with friends"
      subtitle={error ?? (on ? 'Followers see sport, time and distance. Never heart rate or where.' : 'Private: only you see them')}
      trailing={<Switch label="Share my workouts with friends" checked={on} onChange={(v) => void change(v)} />} />
  )
}
