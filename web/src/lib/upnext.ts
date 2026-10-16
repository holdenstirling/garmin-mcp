// Rabbit home "Up next" (server: upnext.py) and the first visit without Garmin.
import { requestConnect } from '@/lib/connections'
import { getJSON } from '@/lib/api'
import type { Today, TodayActionKind, TodayTone } from '@/lib/live'

export type UpNextKind = 'session' | 'today' | 'rest' | 'build_plan' | 'group_run' | 'set_goal'
/** start: workout day · today: the Today card's own action · group: Community → Clubs */
export type UpNextPrimary = 'start' | 'today' | 'open_plan' | 'build_plan' | 'group' | 'set_goal' | TodayActionKind
export type UpNextGroup = {
  source: 'club' | 'directory'; name: string; club: string; club_id: string | null; meetup_id: string | null
  when: string; where: string; rsvp: 'going' | 'maybe' | null; url: string | null; listing_id: string | null
}
export type UpNext = {
  kind: UpNextKind; tone: TodayTone | ''; headline: string; detail: string
  primary: { kind: UpNextPrimary; label: string }
  secondary: { kind: 'send_to_watch'; label: string } | null
  extra: { kind: 'today'; label: string } | null
  session: { id: string | null; title: string; minutes: number | null; sport: string; target: string | null; on_watch: boolean; syncable: boolean } | null
  tomorrow: { date: string; rest: boolean; title: string; sport: string; minutes: number | null; id: string | null } | null
  group: UpNextGroup | null
  signals: Today['signals']
  /** the Today card it wraps (null when it couldn't be built) */
  today: Today | null
  garmin: boolean
}
export const getUpNext = () => getJSON<UpNext>('/api/upnext')

export type FirstVisitItem = { id: 'clubs' | 'events' | 'feed' | 'friends'; title: string; detail: string }
export type FirstVisit = {
  show: boolean; garmin: boolean; inviter: string | null; title: string; items: FirstVisitItem[]
  primary: { kind: 'connect_garmin'; label: string; detail: string }
}
export const getFirstVisit = () => getJSON<FirstVisit>('/api/firstvisit')

/** Garmin-only reads answer 409 {code: "garmin_not_connected"} (lib/api attaches `code`). */
export const GARMIN_MISSING = 'garmin_not_connected'
export function isGarminMissing(e: unknown): boolean {
  return !!e && typeof e === 'object' && (e as { code?: unknown }).code === GARMIN_MISSING
}

/** Any screen can ask the app to open the Connect Garmin popup (lib/connections.ts; Chat.tsx listens). */
export { CONNECT_EVENT as CONNECT_GARMIN_EVENT } from '@/lib/connections'
export function requestConnectGarmin(): void { requestConnect('garmin') }
