// Share by text (server: sharelinks.py): a public read-only link for one workout, recorded
// workout, event, club or invite, plus a friendly message. Opened by anyone (no login) from
// Messages, WhatsApp, email... No heart rate or location unless the sharer includes HR.
import { getJSON, sendJSON } from '@/lib/api'

export type ShareKind = 'workout' | 'activity' | 'event' | 'club' | 'invite'
export type ShareTarget = { kind: ShareKind; ref?: string; label: string }
export type ShareLink = { id: string; url: string; title: string; text: string }
export type SharedLinkRow = { id: string; kind: ShareKind; title: string; created: number; views: number }

export const createShareLink = (t: ShareTarget, opts: { include_hr?: boolean; include_code?: boolean } = {}) =>
  sendJSON<ShareLink>('POST', '/api/sharelinks', { kind: t.kind, ref: t.ref ?? '', ...opts })
export const listShareLinks = () => getJSON<{ links: SharedLinkRow[] }>('/api/sharelinks')
export const revokeShareLink = (id: string) => sendJSON<{ ok: boolean }>('DELETE', `/api/sharelinks/${id}`, {})

/** sms: link with a prefilled body (iOS and Android both read `?&body=`). */
export function smsHref(text: string, url: string): string {
  return `sms:?&body=${encodeURIComponent(`${text} ${url}`.trim())}`
}

export const canNativeShare = () => typeof navigator !== 'undefined' && typeof navigator.share === 'function'

/** The phone's own share menu (Messages first on iOS). 'cancelled' when the person backs out. */
export async function nativeShare(title: string, text: string, url: string): Promise<'shared' | 'cancelled' | 'unsupported'> {
  if (!canNativeShare()) return 'unsupported'
  try {
    await navigator.share({ title, text, url })
    return 'shared'
  } catch (e) {
    return (e as DOMException)?.name === 'AbortError' ? 'cancelled' : 'unsupported'
  }
}

export const SHARE_KIND_LABEL: Record<ShareKind, string> = {
  workout: 'Planned workout', activity: 'Workout', event: 'Event', club: 'Club', invite: 'Invite',
}
