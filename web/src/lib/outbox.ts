// Saves that survive a bad connection.
//
// `save()` sends one request with an Idempotency-Key. When it fails in a way that might work
// later (offline, timeout, 5xx, 408/429, or the session ran out), the request goes into a tiny
// per-user outbox in localStorage and is retried with backoff: when the browser says it's back
// online, when the app becomes visible, and on a timer (2 s doubling to 5 min). The same key is
// sent every time, so the server (webapp._api, idempotency.py) answers a retry with the first
// result instead of doing it twice. Requests with the same `coalesce` key replace each other
// (PUT/PATCH object bodies are merged), so ten toggles while offline become one save.
// Other 4xx answers are final: the item is dropped and the error is reported.
// Only use it for saves that are safe to repeat (settings, profile fields, check-ins, ...).
import { AuthError } from '@/lib/api'
import { draftUser } from '@/lib/drafts'

export type Method = 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type OutboxItem = {
  id: string; method: Method; path: string; body: unknown; label: string
  coalesce?: string; at: number; tries: number
}
export type SaveResult<T> = { ok: true; data: T } | { ok: false; queued: true; id: string }
export type OutboxEvent =
  | { type: 'saved'; item: OutboxItem; data: unknown }
  | { type: 'failed'; item: OutboxItem; message: string }
  | { type: 'change'; pending: number }

const TIMEOUT_MS = 15_000
const MAX_ITEMS = 50
const MAX_BACKOFF_MS = 5 * 60_000

export function newRequestId(): string {
  try { return crypto.randomUUID().replace(/-/g, '') } catch {
    return Array.from({ length: 4 }, () => Math.random().toString(36).slice(2, 10)).join('')
  }
}

const storeKey = () => `rabbit.outbox.${draftUser() || 'anon'}`

function load(): OutboxItem[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(storeKey()) ?? '[]') as unknown
    return Array.isArray(v) ? (v as OutboxItem[]).filter((i) => i && typeof i.path === 'string') : []
  } catch { return [] }
}

function store(items: OutboxItem[]): void {
  try { window.localStorage.setItem(storeKey(), JSON.stringify(items.slice(-MAX_ITEMS))) } catch { /* ignore */ }
  emit({ type: 'change', pending: items.length })
}

const listeners = new Set<(e: OutboxEvent) => void>()
function emit(e: OutboxEvent): void {
  for (const fn of Array.from(listeners)) { try { fn(e) } catch { /* ignore */ } }
}
export function onOutbox(fn: (e: OutboxEvent) => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}
export const pendingCount = () => load().length

class Retryable extends Error {}

/** True for failures worth retrying later. */
export function retryableStatus(status: number): boolean {
  return status >= 500 || status === 408 || status === 429
}

async function sendOnce(item: OutboxItem): Promise<unknown> {
  const ctl = new AbortController()
  const timer = window.setTimeout(() => ctl.abort(), TIMEOUT_MS)
  let r: Response
  try {
    r = await fetch(`/app${item.path}`, {
      method: item.method, credentials: 'same-origin', signal: ctl.signal,
      headers: { 'content-type': 'application/json', 'idempotency-key': item.id },
      body: item.body === undefined ? '{}' : JSON.stringify(item.body),
    })
  } catch {
    throw new Retryable('offline') // network error or timeout
  } finally { window.clearTimeout(timer) }
  if (r.status === 401) throw new AuthError('not signed in')
  const data = await r.json().catch(() => ({})) as { error?: string; code?: string }
  if (r.status === 409 && data.code === 'in_flight') throw new Retryable('in flight')
  if (retryableStatus(r.status)) throw new Retryable(`HTTP ${r.status}`)
  if (!r.ok) throw Object.assign(new Error(data.error ?? `HTTP ${r.status}`), { status: r.status, code: data.code })
  return data
}

function enqueue(item: OutboxItem): void {
  let items = load()
  if (item.coalesce) {
    const prev = items.find((i) => i.coalesce === item.coalesce)
    if (prev && (item.method === 'PUT' || item.method === 'PATCH')
        && prev.body && item.body && typeof prev.body === 'object' && typeof item.body === 'object') {
      item = { ...item, body: { ...(prev.body as object), ...(item.body as object) } }
    }
    items = items.filter((i) => i.coalesce !== item.coalesce)
  }
  store([...items.filter((i) => i.id !== item.id), item])
  schedule(0)
}

/** Send now; on a retryable failure keep it in the outbox and resolve `{queued: true}`.
 *  Throws on final errors (validation 4xx). AuthError also queues (it goes once signed in). */
export async function save<T>(req: { method: Method; path: string; body?: unknown; label: string; coalesce?: string; id?: string }): Promise<SaveResult<T>> {
  const item: OutboxItem = { id: req.id ?? newRequestId(), method: req.method, path: req.path, body: req.body ?? {},
    label: req.label, coalesce: req.coalesce, at: Date.now(), tries: 0 }
  // Something older for the same thing is still waiting: keep the order, queue behind it.
  if (item.coalesce && load().some((i) => i.coalesce === item.coalesce)) {
    enqueue(item)
    return { ok: false, queued: true, id: item.id }
  }
  try {
    return { ok: true, data: await sendOnce(item) as T }
  } catch (e) {
    if (e instanceof Retryable || e instanceof AuthError) {
      enqueue(item)
      if (e instanceof AuthError) notifyAuthLost()
      return { ok: false, queued: true, id: item.id }
    }
    throw e
  }
}

let timer: number | null = null
let running = false
let authWait = false

function schedule(delay: number): void {
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => { timer = null; void flush() }, delay)
}

/** Try everything in the outbox, oldest first. */
export async function flush(): Promise<void> {
  if (running || authWait) return
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return
  running = true
  try {
    for (;;) {
      const items = load()
      const item = items[0]
      if (!item) return
      try {
        const data = await sendOnce(item)
        store(load().filter((i) => i.id !== item.id))
        emit({ type: 'saved', item, data })
      } catch (e) {
        if (e instanceof AuthError) { authWait = true; notifyAuthLost(); return }
        if (e instanceof Retryable) {
          const tries = item.tries + 1
          store(load().map((i) => i.id === item.id ? { ...i, tries } : i))
          schedule(Math.min(2000 * 2 ** (tries - 1), MAX_BACKOFF_MS))
          return
        }
        store(load().filter((i) => i.id !== item.id))
        emit({ type: 'failed', item, message: (e as Error).message })
      }
    }
  } finally { running = false }
}

function notifyAuthLost(): void {
  try { window.dispatchEvent(new Event('rabbit:auth-lost')) } catch { /* ignore */ }
}

let started = false
/** Once per app load, after setDraftUser(). Also call after signing in again. */
export function startOutbox(): void {
  authWait = false
  if (!started) {
    started = true
    window.addEventListener('online', () => schedule(0))
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') schedule(0) })
  }
  emit({ type: 'change', pending: load().length })
  schedule(500)
}

/** Like `save`, but the promise settles when the request finally goes through: right away, or
 *  later from the outbox (`onQueued` runs when it had to wait; show "Not saved yet — we'll
 *  retry" then). Rejects on a final error. Fits the usual `await create(...)` form code. */
export function saveDurably<T>(req: { method: Method; path: string; body?: unknown; label: string; coalesce?: string; id?: string },
  onQueued?: () => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    save<T>(req).then((r) => {
      if (r.ok) { resolve(r.data); return }
      onQueued?.()
      const off = onOutbox((e) => {
        if (e.type === 'change' || e.item.id !== r.id) return
        off()
        if (e.type === 'saved') resolve(e.data as T)
        else reject(new Error(e.message))
      })
    }, reject)
  })
}
