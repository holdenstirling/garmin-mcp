// Find friends (server: friendfind.py, routes friendfind_web.py): search by @handle, name,
// exact email or phone; contacts (picked on the phone, pasted, or a shared .vcf) compared on
// the server and thrown away; People you may know; my @handle, phone and who can find me.
// openFindFriends() opens the screen from anywhere (screens/Chat listens).
import { getJSON, sendJSON } from '@/lib/api'
import { milestone } from '@/lib/traction'
import type { SocialUser } from '@/lib/social'

export type FindUser = SocialUser & { handle?: string }
export type FindStatus = 'following' | 'requested' | 'none'
export type FindRow = { user: FindUser; reason: string; status: FindStatus; follows_you: boolean; mutual?: number }
export type FindMe = { handle: string; phone: string | null; find: { name: boolean; email: boolean; phone: boolean }; invite_link: string }
export type Contact = { name: string; emails: string[]; phones: string[] }
export type MatchResult = { on_rabbit: { index: number; status: FindStatus; follows_you: boolean; user: FindUser }[]; checked: number; invite_link: string }

const P = '/api/friends'
export const searchPeople = (q: string) => getJSON<{ people: FindRow[] }>(`${P}/search?q=${encodeURIComponent(q)}`)
export const getSuggestedPeople = () => getJSON<{ people: FindRow[] }>(`${P}/suggested`)
export const dismissSuggestion = (uid: string) => sendJSON<{ ok: boolean }>('POST', `${P}/suggested/${encodeURIComponent(uid)}/dismiss`, {})
export const followPerson = (uid: string) => sendJSON<{ ok: boolean; status: FindStatus; message: string }>('POST', `${P}/follow`, { user_id: uid })
  .then((r) => { milestone('follow'); return r })
export const getFindMe = () => getJSON<FindMe>(`${P}/me`)
export const putFindMe = (patch: Partial<{ handle: string; phone: string | null; find: Partial<FindMe['find']> }>) =>
  sendJSON<FindMe>('PUT', `${P}/me`, patch)
export const matchContacts = (contacts: Contact[]) =>
  sendJSON<MatchResult>('POST', `${P}/match`, { contacts: contacts.map((c) => ({ emails: c.emails, phones: c.phones })) })

export const MATCH_MAX = 500

// --------------------------------------------------------------- opening --
export const OPEN_FRIENDS_EVENT = 'rabbit:open-friends'
export type FriendsOpen = { section?: 'me'; add?: string; q?: string }
export function openFindFriends(detail: FriendsOpen = {}) {
  try { window.dispatchEvent(new CustomEvent(OPEN_FRIENDS_EVENT, { detail })) } catch { /* old browsers */ }
}

// -------------------------------------------------------------- contacts --
const EMAIL = /[^\s<>,;:"'()[\]]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}/g
const PHONE = /(?:\+|00)?[\d][\d\s().-]{6,}\d/g

/** Typed or pasted text: one contact per line ("Jesse 303-555-1234" or just an address). */
export function parsePasted(text: string): Contact[] {
  const out: Contact[] = []
  for (const line of text.split(/\r?\n|;/)) {
    const emails = [...line.matchAll(EMAIL)].map((m) => m[0].toLowerCase())
    const rest = line.replace(EMAIL, ' ')
    const phones = [...rest.matchAll(PHONE)].map((m) => m[0].trim()).filter((p) => p.replace(/\D/g, '').length >= 7)
    if (!emails.length && !phones.length) continue
    const name = rest.replace(PHONE, ' ').replace(/[<>,"]/g, ' ').replace(/\s+/g, ' ').trim()
    out.push({ name, emails, phones })
  }
  return dedupe(out)
}

/** A shared contact card file (iPhone Contacts: Share Contact, or Export from a Mac). */
export function parseVcf(text: string): Contact[] {
  const out: Contact[] = []
  // Unfold continued lines first (a line starting with a space continues the previous one).
  const lines = text.replace(/\r\n[ \t]/g, '').replace(/\n[ \t]/g, '').split(/\r?\n/)
  let cur: Contact | null = null
  for (const raw of lines) {
    const line = raw.trim()
    const up = line.toUpperCase()
    if (up === 'BEGIN:VCARD') { cur = { name: '', emails: [], phones: [] }; continue }
    if (up === 'END:VCARD') { if (cur && (cur.emails.length || cur.phones.length)) out.push(cur); cur = null; continue }
    if (!cur) continue
    const i = line.indexOf(':')
    if (i < 0) continue
    const key = line.slice(0, i).split(';')[0].split('.').pop()!.toUpperCase()
    const val = line.slice(i + 1).trim()
    if (key === 'FN' && val) cur.name = unescapeVcf(val)
    else if (key === 'N' && !cur.name) cur.name = unescapeVcf(val.split(';').slice(0, 2).reverse().join(' ').trim())
    else if (key === 'EMAIL' && val) cur.emails.push(val.toLowerCase())
    else if (key === 'TEL' && val) cur.phones.push(val.replace(/^tel:/i, ''))
  }
  return dedupe(out)
}

const unescapeVcf = (s: string) => s.replace(/\\([,;\\])/g, '$1').replace(/\\n/gi, ' ')

function dedupe(list: Contact[]): Contact[] {
  const seen = new Set<string>()
  const out: Contact[] = []
  for (const c of list) {
    const key = [...c.emails, ...c.phones.map((p) => p.replace(/\D/g, '').slice(-10))].sort().join('|')
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push({ ...c, emails: [...new Set(c.emails)].slice(0, 5), phones: [...new Set(c.phones)].slice(0, 5) })
  }
  return out
}

/** The phone's own contact picker (Chrome on Android). Null where it doesn't exist (iPhone). */
type PickerContact = { name?: string[]; email?: string[]; tel?: string[] }
type ContactsManager = { select: (props: string[], opts: { multiple: boolean }) => Promise<PickerContact[]> }
export const canPickContacts = () =>
  typeof navigator !== 'undefined' && 'contacts' in navigator && typeof (navigator as unknown as { contacts?: ContactsManager }).contacts?.select === 'function'

export async function pickContacts(): Promise<Contact[] | null> {
  const mgr = (navigator as unknown as { contacts?: ContactsManager }).contacts
  if (!mgr) return null
  try {
    const picked = await mgr.select(['name', 'email', 'tel'], { multiple: true })
    return dedupe(picked.map((p) => ({ name: (p.name ?? [])[0] ?? '', emails: (p.email ?? []).map((e) => e.toLowerCase()), phones: p.tel ?? [] })))
  } catch { return null }  // cancelled
}

/** Contacts are sent in chunks the server accepts (500 emails and numbers per request). */
export function chunks(list: Contact[]): Contact[][] {
  const out: Contact[][] = []
  let cur: Contact[] = []
  let n = 0
  for (const c of list) {
    const k = c.emails.length + c.phones.length
    if (n + k > MATCH_MAX && cur.length) { out.push(cur); cur = []; n = 0 }
    cur.push(c); n += k
  }
  if (cur.length) out.push(cur)
  return out
}

export const whoseCode = (code: string) =>
  getJSON<{ user: FindUser; status: FindStatus | 'self'; follows_you: boolean }>(`${P}/code/${encodeURIComponent(code)}`)
