/**
 * useCoach: chat state for Rabbit's single ongoing thread.
 *
 * A slimmed-down port of Dolly's useAgent: keeps the processStream switch
 * (text deltas append to the open agent message; a tool call closes it so
 * cards land in order) and history loading. A running reply is tied to the thread it
 * was sent in, so switching threads mid-reply doesn't leak it into another thread. Turns run server-side, so when a
 * phone drops the stream we re-attach from the last event index.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getJSON } from '@/lib/api'
import { attachTurn, sendChat, type ApprovalSummary, type StreamEvent } from '@/lib/agent-stream'
import type { AttachmentMeta } from '@/lib/attachments'
import type { ChartSpec } from '@/components/chat/Chart'

export type ChatMessage = {
  kind: 'message'; id: string; role: 'user' | 'agent'; text: string; error?: boolean
  /** coach-log metadata: which stored turn this came from, and what kind */
  turnId?: string; ts?: number; label?: 'brief' | 'workout' | 'note' | null; turnKind?: string
  attachments?: AttachmentMeta[]
}
export type ThreadLink = { kind: 'link'; id: string; threadId: string; fromTurn: string | null; ts: number }
export type ToolCall = {
  kind: 'tool'; id: string; toolName: string; params: Record<string, unknown>
  status: 'executing' | 'done' | 'error'; result?: unknown; error?: string
}
export type Approval = {
  kind: 'approval'; id: string; turnId: string | null; summary: ApprovalSummary
  status: 'pending' | 'approved' | 'declined'; reason?: string | null
}
export type ChartItem = { kind: 'chart'; id: string; spec: ChartSpec }
/** Rabbit moments (moments.py): a short deterministic update with action chips. */
export type MomentActionId = 'checkin' | 'reaction' | 'readiness' | 'racepack' | 'plan' | 'progress' | 'ask' | 'race_invite'
  | 'community_share' | 'community_later' | 'community' | 'month_recap' | 'raceweek' | 'block' | 'block_checkin' | 'plan_fix'
  | 'pace' | 'pace_accept' | 'pace_later' | 'sick'
export type MomentAction = { id: MomentActionId; label: string; activity_id?: number; event_id?: string; prompt?: string; title?: string; draft_id?: string; post_id?: string; club_id?: string; view?: 'people'; month?: string; section?: string; block_id?: string; feel?: string; session_id?: string; sport?: string; sid?: string }
export type MomentItem = { kind: 'moment'; id: string; ts: number; moment: string; text: string; actions: MomentAction[] }
export type ChatItem = ChatMessage | ToolCall | ThreadLink | Approval | ChartItem | MomentItem
/** 'busy': idle here, but a reply is still running in another thread. */
export type Status = 'loading' | 'idle' | 'streaming' | 'busy'

type Part =
  | { type: 'text'; text: string }
  | { type: 'thread_link'; thread_id: string; from_turn: string | null }
  | { type: 'chart'; spec: ChartSpec }
  | { type: 'moment'; moment: string; text: string; actions?: MomentAction[] }
  | { type: 'tool_call'; toolCallId: string; toolName: string; params: Record<string, unknown>; result?: unknown; error?: string
      approval?: { summary: ApprovalSummary; approved: boolean; reason: string | null } }
type StoredTurn = {
  id: string; ts: number; kind: 'chat' | 'proactive' | 'seed' | 'link' | 'moment'
  label?: 'brief' | 'workout' | null; user: string | null; parts: Part[]
  attachments?: AttachmentMeta[]
}

let seq = 0
const uid = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`

function turnsToItems(turns: StoredTurn[]): ChatItem[] {
  const items: ChatItem[] = []
  for (const t of turns) {
    if (t.user) {
      const text = t.attachments?.length && t.user === '(see attached)' ? '' : t.user
      items.push({ kind: 'message', id: `${t.id}-u`, role: 'user', text, ts: t.ts, attachments: t.attachments })
    }
    let first = true
    t.parts.forEach((p, i) => {
      if (p.type === 'moment') {
        items.push({ kind: 'moment', id: `${t.id}-${i}`, ts: t.ts, moment: p.moment, text: p.text, actions: p.actions ?? [] })
      } else if (p.type === 'chart') {
        items.push({ kind: 'chart', id: `${t.id}-${i}`, spec: p.spec })
      } else if (p.type === 'thread_link') {
        items.push({ kind: 'link', id: `${t.id}-${i}`, threadId: p.thread_id, fromTurn: p.from_turn, ts: t.ts })
      } else if (p.type === 'text') {
        items.push({ kind: 'message', id: `${t.id}-${i}`, role: 'agent', text: p.text, ts: t.ts,
          turnId: t.id, turnKind: t.kind, label: first ? (t.label ?? (t.kind === 'proactive' ? 'note' : null)) : null })
        first = false
      } else {
        if (p.approval) {
          items.push({ kind: 'approval', id: `ap-${p.toolCallId}`, turnId: t.id, summary: p.approval.summary,
            status: p.approval.approved ? 'approved' : 'declined', reason: p.approval.reason })
        }
        items.push({
          kind: 'tool', id: p.toolCallId, toolName: p.toolName, params: p.params ?? {},
          status: p.error ? 'error' : 'done', result: p.result, error: p.error,
        })
      }
    })
  }
  return items
}

export type QueuedSend = { threadId: string; text: string; attachments: AttachmentMeta[] }


/** One running reply. The server runs one turn per user at a time, so there is at most one;
 *  it belongs to the thread it was sent in, whichever thread is on screen. */
type Stream = {
  threadId: string
  turn: { id: string; seen: number } | null
  /** the reply so far (the user's message, text, tool cards), shown under that thread's history */
  items: ChatItem[]
  openMsg: string | null
  /** a request is reading the stream right now (otherwise it dropped and can be re-attached) */
  consuming: boolean
  /** the finished turn is already in the loaded history: don't show ``items`` twice */
  inHistory: boolean
}

/** Fold one stream event into the reply's items (text deltas append to the open agent
 *  message; a tool call closes it so cards land in order). */
function applyEvent(s: Stream, items: ChatItem[], e: StreamEvent): ChatItem[] {
  switch (e.type) {
    case 'text-delta': {
      const id = s.openMsg
      if (id) {
        return items.map((it) => (it.id === id && it.kind === 'message' ? { ...it, text: it.text + e.text } : it))
      }
      const nid = uid('a')
      s.openMsg = nid
      return [...items, { kind: 'message', id: nid, role: 'agent', text: e.text }]
    }
    case 'tool-call-start':
      s.openMsg = null
      return [...items, { kind: 'tool', id: e.toolCallId, toolName: e.toolName, params: e.params ?? {}, status: 'executing' }]
    case 'tool-call-result':
      return items.map((it) => (it.id === e.toolCallId && it.kind === 'tool' ? { ...it, status: 'done', result: e.result } : it))
    case 'tool-call-error':
      return items.map((it) => (it.id === e.toolCallId && it.kind === 'tool' ? { ...it, status: 'error', error: e.error } : it))
    case 'chart':
      s.openMsg = null
      // The chart replaces the tool card that announced it.
      return [...items.filter((it) => it.id !== e.toolCallId), { kind: 'chart', id: `c-${e.toolCallId}`, spec: e.spec }]
    case 'approval-request':
      s.openMsg = null
      return [...items, { kind: 'approval', id: `ap-${e.approvalCallId}`, turnId: s.turn?.id ?? null,
        summary: e.summary, status: 'pending' }]
    case 'approval-result':
      return items.map((it) => (it.id === `ap-${e.approvalCallId}` && it.kind === 'approval'
        ? { ...it, status: e.approved ? 'approved' : 'declined', reason: e.reason } : it))
    case 'result':
      s.openMsg = null
      if (e.response.status === 'error' && !e.response.disconnected) {
        return [...items, { kind: 'message', id: uid('e'), role: 'agent', text: e.response.status === 'error' ? e.response.error : '', error: true }]
      }
      return items
    default:
      return items
  }
}

/** ``active``: the reply that was still running when the app opened (from /api/me).
 *  ``queued``: a message to send as soon as ``queued.threadId`` is open (used when a
 *  message typed in the coach log becomes a new thread). */
export function useCoach(threadId: string | null, active: { turn: string | null; thread: string | null },
  queued?: QueuedSend | null, onQueuedSent?: () => void) {
  const queuedRef = useRef(queued)
  queuedRef.current = queued
  // The thread on screen; stream events for any other thread stay off screen.
  const viewRef = useRef(threadId)
  viewRef.current = threadId
  const initialActive = useRef(active)

  const [history, setHistory] = useState<ChatItem[]>([])
  const [live, setLive] = useState<ChatItem[]>([])
  const items = useMemo(() => (live.length ? [...history, ...live] : history), [history, live])
  const [loading, setLoading] = useState(true)
  // Which thread ``history`` belongs to: right after a switch it's still the old thread's.
  const [loadedId, setLoadedId] = useState<string | null>(null)
  const loadedRef = useRef<string | null>(null)
  const [errorFor, setErrorFor] = useState<string | null>(null)
  const [streamThread, setStreamThread] = useState<string | null>(null)
  const streamRef = useRef<Stream | null>(null)

  /** What to show under ``tid``'s history: the running reply, if it's that thread's. */
  const liveFor = (tid: string | null): ChatItem[] => {
    const s = streamRef.current
    return s && tid && s.threadId === tid && !s.inHistory ? s.items : []
  }

  // Only the newest history request may land (fast thread switches answer out of order).
  const histReq = useRef(0)
  const histInFlight = useRef<string | null>(null)
  const loadHistory = useCallback(async (): Promise<boolean> => {
    if (!threadId) return false
    const tid = threadId
    const req = ++histReq.current
    histInFlight.current = tid
    try {
      const page = await getJSON<{ turns: StoredTurn[] }>(`/api/threads/${tid}/messages?limit=60`)
      if (req !== histReq.current) return false
      const s = streamRef.current
      const runningId = s && s.threadId === tid ? s.turn?.id : undefined
      if (s && runningId && page.turns.some((t) => t.id === runningId)) s.inHistory = true
      setHistory(turnsToItems(page.turns))
      setLive(liveFor(tid))
      setErrorFor(null)
      loadedRef.current = tid
      setLoadedId(tid)
      return true
    } catch {
      if (req !== histReq.current) return false
      // A background refresh that fails keeps what's on screen; a first load shows the error.
      if (loadedRef.current !== tid) {
        setHistory([])
        setLive(liveFor(tid))
        setErrorFor(tid)
        loadedRef.current = tid
        setLoadedId(tid)
      }
      return false
    } finally {
      if (req === histReq.current) histInFlight.current = null
    }
  }, [threadId]) // eslint-disable-line react-hooks/exhaustive-deps
  const loadRef = useRef(loadHistory)
  loadRef.current = loadHistory

  const begin = useCallback((tid: string): Stream => {
    const s: Stream = { threadId: tid, turn: null, items: [], openMsg: null, consuming: false, inHistory: false }
    streamRef.current = s
    setStreamThread(tid)
    return s
  }, [])

  /** The reply finished: it's part of its thread's history now. */
  const end = useCallback((s: Stream) => {
    if (streamRef.current !== s) return
    streamRef.current = null
    setStreamThread(null)
    if (viewRef.current !== s.threadId) return // that thread reloads when it's opened again
    if (histInFlight.current === s.threadId) {
      // A history request already on its way may predate the saved turn: ask again.
      void loadRef.current()
      return
    }
    if (!s.inHistory) setHistory((h) => [...h, ...s.items])
    setLive([])
  }, [])

  /** Consume a stream; returns true if it ended because the connection dropped. */
  const consume = useCallback(async (s: Stream, stream: AsyncGenerator<StreamEvent | { type: 'turn-id'; turnId: string }>) => {
    for await (const e of stream) {
      if (e.type === 'turn-id') { s.turn = { id: e.turnId, seen: 0 }; continue }
      if (e.type === 'result' && e.response.status === 'error' && e.response.disconnected) return true
      if (s.turn) s.turn.seen += 1
      s.items = applyEvent(s, s.items, e)
      if (viewRef.current === s.threadId && !s.inHistory) setLive(s.items)
    }
    return false
  }, [])

  const reattach = useCallback(async (s: Stream) => {
    if (s.consuming || streamRef.current !== s) return
    const t = s.turn
    if (!t) { end(s); return }
    s.consuming = true
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        const dropped = await consume(s, attachTurn(t.id, t.seen))
        if (!dropped) break
        await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)))
      }
    } finally {
      s.consuming = false
      end(s)
    }
  }, [consume, end])

  // A reply was still running when the app was opened: follow it in its own thread.
  const resumed = useRef(false)
  useEffect(() => {
    const a = initialActive.current
    if (resumed.current || !a.turn || !a.thread) return
    resumed.current = true
    const s = begin(a.thread)
    s.turn = { id: a.turn, seen: 0 }
    if (viewRef.current === a.thread) setLive(s.items)
    void reattach(s)
  }, [begin, reattach])

  const send = useCallback(async (text: string, attachments: AttachmentMeta[] = []) => {
    const message = text.trim()
    if ((!message && !attachments.length) || streamRef.current || !threadId) return
    const s = begin(threadId)
    s.consuming = true
    s.items = [{ kind: 'message', id: uid('u'), role: 'user', text: message, attachments }]
    if (viewRef.current === threadId) setLive(s.items)
    let dropped = false
    try {
      dropped = await consume(s, sendChat(message, threadId, attachments.map((a) => a.id)))
    } finally {
      s.consuming = false
      if (!dropped) end(s)
      else if (document.visibilityState === 'visible') void reattach(s)
      // else: re-attached when the app comes back (below)
    }
  }, [begin, consume, end, reattach, threadId])

  useEffect(() => {
    if (!threadId) return
    setLoading(true)
    setLive(liveFor(threadId))
    void (async () => {
      await loadHistory()
      if (viewRef.current !== threadId) return // switched again meanwhile
      setLoading(false)
      const q = queuedRef.current
      if (q && q.threadId === threadId) {
        onQueuedSent?.()
        await send(q.text, q.attachments)
      }
    })()
  }, [threadId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Coming back to the app: pick up a reply that kept running in the background.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      const s = streamRef.current
      if (s && !s.consuming) void reattach(s)
      // pick up workout notes / briefs written while away
      if (!s || s.threadId !== viewRef.current) void loadHistory()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [reattach, loadHistory])

  const retry = useCallback(async () => {
    const tid = threadId
    setLoading(true)
    await loadHistory()
    if (viewRef.current === tid) setLoading(false)
  }, [loadHistory, threadId])

  const stop = useCallback(async () => {
    const t = streamRef.current?.turn
    if (!t) return
    await fetch(`/app/api/chat/${encodeURIComponent(t.id)}/cancel`, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'content-type': 'application/json' }, body: '{}',
    }).catch(() => {})
  }, [])

  const decide = useCallback(async (approvalId: string, approved: boolean, reason?: string) => {
    const t = streamRef.current?.turn
    if (!t) return
    const callId = approvalId.replace(/^ap-/, '')
    await fetch(`/app/api/chat/${encodeURIComponent(t.id)}/approval`, {
      method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ approval_id: callId, approved, reason: reason || null }),
    }).catch(() => {})
  }, [])

  // 'busy': a reply is running in another thread (the server takes one at a time).
  const status: Status = loading ? 'loading'
    : streamThread === null ? 'idle' : streamThread === threadId ? 'streaming' : 'busy'

  return {
    items, ready: loadedId === threadId, status, send, stop, decide, reload: loadHistory,
    loadError: errorFor !== null && errorFor === threadId, retry,
  }
}
