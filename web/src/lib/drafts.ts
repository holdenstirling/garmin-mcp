// Never lose what someone typed: form drafts in localStorage, per signed-in user, 14 days.
//
//   const [v, setV, draft] = useDraft(`event.${id ?? 'new'}`, initial, { label: 'your event' })
//   ... on a successful save: draft.clear()      ... "Discard": draft.discard()
//
// * Nothing is stored until the person changes something, and a value equal to the initial
//   one (or `isEmpty`) removes the draft, so merely opening a form never saves a "draft".
// * Keys are prefixed with the user id (setDraftUser, from /me), so on a shared device one
//   person's half-written post never shows up for another.
// * Every storage access is wrapped: private mode / blocked storage just means no drafts.
// * Photos and files can't be kept (localStorage holds text); forms say so where it matters.
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

const PREFIX = 'rabbit.draft.'
export const DRAFT_TTL_MS = 14 * 86_400_000
const LAST = 'rabbit.draft-last'

let uid = ''

/** Called once /me is known. Also drops drafts older than 14 days. */
export function setDraftUser(id: string): void {
  uid = id
  pruneDrafts()
}

export function draftUser(): string { return uid }

const full = (key: string) => `${PREFIX}${uid || 'anon'}.${key}`

type Stored<T> = { v: T; at: number; label?: string }

function storage(): Storage | null {
  try { return window.localStorage } catch { return null }
}

export function readDraft<T>(key: string, now = Date.now()): T | null {
  try {
    const raw = storage()?.getItem(full(key))
    if (!raw) return null
    const s = JSON.parse(raw) as Stored<T>
    if (!s || typeof s.at !== 'number' || now - s.at > DRAFT_TTL_MS) {
      storage()?.removeItem(full(key))
      return null
    }
    return s.v
  } catch { return null }
}

export function writeDraft<T>(key: string, v: T, label?: string): void {
  try {
    const at = Date.now()
    storage()?.setItem(full(key), JSON.stringify({ v, at, label } satisfies Stored<T>))
    if (label) storage()?.setItem(LAST, JSON.stringify({ uid, key, label, at }))
  } catch { /* full or blocked: the form still works, just without a draft */ }
}

export function clearDraft(key: string): void {
  try { storage()?.removeItem(full(key)) } catch { /* ignore */ }
}

export function pruneDrafts(now = Date.now()): void {
  const s = storage()
  if (!s) return
  try {
    const keys: string[] = []
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i)
      if (k?.startsWith(PREFIX)) keys.push(k)
    }
    for (const k of keys) {
      try {
        const v = JSON.parse(s.getItem(k) ?? 'null') as Stored<unknown> | null
        if (!v || typeof v.at !== 'number' || now - v.at > DRAFT_TTL_MS) s.removeItem(k)
      } catch { s.removeItem(k) }
    }
  } catch { /* ignore */ }
}

/** The newest labelled draft this user still has (for "pick up where you left off"). */
export function lastDraft(maxAgeMs = DRAFT_TTL_MS): { key: string; label: string; at: number } | null {
  try {
    const l = JSON.parse(storage()?.getItem(LAST) ?? 'null') as { uid: string; key: string; label: string; at: number } | null
    if (!l || l.uid !== uid || Date.now() - l.at > maxAgeMs) return null
    return readDraft(l.key) == null ? null : { key: l.key, label: l.label, at: l.at }
  } catch { return null }
}

const same = (a: unknown, b: unknown) => {
  try { return JSON.stringify(a) === JSON.stringify(b) } catch { return false }
}

export type DraftCtl = {
  /** the form opened with a saved draft */
  restored: boolean
  /** differs from what the form started with (unsaved edits) */
  dirty: boolean
  /** after a successful save: forget the draft, keep what's on screen */
  clear: () => void
  /** "Discard": forget the draft and go back to the initial value */
  discard: () => void
}

/** useState that keeps a draft of the value. `key` null = plain state (no draft). */
export function useDraft<T>(key: string | null, initial: T | (() => T),
  opts: { label?: string; isEmpty?: (v: T) => boolean } = {}): [T, Dispatch<SetStateAction<T>>, DraftCtl] {
  const base = useRef<T | null>(null)
  if (base.current === null) base.current = typeof initial === 'function' ? (initial as () => T)() : initial
  const [restored, setRestored] = useState(false)
  const [value, setValueState] = useState<T>(() => {
    const saved = key ? readDraft<T>(key) : null
    return saved ?? base.current as T
  })
  // Set after the first render so `restored` is accurate without a flash.
  useEffect(() => {
    if (key && readDraft<T>(key) != null) setRestored(true)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const touched = useRef(false)
  const rebase = useRef(false)
  if (rebase.current) { rebase.current = false; base.current = value }
  const opt = useRef(opts)
  opt.current = opts
  const pending = useRef<number | null>(null)
  const latest = useRef(value)
  latest.current = value

  const persist = useCallback(() => {
    pending.current = null
    if (!key || !touched.current) return
    const v = latest.current
    const empty = opt.current.isEmpty ? opt.current.isEmpty(v) : same(v, base.current)
    if (empty) clearDraft(key)
    else writeDraft(key, v, opt.current.label)
  }, [key])

  useEffect(() => {
    if (!key || !touched.current) return
    if (pending.current !== null) window.clearTimeout(pending.current)
    pending.current = window.setTimeout(persist, 250)
  }, [value, key, persist])

  // Leaving (unmount, tab hidden, page closing): write what's pending right away.
  useEffect(() => {
    const flush = () => { if (pending.current !== null) { window.clearTimeout(pending.current); persist() } }
    const onHide = () => { if (document.visibilityState === 'hidden') flush() }
    window.addEventListener('pagehide', flush)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      window.removeEventListener('pagehide', flush)
      document.removeEventListener('visibilitychange', onHide)
      flush()
    }
  }, [persist])

  const setValue: Dispatch<SetStateAction<T>> = useCallback((v) => {
    touched.current = true
    setValueState(v)
  }, [])

  const clear = useCallback(() => {
    if (pending.current !== null) { window.clearTimeout(pending.current); pending.current = null }
    touched.current = false
    rebase.current = true // what's on screen after this update becomes the new "saved" value
    if (key) clearDraft(key)
    setRestored(false)
  }, [key])

  const discard = useCallback(() => {
    if (pending.current !== null) { window.clearTimeout(pending.current); pending.current = null }
    touched.current = false
    if (key) clearDraft(key)
    setRestored(false)
    setValueState(base.current as T)
  }, [key])

  return [value, setValue, { restored, dirty: !same(value, base.current), clear, discard }]
}
