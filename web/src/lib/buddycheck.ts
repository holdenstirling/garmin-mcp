// Check-in buddy: "I'm starting" / "I'm back" pings to one friend (no GPS, no location stored).
import { getJSON, postJSON } from '@/lib/api'
import type { SocialUser } from '@/lib/social'

export type BuddyState = {
  buddy: string | null; buddy_user: SocialUser | null
  active: { started: number; back_by: number } | null
}
export const getBuddy = () => getJSON<BuddyState>('/api/buddy')
export const setBuddy = (buddy: string | null) => postJSON<BuddyState>('/api/buddy', { action: 'set', buddy })
export const startOut = (minutes: number) => postJSON<BuddyState>('/api/buddy', { action: 'start', minutes })
export const backSafe = () => postJSON<BuddyState>('/api/buddy', { action: 'back' })
