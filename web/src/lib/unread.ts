// App icon badge (Badging API) + the Rabbit home's one-tap actions (unread.py,
// quickactions.py, routes in friends_web.py). The service worker also sets the badge from
// each push's `badge` count; here it's set on load/return and after something is viewed.
import { getJSON, postJSON } from '@/lib/api'

export type UnreadCounts = { cheers: number; requests: number; invites: number; coach: number; total: number }
export type SeenKind = 'cheers' | 'requests' | 'invites'

type BadgeNav = Navigator & { setAppBadge?: (n?: number) => Promise<void>; clearAppBadge?: () => Promise<void> }

/** Set (or clear) the installed app's icon badge; a no-op where the Badging API is missing. */
export function setAppBadge(n: number): void {
  const nav = navigator as BadgeNav
  try {
    if (n > 0) void nav.setAppBadge?.(Math.min(n, 999))?.catch(() => {})
    else void nav.clearAppBadge?.()?.catch(() => {})
  } catch { /* unsupported */ }
}

export const getUnread = () => getJSON<UnreadCounts>('/api/unread')

/** Re-read the unread total and update the icon badge (errors, e.g. coach 403, are ignored). */
export async function syncAppBadge(): Promise<UnreadCounts | null> {
  try { const c = await getUnread(); setAppBadge(c.total); return c } catch { return null }
}

/** The person looked at Community / People / Clubs: clear those and update the badge. */
export async function markSeen(kind: SeenKind): Promise<void> {
  try { const c = await postJSON<UnreadCounts>('/api/unread/seen', { kind }); setAppBadge(c.total) } catch { /* best effort */ }
}

/** On load and whenever the app comes back to the foreground. Returns a cleanup. */
export function startBadgeSync(): () => void {
  void syncAppBadge()
  const onVis = () => { if (document.visibilityState === 'visible') void syncAppBadge() }
  document.addEventListener('visibilitychange', onVis)
  return () => document.removeEventListener('visibilitychange', onVis)
}

// ------------------------------------------------------------ quick actions --
export type QuickAction =
  | { kind: 'feel'; label: string; activity_id: number; date: string; sport: string; title: string; minutes: number | null; km: number | null }
  | { kind: 'rsvp'; label: string; club_id: string; club: string; meetup_id: string; title: string; next: string; where: string; going: number }
  | { kind: 'cheer'; label: string; post_id: string; name: string; what: string; sport: string | null }
  | { kind: 'watch'; label: string; session_id: string; date: string; title: string; sport: string | null }

export const getQuickActions = () => getJSON<{ actions: QuickAction[] }>('/api/home/quick')
