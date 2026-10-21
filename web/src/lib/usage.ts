// Privacy-first usage counts (server: usage.py, POST /app/api/usage). track() queues a tiny
// event {name, props, ts}; the queue goes up every 15 s, at 20 events, and with sendBeacon
// when the page is hidden. Only the names/props below exist (the server drops anything else):
// no free text, health data or location, ever.
//
// Nothing is sent when the browser asks not to be tracked (Do Not Track / Global Privacy
// Control) or the person turned on "Don't count my usage" (settings.usage_off, mirrored here
// per device by setUsageOff so it holds before /me loads). Failures are silent.
import { haptic } from '@/lib/haptics'
import { markJob } from '@/lib/newcomer'

export type UsageEvent =
  | ['app_open']
  | ['tab_view', { tab: 'rabbit' | 'plan' | 'feed' | 'clubs' | 'progress' | 'me' }]
  | ['card_tap', { card: CardId }]
  | ['setup_step', { step: 'intro' | 'race' | 'goal' | 'you' | 'numbers' | 'week' | 'review' }]
  | ['setup_complete']
  | ['invite_join']
  | ['share', { what: 'workout' | 'post' | 'month' | 'race' | 'plan' | 'invite' | 'profile' }]
  | ['cheer']
  | ['rsvp', { kind: 'meetup' | 'group' | 'race' }]
  | ['push_open', { kind: 'coach' | 'recap' | 'community' | 'workout' | 'brief' | 'other' }]
  | ['milestone', { what: Milestone }]

/** A person's firsts (server: traction.py counts each once per person). */
export type Milestone = 'area_set' | 'rsvp' | 'run_posted' | 'plan_built' | 'post' | 'follow' | 'watch_connected'

export const CARD_IDS = ['upnext', 'ring', 'race_grade', 'reward', 'actions'] as const
export type CardId = typeof CARD_IDS[number]

type Queued = { name: string; props?: Record<string, string>; ts: number }

const URL_ = '/app/api/usage'
const KEY = 'rabbit.usage_off'
const FLUSH_MS = 15_000
const MAX_QUEUE = 20
const MAX_HELD = 200 // never let an offline queue grow without bound

let queue: Queued[] = []
let timer: number | null = null
let wired = false
let offOverride: boolean | null = null

function dnt(): boolean {
  const n = navigator as Navigator & { globalPrivacyControl?: boolean; msDoNotTrack?: string }
  const w = window as Window & { doNotTrack?: string }
  return n.globalPrivacyControl === true || n.doNotTrack === '1' || w.doNotTrack === '1' || n.msDoNotTrack === '1'
}

export function usageOff(): boolean {
  if (offOverride !== null) return offOverride
  try { return window.localStorage.getItem(KEY) === '1' } catch { return false }
}

/** Mirror of settings.usage_off on this device (called when /me loads and on toggle). */
export function setUsageOff(off: boolean): void {
  offOverride = off
  try { if (off) window.localStorage.setItem(KEY, '1'); else window.localStorage.removeItem(KEY) } catch { /* this visit only */ }
  if (off) queue = []
}

export function counting(): boolean {
  return typeof window !== 'undefined' && !dnt() && !usageOff()
}

function send(events: Queued[], beacon: boolean): void {
  const body = JSON.stringify({ events })
  try {
    if (beacon && typeof navigator.sendBeacon === 'function'
      && navigator.sendBeacon(URL_, new Blob([body], { type: 'application/json' }))) return
  } catch { /* fall back to fetch */ }
  fetch(URL_, {
    method: 'POST', credentials: 'same-origin', keepalive: true,
    headers: { 'content-type': 'application/json' }, body,
  }).catch(() => {})
}

export function flushUsage(beacon = false): void {
  if (timer !== null) { window.clearTimeout(timer); timer = null }
  if (!queue.length) return
  const batch = queue.splice(0, 50)
  if (counting()) send(batch, beacon)
  if (queue.length) flushUsage(beacon)
}

function wire(): void {
  if (wired) return
  wired = true
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushUsage(true) })
  window.addEventListener('pagehide', () => flushUsage(true))
}

export function track(...[name, props]: UsageEvent): void {
  try {
    if (!counting()) return
    wire()
    queue.push(props ? { name, props: props as Record<string, string>, ts: Date.now() } : { name, ts: Date.now() })
    if (queue.length > MAX_HELD) queue = queue.slice(-MAX_HELD)
    if (queue.length >= MAX_QUEUE) flushUsage()
    else if (timer === null) timer = window.setTimeout(() => flushUsage(), FLUSH_MS)
  } catch { /* counting never breaks the app */ }
}

function pushKind(url: string): 'coach' | 'recap' | 'community' | 'workout' | 'brief' | 'other' {
  try {
    const o = new URL(url, window.location.origin).searchParams.get('open')
    return o === 'coach' || o === 'recap' || o === 'community' || o === 'workout' || o === 'brief' ? o : 'other'
  } catch { return 'other' }
}

/** Count `ev` and give a success haptic once `p` resolves (failures count nothing). */
export function counted<T>(p: Promise<T>, ...ev: UsageEvent): Promise<T> {
  return p.then((r) => { if (ev[0] === 'rsvp') markJob(); track(...ev); haptic(); return r })
}

// Read at load, before the app tidies the address bar (sw.js adds from=push to a notification's link).
const launchedFromPush: string | null = (() => {
  try {
    const u = new URL(window.location.href)
    if (u.searchParams.get('from') !== 'push') return null
    u.searchParams.delete('from')
    window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash)
    return u.href
  } catch { return null }
})()

/** Once per page load: app_open, plus push_open when a notification opened the app or
 * later brought it forward. */
let opened = false
export function trackAppOpen(): void {
  if (opened) return
  opened = true
  track('app_open')
  try {
    if (launchedFromPush) track('push_open', { kind: pushKind(launchedFromPush) })
    // Card taps: any click inside an element marked data-usage-card="upnext|ring|race_grade|
    // reward|actions" counts once (unknown values are dropped here and on the server).
    document.addEventListener('click', (e) => {
      const el = e.target instanceof Element ? e.target.closest<HTMLElement>('[data-usage-card]') : null
      const card = el?.dataset.usageCard
      if (card && (CARD_IDS as readonly string[]).includes(card)) track('card_tap', { card: card as CardId })
    }, { capture: true, passive: true })
    navigator.serviceWorker?.addEventListener('message', (e: MessageEvent) => {
      const d = e.data as { type?: string; url?: string; push?: boolean } | null
      if (d?.type === 'open' && d.push && typeof d.url === 'string') track('push_open', { kind: pushKind(d.url) })
    })
  } catch { /* counting never breaks the app */ }
}

export type UsageSummary = {
  today: string
  days: number
  now: { date: string; dau: number; wau: number; mau: number }
  series: { date: string; dau: number; wau: number; mau: number }[]
  retention: Record<'d1' | 'd7', { cohort: number; returned: number; pct: number | null }>
  funnel: { step: string; users: number; pct: number | null }[]
  cards: { id: string; taps: number; users: number }[]
  tabs: { id: string; taps: number; users: number }[]
  events: Record<string, number>
  new_users: number
}
