// Apple Watch (server: applehealth.py): the athlete's own iPhone Shortcut sends recent workouts
// from Apple Health to Rabbit with a personal import key. The key is shown once when created
// (only its hash is stored); creating a new one stops the old one. Imported workouts are
// display-only (never sent to Rabbit's AI) and count once if Garmin has them too.
import { getJSON, postJSON } from '@/lib/api'

export type AppleHealth = {
  on: boolean
  available: boolean
  /** unix seconds */
  created: number | null
  last_import: number | null
  last_received: number | null
  last_new: number | null
  /** workouts imported from Apple Watch and still stored */
  workouts: number
  /** the full https URL the Shortcut posts to */
  endpoint: string
}

export const getAppleHealth = () => getJSON<AppleHealth>('/api/apple-health')
/** A new import key (the old one stops working). The key is in the reply only this once. */
export const newAppleKey = () => postJSON<AppleHealth & { key: string }>('/api/apple-health/key', {})
/** Turn Apple Watch off: revokes the key; `remove` also deletes the workouts it imported. */
export const disconnectAppleHealth = (remove: boolean) => postJSON<AppleHealth>('/api/apple-health/disconnect', { remove })

/** What the Shortcut's Text action holds for each workout; the ⟨…⟩ parts become Repeat Item details. */
export const TEXT_TEMPLATE =
  '{"type":"⟨Workout Type⟩","start":"⟨Start Date⟩","end":"⟨End Date⟩","duration":"⟨Duration⟩","distance":"⟨Distance⟩"}'

/** "Last import 2 h ago · 12 workouts" / "Waiting for your first import". */
export function importLine(h: Pick<AppleHealth, 'last_import' | 'workouts'>, now = Date.now()): string {
  if (!h.last_import) return 'Waiting for your Shortcut’s first run'
  const min = Math.max(0, Math.round((now - h.last_import * 1000) / 60000))
  const ago = min < 1 ? 'just now' : min < 60 ? `${min} min ago` : min < 60 * 24 ? `${Math.round(min / 60)} h ago`
    : Math.round(min / 1440) === 1 ? 'yesterday' : `${Math.round(min / 1440)} days ago`
  return `Last import ${ago} · ${h.workouts} workout${h.workouts === 1 ? '' : 's'}`
}

export async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true } catch { return false }
}
