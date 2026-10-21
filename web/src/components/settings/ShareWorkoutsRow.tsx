// Me -> "Share my workouts with friends" (community.py `share_workouts`): each newly synced
// workout goes to the people who follow you as a compact card (sport, time, distance; never
// heart rate; a route map only if you also share maps). "On" also covers a "share my workouts"
// saved earlier in friends settings (sharing_source "earlier"), said so in the subtitle.
// Hidden until the setting loads (and for coach accounts).
import { useEffect, useState } from 'react'
import { Share2 } from 'lucide-react'
import { Icon, Row, Switch } from '@/components/settings/Grouped'
import { ago, getCommunitySettings, putCommunitySettings, sharingWorkouts } from '@/lib/community'

export function ShareWorkoutsRow() {
  const [on, setOn] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [last, setLast] = useState<number | null>(null)
  const [earlier, setEarlier] = useState(false)
  useEffect(() => {
    let live = true
    getCommunitySettings().then((r) => {
      if (!live) return
      setOn(sharingWorkouts(r.settings)); setLast(r.settings.last_shared_at ?? null); setEarlier(r.settings.sharing_source === 'earlier')
    }, () => {})
    return () => { live = false }
  }, [])
  if (on === null) return null
  async function change(v: boolean) {
    const prev = on
    setOn(v); setError(null)
    try {
      const s = (await putCommunitySettings({ share_workouts: v })).settings
      setOn(sharingWorkouts(s)); setLast(s.last_shared_at ?? null); setEarlier(s.sharing_source === 'earlier')
    }
    catch (e) { setOn(prev); setError((e as Error).message) }
  }
  return (
    <Row icon={<Icon><Share2 /></Icon>} title="Share my workouts with friends"
      subtitle={error ?? (on
        ? `On${earlier ? ' (you chose this in friends settings)' : ''}: ${last ? `last shared ${ago(last) === 'now' ? 'just now' : `${ago(last)} ago`}` : 'your next workout posts after it syncs'}. Followers see sport, time and distance, never heart rate. Maps only if you share them.`
        : 'Off: only you see your workouts. Turn on so friends see them on the Feed.')}
      trailing={<Switch label="Share my workouts with friends" checked={on} onChange={(v) => void change(v)} />} />
  )
}
