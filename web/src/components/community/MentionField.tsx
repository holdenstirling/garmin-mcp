// @mention typing for a text box (feed comments, the post composer, editing a post). Typing "@"
// and a few letters opens a short list right above the box (so the phone keyboard never covers
// it): people you follow or who follow you, the post's author and commenters, the club or group
// it's in. Pick one with a tap, or arrows + Enter/Tab; Escape closes. The box shows "@Name";
// `encode()` turns it into the stored token on send. Someone the post won't reach is shown
// greyed with "can't see this post" and can't be picked.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react'
import { Avatar } from '@/components/Avatar'
import { encodeMentions, getMentionable, matchPeople, type Mention, type Mentionable } from '@/lib/mentions'
import { communityPhotoUrl } from '@/lib/community'
import { cn } from '@/lib/utils'

type Field = HTMLInputElement | HTMLTextAreaElement
// "@" at the start or after a space/newline/bracket, then up to two words being typed.
const TRIGGER = /(?:^|[\s(])@([^\s@]{0,30}(?: [^\s@]{0,30})?)$/u

export function useMentionField<T extends Field>({ value, setValue, where, initial = [] }: {
  value: string; setValue: (v: string) => void
  /** the post being commented on, or the audience of a new post */
  where: { pid?: string; audience?: string }
  /** people already mentioned (editing a saved post) */
  initial?: Mention[]
}): {
  ref: RefObject<T | null>
  onKeyDown: (e: KeyboardEvent<T>) => boolean
  onSelect: () => void
  list: ReactNode
  /** the text to send, with mention tokens */
  encode: (text?: string) => string
  reset: () => void
  /** true while the suggestion list is open (an Enter picks, it doesn't send) */
  open: boolean
} {
  const ref = useRef<T>(null)
  const [picked, setPicked] = useState<Mention[]>(initial)
  const [q, setQ] = useState<string | null>(null)
  const [people, setPeople] = useState<Mentionable[] | null>(null)
  const [active, setActive] = useState(0)
  const [note, setNote] = useState<string | null>(null)
  const key = where.pid ? `p:${where.pid}` : `a:${where.audience ?? 'friends'}`

  useEffect(() => { setPeople(null) }, [key])
  // Load who can be mentioned the first time "@" is typed.
  useEffect(() => {
    if (q === null || people) return
    let live = true
    getMentionable(where).then((p) => { if (live) setPeople(p) }, () => { if (live) setPeople([]) })
    return () => { live = false }
  }, [q, people, key]) // eslint-disable-line react-hooks/exhaustive-deps

  function check() {
    const el = ref.current
    if (!el) return
    const caret = el.selectionStart ?? value.length
    const m = TRIGGER.exec(value.slice(0, caret))
    setQ(m ? m[1] : null)
    setActive(0)
    if (!m) setNote(null)
  }
  // Re-check after every change (typing, paste, the caret moving with the text).
  useEffect(() => { check() }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  const matches = q === null || !people ? [] : matchPeople(people, q)

  function pick(p: Mentionable) {
    if (!p.can_see) { setNote(`${p.name.split(' ')[0]} can't see this post.`); return }
    const el = ref.current
    const caret = el?.selectionStart ?? value.length
    const before = value.slice(0, caret)
    const m = TRIGGER.exec(before)
    if (!m) return
    const start = caret - m[1].length - 1
    const name = p.name.replace(/[[\]()\n]/g, '').trim()
    const insert = `@${name} `
    const next = value.slice(0, start) + insert + value.slice(caret)
    setValue(next)
    setPicked((x) => (x.some((y) => y.id === p.id) ? x : [...x, { id: p.id, name }]))
    setQ(null); setNote(null)
    window.requestAnimationFrame(() => {
      const f = ref.current
      if (!f) return
      f.focus()
      const at = start + insert.length
      f.setSelectionRange(at, at)
    })
  }

  function onKeyDown(e: KeyboardEvent<T>): boolean {
    if (q === null || !matches.length) return false
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => (i + 1) % matches.length); return true }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (i - 1 + matches.length) % matches.length); return true }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(matches[Math.min(active, matches.length - 1)]); return true }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setQ(null); return true }
    return false
  }

  const open = q !== null && (matches.length > 0 || !!note || (people !== null && q.length > 0))
  const list = q === null ? null : (
    <div className="absolute inset-x-0 bottom-full z-20 mb-1.5 overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface) shadow-lg"
      role="listbox" aria-label="Mention someone">
      {people === null ? (
        <p className="px-3 py-2.5 text-[0.7059rem] text-(--text-muted)">Finding people…</p>
      ) : matches.length === 0 ? (
        q.length > 0 ? <p className="px-3 py-2.5 text-[0.7059rem] text-(--text-muted)">No one called “{q}” you can mention here.</p> : null
      ) : matches.map((p, i) => (
        <button key={p.id} type="button" role="option" aria-selected={i === active} aria-disabled={!p.can_see}
          onMouseDown={(e) => e.preventDefault()} onClick={() => pick(p)}
          className={cn('flex min-h-11 w-full items-center gap-2.5 px-3 py-1.5 text-left',
            i === active && 'bg-(--bg-inset)', !p.can_see && 'opacity-50')}>
          <Avatar name={p.name} picture={p.picture ?? ''} photo={communityPhotoUrl(p)} size={28} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{p.name}</span>
            {(!p.can_see || p.handle) && (
              <span className="block truncate text-[0.6471rem] text-(--text-muted)">{!p.can_see ? "Can't see this post" : `@${p.handle}`}</span>
            )}
          </span>
        </button>
      ))}
      {note && <p className="border-t border-(--border) px-3 py-2 text-[0.7059rem] text-(--warning-text,var(--danger))" role="alert">{note}</p>}
    </div>
  )

  return {
    ref, onKeyDown, onSelect: check, list, open,
    encode: (text = value) => encodeMentions(text, picked),
    reset: () => { setPicked([]); setQ(null); setNote(null) },
  }
}
