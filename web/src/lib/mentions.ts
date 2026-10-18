// @mentions (server: mentions.py + community.py). Stored text carries ``@[Name](uid)`` per
// mention; only the uids in the item's ``mentions`` list are links (anything else shows as plain
// "@Name"). While typing, the field shows plain "@Name" and keeps the picked people beside it;
// ``encodeMentions`` turns each picked "@Name" still in the text into its token on send.
import { getJSON } from '@/lib/api'
import type { SocialUser } from '@/lib/social'

export type Mention = { id: string; name: string }
export type Mentionable = SocialUser & { can_see: boolean; handle?: string | null }

const TOKEN = /@\[([^[\]\n]{1,60})\]\(([^\s()[\]]{1,120})\)/g

export type Segment = { text: string } | { mention: Mention; label: string }

/** Text split into plain runs and mentions (links only for ``allowed`` ids, current names). */
export function segments(text: string, allowed: Mention[] | undefined): Segment[] {
  const ok = new Map((allowed ?? []).map((m) => [m.id, m]))
  const out: Segment[] = []
  let last = 0
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0
    if (at > last) out.push({ text: text.slice(last, at) })
    const who = ok.get(m[2])
    out.push(who ? { mention: who, label: `@${who.name}` } : { text: `@${m[1].trim()}` })
    last = at + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

/** Tokens as people read them: "@Name". */
export const displayText = (text: string) => text.replace(TOKEN, (_, name: string) => `@${name.trim()}`)

/** The people mentioned by tokens in ``text`` (for editing a saved post). */
export function tokensIn(text: string): Mention[] {
  const seen = new Map<string, Mention>()
  for (const m of text.matchAll(TOKEN)) if (!seen.has(m[2])) seen.set(m[2], { id: m[2], name: m[1].trim() })
  return [...seen.values()]
}

const clean = (s: string) => s.replace(/[[\]()\n]/g, '').trim().slice(0, 60)

/** Plain field text + picked people -> text with tokens (each "@Name" still there, all of them). */
export function encodeMentions(text: string, picked: Mention[]): string {
  let out = text
  for (const p of [...picked].sort((a, b) => b.name.length - a.name.length)) {
    const name = clean(p.name)
    if (!name) continue
    const at = `@${name}`
    const re = new RegExp(`${at.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\p{L}\\p{N}_])`, 'gu')
    out = out.replace(re, (m, offset: number, whole: string) => (whole[offset - 1] === '[' ? m : `@[${name}](${p.id})`))
  }
  return out
}

/** Accent- and case-insensitive. */
export const fold = (s: string) => s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()

/** People whose name (any word) or handle starts with ``q``; the post's own people first. */
export function matchPeople(all: Mentionable[], q: string, limit = 6): Mentionable[] {
  const f = fold(q.trim())
  if (!f) return all.slice(0, limit)
  const hit = (p: Mentionable) => {
    const name = fold(p.name)
    if (name.startsWith(f) || name.split(/\s+/).some((w) => w.startsWith(f))) return true
    return !!p.handle && fold(p.handle).startsWith(f.replace(/^@/, ''))
  }
  return all.filter(hit).slice(0, limit)
}

const cache = new Map<string, Promise<Mentionable[]>>()
/** Who can be mentioned on a post (``pid``) or in a new post to ``audience``. Cached a minute. */
export function getMentionable(where: { pid?: string; audience?: string }): Promise<Mentionable[]> {
  const key = where.pid ? `p:${where.pid}` : `a:${where.audience ?? 'friends'}`
  let p = cache.get(key)
  if (!p) {
    const qs = where.pid ? `pid=${encodeURIComponent(where.pid)}` : `audience=${encodeURIComponent(where.audience ?? 'friends')}`
    p = getJSON<{ people: Mentionable[] }>(`/api/community/mentionable?${qs}`).then((r) => r.people)
    p.catch(() => cache.delete(key))
    cache.set(key, p)
    window.setTimeout(() => cache.delete(key), 60_000)
  }
  return p
}
