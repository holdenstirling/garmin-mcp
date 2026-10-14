import { useSheetDrag } from '@/hooks/useSheetDrag'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, MessageCircle, MessagesSquare, Sparkles, Upload, X } from 'lucide-react'
import { useEdgeSwipe } from '@/hooks/useEdgeSwipe'
import { Avatar } from '@/components/Avatar'
import { photoUrl } from '@/lib/photo'
import { MemorySheet } from '@/components/MemorySheet'
import { PlanSheet } from '@/components/PlanSheet'
import { planLine } from '@/components/chat/PlanPins'
import { PlanEditor } from '@/components/plan/PlanEditor'
import { AddPlanLauncher } from '@/components/plan/PlanImport'
import { SetupWizard } from '@/components/plan/SetupWizard'
import { ProfileScreen } from '@/components/plan/ProfileScreen'
import { Screen, TabScreen } from '@/components/plan/ui'
import { EventsScreen } from '@/components/events/EventsScreen'
import { RacePackScreen } from '@/components/events/RacePackScreen'
import { StatsScreen } from '@/components/stats/StatsScreen'
import { GearScreen } from '@/components/gear/GearScreen'
import { ExploreScreen } from '@/components/explore/ExploreScreen'
import { CommunityScreen, type CommunityView } from '@/components/community/CommunityScreen'
import { Celebration, SetupScreen } from '@/components/progress/Progress'
import { getProgress, nextQuest, type Progress, type QuestId } from '@/lib/progress'
import { CoachInbox } from '@/components/coach/CoachInbox'
import { CoachesScreen } from '@/components/coach/CoachesScreen'
import { CoachStatusSheet } from '@/components/coach/CoachStatusSheet'
import { FindCoachScreen } from '@/components/coach/FindCoachScreen'
import { CoachApp } from '@/components/coach/CoachApp'
import { athleteChat, getCoaches } from '@/lib/coach'
import { daysUntil } from '@/lib/events'
import { dismissDraft, shareDraft } from '@/lib/community'
import { TodayCard } from '@/components/today/TodayCard'
import { useTopInsight } from '@/lib/insights'
import { VoiceCheckIn } from '@/components/checkin/VoiceCheckIn'
import { RecapSheet } from '@/components/recap/RecapSheet'
import { getToday, localDay, shiftWeek, syncNow, type Today, type TodayActionKind } from '@/lib/live'
import { WorkoutDayScreen } from '@/components/workout/WorkoutDayScreen'
import { ReactionCard } from '@/components/workout/ReactionCard'
import { markReactionShown, reactionShown } from '@/lib/workout'
import { RabbitLogo } from '@/components/RabbitLogo'
import { RabbitLoader } from '@/components/RabbitLoader'
import { SettingsPanels } from '@/components/SettingsPanels'
import { DataSourcesSheet } from '@/components/settings/DataSourcesSheet'
import { setCurrentSources } from '@/lib/sources'
import { ThreadsSheet } from '@/components/ThreadsSheet'
import { Group, Icon, Row as SettingsRow } from '@/components/settings/Grouped'
import { WeekList } from '@/components/week/WeekStrip'
import { TabBar, readTab, saveTab, useSocialBadge, type TabId } from '@/components/nav/TabBar'
import { PullToRefresh, celebrate, signalReplyDone } from '@/components/fx'
import { Segmented } from '@/components/nav/Segmented'
import { MePage, type MeRow } from '@/components/nav/MePage'
import { StatusBanner, type Banner } from '@/components/nav/StatusBanner'
import { CoachHeader, DiscussButton, ThreadLinkCard } from '@/components/chat/CoachCards'
import { ATTACH_INPUT_ID, Composer } from '@/components/chat/Composer'
import type { AttachmentMeta } from '@/lib/attachments'
import { MessageBubble } from '@/components/chat/MessageBubble'
import { ToolCallCard, ToolCallGroup } from '@/components/chat/ToolCallCard'
import { Button } from '@/components/ui/button'
import {
  createThread, deleteThread, getPlanWeek, goalCountdown, listThreads, putSettings,
  type Goal, type Me, type PlannedSession, type PlanWeek, type Thread, type WeekDay,
} from '@/lib/api'
import { useCoach, type QueuedSend, type ChartItem, type Approval, type ChatItem, type ChatMessage, type MomentAction, type MomentItem, type ThreadLink, type ToolCall } from '@/hooks/useCoach'
import { MomentCard } from '@/components/chat/MomentCard'
import { ReplyChips, replyChips, useRotatingPrompt } from '@/components/chat/ReplyChips'
import { RaceFitScreen } from '@/components/events/RaceFitScreen'
import { ApprovalCard } from '@/components/chat/ApprovalCard'
import { Chart } from '@/components/chat/Chart'
import { MessageMenu, type MenuTarget } from '@/components/chat/MessageMenu'
import { ThreadPeek } from '@/components/chat/ThreadPeek'
import { EmptyHero } from '@/components/chat/EmptyHero'
import { useLongPress } from '@/hooks/useLongPress'
import { hapticTap } from '@/lib/haptics'
import { WelcomeGate } from '@/components/onboarding/WelcomeFlow'
import { IntentStrip, stripFirst } from '@/components/onboarding/IntentHome'
import { composerPrompts, intentSuggestions, intentsOf, wantsPlan } from '@/lib/intent'

const COACH_SUGGESTIONS = [
  'How did my training go this week?',
  'Am I recovered enough for a hard session today?',
  "How's my sleep been lately?",
]
const TOPIC_SUGGESTIONS = ['Help me plan next week.', 'Can I move my long ride to Sunday?', 'What should I eat before a long run?']

type Row =
  | { kind: 'message'; item: ChatMessage; showLabel: boolean }
  | { kind: 'tool'; item: ToolCall }
  | { kind: 'group'; items: ToolCall[] }
  | { kind: 'link'; item: ThreadLink }
  | { kind: 'approval'; item: Approval }
  | { kind: 'chart'; item: ChartItem }
  | { kind: 'moment'; item: MomentItem }

// Consecutive tool calls collapse into one group (Dolly's ToolCallGroup); a
// speaker label shows only when the speaker changes.
function toRows(items: ChatItem[], hideTools = false): Row[] {
  const rows: Row[] = []
  if (hideTools) items = items.filter((it) => it.kind !== 'tool')
  let lastSpeaker: string | null = null
  for (let i = 0; i < items.length; i++) {
    const it = items[i]!
    if (it.kind === 'tool') {
      const run: ToolCall[] = []
      while (i < items.length && items[i]!.kind === 'tool') run.push(items[i++] as ToolCall)
      i--
      rows.push(run.length > 1 ? { kind: 'group', items: run } : { kind: 'tool', item: run[0]! })
      lastSpeaker = 'agent'
      continue
    }
    if (it.kind === 'link') { rows.push({ kind: 'link', item: it }); lastSpeaker = null; continue }
    if (it.kind === 'approval') { rows.push({ kind: 'approval', item: it }); lastSpeaker = 'agent'; continue }
    if (it.kind === 'chart') { rows.push({ kind: 'chart', item: it }); lastSpeaker = 'agent'; continue }
    if (it.kind === 'moment') { rows.push({ kind: 'moment', item: it }); lastSpeaker = null; continue }
    rows.push({ kind: 'message', item: it, showLabel: lastSpeaker !== it.role && !it.label })
    lastSpeaker = it.role
  }
  return rows
}


type Sheet = 'settings' | 'threads' | 'memory' | 'plan'
// Full-screen pages over the tabs (each with its own close): plan setup, profile, people, gear.
type PlanScreen = 'setup' | 'profile' | 'coach' | 'coaches' | 'athletes' | 'racepack' | 'quests' | 'gear' | 'findcoach'
type ProgressView = 'overview' | 'recap'
type RacesView = 'mine' | 'explore'

const noop = () => {}
// Touch devices: focusing the composer means the keyboard is coming, so make room for it.
const coarsePointer = () => { try { return window.matchMedia('(pointer: coarse)').matches } catch { return false } }

export function Chat({ me, onChange }: { me: Me; onChange: () => void }) {
  const [threads, setThreads] = useState<Thread[]>([])
  const [goal, setGoal] = useState<Goal | null>(me.goal)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [queued, setQueued] = useState<QueuedSend | null>(null)
  // A new chat is a client-side draft until its first message is sent (then it's created).
  const [pending, setPending] = useState<{ seed?: { thread_id: string; turn_id: string }; seedMsg?: ChatMessage } | null>(null)
  const { items, ready, status, send, stop, decide, reload, loadError, retry } =
    useCoach(threadId, { turn: me.chat.active_turn, thread: me.chat.active_thread }, queued, () => setQueued(null))
  const [sheet, setSheet] = useState<Sheet | null>(me.garmin.connected ? null : 'settings')
  const [closing, setClosing] = useState(false)
  const [planScreen, setPlanScreen] = useState<PlanScreen | null>(null)
  const [addPlan, setAddPlan] = useState(false)
  const [coachMsgThread, setCoachMsgThread] = useState<string | null>(null)
  const [coachAsk, setCoachAsk] = useState(false) // "Do you want a coach?" sheet
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<{ text: string; n: number } | null>(null)
  const [menu, setMenu] = useState<MenuTarget | null>(null)
  const [peek, setPeek] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; n: number } | null>(null)
  const [voice, setVoice] = useState<{ sessionId?: string; activityId?: number; title?: string } | null>(null)
  const [fitEvent, setFitEvent] = useState<string | null>(null) // race readiness from a moment
  const [feedTick, setFeedTick] = useState(0) // bump: re-read the log (new moments from sync/progress)
  const showToast = (msg: string) => setToast((t) => ({ msg, n: (t?.n ?? 0) + 1 }))
  const feed = useRef<HTMLDivElement>(null)
  // Was the user at the bottom of the feed? Kept current by scroll events, so that when the
  // feed resizes (keyboard opening/closing) we can keep the newest messages in view.
  const atBottom = useRef(true)

  // Tabs (components/nav/TabBar): Rabbit | Plan | Community | Events | Progress; Me opens from
  // the header avatar. The last tab is kept for this browser session; notification links pick their own.
  const openParam = useRef(new URLSearchParams(window.location.search).get('open')).current
  const [tab, setTabState] = useState<TabId>(() => openParam === 'recap' ? 'progress' : openParam === 'coach' ? 'rabbit'
    : openParam === 'community' ? 'community' : readTab())
  const setTab = useCallback((t: TabId) => { setTabState(t); saveTab(t) }, [])
  const [progressView, setProgressView] = useState<ProgressView>(openParam === 'recap' ? 'recap' : 'overview')
  const [recapWeek, setRecapWeek] = useState<string | undefined>(undefined)
  const [racesView, setRacesView] = useState<RacesView>('mine')
  const [meOpen, setMeOpen] = useState(false) // Me: from the avatar in the tab headers
  const [communityView, setCommunityView] = useState<CommunityView>('feed')
  const [communityClub, setCommunityClub] = useState<string | null>(null)
  const [composerFocus, setComposerFocus] = useState(false)
  const friendsDot = useSocialBadge()

  const thread = threads.find((t) => t.id === threadId) ?? null
  const byId = useMemo(() => Object.fromEntries(threads.map((t) => [t.id, t])), [threads])
  // Rabbit's log is a timeline: no lookup cards there (they stay in topic threads).
  const rows = useMemo(() => toRows(items, thread?.kind === 'coach'), [items, thread?.kind])
  const last = items[items.length - 1]
  const waitingOnYou = items.some((it) => it.kind === 'approval' && it.status === 'pending')
  const thinking = status === 'streaming' && !waitingOnYou && !(last?.kind === 'message' && last.role === 'agent')

  // Couldn't load the chat list (the thread to select once it loads, if any).
  const [threadsError, setThreadsError] = useState<{ select?: string } | null>(null)
  const refreshThreads = useCallback(async (select?: string) => {
    const r = await listThreads().catch(() => null)
    if (!r) { setThreadsError({ select }); return }
    setThreadsError(null)
    setThreads(r.threads)
    setGoal(r.goal)
    setThreadId((cur) => select ?? (cur && r.threads.some((t) => t.id === cur) ? cur
      : r.threads.find((t) => t.kind === 'coach')?.id ?? r.threads[0]?.id ?? null))
  }, [])

  useEffect(() => { void refreshThreads() }, [refreshThreads])
  // After each reply: pick up a new thread title, or a goal/plan Rabbit just saved.
  const prevStatus = useRef(status)
  useEffect(() => {
    if ((prevStatus.current === 'streaming' || prevStatus.current === 'busy') && status === 'idle') {
      void refreshThreads(); onChange()
      if (tab !== 'rabbit') signalReplyDone() // the Rabbit tab wiggles
    }
    prevStatus.current = status
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the phone's time zone (first run, and after travel) so "today", the plan week
  // and the morning brief match where you are. Checked on open and on return to the app.
  const savedTz = me.settings.timezone_set ? me.settings.timezone : null
  const tzSent = useRef<string | null>(null)
  useEffect(() => {
    const check = () => {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
      if (!tz || tz === savedTz || tz === tzSent.current) return
      tzSent.current = tz
      void putSettings({ timezone: tz }).then(() => {
        if (savedTz) showToast(`Time zone updated to ${tz.split('/').pop()!.replace(/_/g, ' ')}`)
        onChange()
      }).catch(() => { tzSent.current = null })
    }
    check()
    const onVis = () => { if (document.visibilityState === 'visible') check() }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [savedTz]) // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard opens/closes (or anything else resizes the feed): stay pinned to the newest
  // messages if that's where the user was.
  useEffect(() => {
    atBottom.current = true // a freshly opened chat starts at its newest messages
    const el = feed.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      if (atBottom.current) el.scrollTop = el.scrollHeight
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [threadId, pending, items.length === 0])

  // An approval is waiting on you: bring it into view.
  const pendingCount = items.filter((it) => it.kind === 'approval' && it.status === 'pending').length
  useEffect(() => {
    if (pendingCount) feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: 'smooth' })
  }, [pendingCount])

  // Stick to the bottom while streaming, unless the user scrolled up to read.
  useEffect(() => {
    const el = feed.current
    if (!el) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 150 || status !== 'streaming') {
      el.scrollTo({ top: el.scrollHeight, behavior: status === 'streaming' ? 'instant' : 'smooth' })
    }
  }, [items, status])

  const open = (s: Sheet) => { setClosing(false); setSheet(s) }
  const coachId = threads.find((t) => t.kind === 'coach')?.id ?? null
  // "Tell Rabbit…": go to Rabbit's log with the composer prefilled.
  const tellRabbit = (text: string) => {
    setPending(null)
    if (coachId) setThreadId(coachId)
    setDraft((d) => ({ text, n: (d?.n ?? 0) + 1 }))
    if (sheet) { setSheet(null); setClosing(false) }
    setPlanScreen(null)
    setTab('rabbit')
  }
  const builtPlan = goal?.plan_source === 'builder'
  const showScreen = (sc: PlanScreen) => { if (sheet) { setSheet(null); setClosing(false) } setPlanScreen(sc) }
  const startSetup = () => showScreen('setup')
  // A tab, with whatever was open on top of it closed.
  const goTab = (t: TabId) => {
    if (sheet) { setSheet(null); setClosing(false) }
    setPlanScreen(null)
    setMeOpen(false)
    setTab(t)
  }
  const openPlan = () => goTab('plan')
  const openRaces = () => { setRacesView('mine'); goTab('races') }
  const openProgress = () => { setProgressView('overview'); goTab('progress') }
  const openRecap = (week?: string) => { setRecapWeek(week); setProgressView('recap'); goTab('progress') }
  const openCommunity = (v: CommunityView = 'feed', club?: string) => {
    setCommunityView(v); setCommunityClub(club ?? null); goTab('community')
  }
  // Nothing open over the tabs: progress, Today and live sync refresh.
  const overlayFree = !planScreen && !sheet
  const homeInView = tab === 'rabbit' && overlayFree
  // Gamification: level, streak, this week and setup quests (status banner, Me, Progress).
  const [progress, setProgress] = useState<Progress | null>(null)
  useEffect(() => {
    if (!overlayFree) return
    let live = true
    getProgress().then((p) => { if (live) setProgress(p) }, () => {})
    return () => { live = false }
  }, [overlayFree, tab, me])
  // Today card (today.py): one recommendation; it replaces the race-soon and adjust banners.
  const [today, setToday] = useState<Today | null>(null)
  const topInsight = useTopInsight(today?.date)
  const loadToday = useCallback(() => { getToday().then(setToday, () => {}) }, [])
  // Workout day: the pre-workout screen (from Today / the plan) and the post-workout reaction.
  const [workout, setWorkout] = useState<{ sessionId?: string } | null>(null)
  const [reaction, setReaction] = useState<number | null>(null)
  useEffect(() => { if (homeInView) loadToday() }, [homeInView, me, loadToday])
  const todayAction = (kind: TodayActionKind) => {
    if (kind === 'open_racepack') { openRaces(); setPlanScreen('racepack') }
    else if (kind === 'review_adjust') openPlan()
    else if (kind === 'open_session') { if (today?.session?.id) setWorkout({ sessionId: today.session.id }); else openPlan() }
    else if (kind === 'build_plan') startSetup()
    else if (kind === 'log_rest') showToast('Enjoy the rest. Recovery is training too.')
    else tellRabbit(today?.tone === 'done' ? "About today's workout: " : `About today (${today?.headline ?? 'my training'}): `)
  }
  // Live workout sync (sync.py): on open, on return to the app and every minute while no
  // screen is open over the tabs. One request at a time; a new workout refreshes XP, the
  // week and the Today card.
  const syncing = useRef(false)
  useEffect(() => {
    if (!overlayFree || !me.garmin.connected) return
    const run = async () => {
      if (syncing.current || document.visibilityState !== 'visible') return
      syncing.current = true
      try {
        const r = await syncNow()
        if (!r.changed) return
        const p = await getProgress().catch(() => null)
        if (p) setProgress(p)
        setFeedTick((n) => n + 1) // the sync posted a "Logged: …" moment in Rabbit's log
        loadToday()
        loadWeek()
        const a = r.new[r.new.length - 1]
        if (a?.id != null && !reactionShown(a.id)) { markReactionShown(a.id); setReaction(a.id); return }
        const xp = p && p.gained > 0 ? ` · +${p.gained} XP` : ''
        if (p && p.gained > 0) celebrate({ x: window.innerWidth / 2, y: window.innerHeight - 120 }, 'xp')
        showToast(a ? `Workout synced: ${a.name}${xp}` : `Workout synced${xp}`)
      } catch { /* offline or signed out: try again next time */ } finally {
        syncing.current = false
      }
    }
    void run()
    const onVis = () => { if (document.visibilityState === 'visible') { setFeedTick((n) => n + 1); void run() } }
    document.addEventListener('visibilitychange', onVis)
    const timer = window.setInterval(() => void run(), 60_000)
    return () => { document.removeEventListener('visibilitychange', onVis); window.clearInterval(timer) }
  }, [overlayFree, me.garmin.connected, loadToday]) // eslint-disable-line react-hooks/exhaustive-deps
  // Moments that arrived while the app was open: refresh the log without a reload.
  useEffect(() => {
    if (feedTick && status === 'idle' && thread?.kind === 'coach') void reload()
  }, [feedTick]) // eslint-disable-line react-hooks/exhaustive-deps
  // Weekly recap (recap.py): from the Sunday push (?open=recap: Progress → Weekly recap), the
  // status banner (Sunday noon through Monday, dismissible per week) and Progress.
  useEffect(() => {
    if (openParam === 'recap' || openParam === 'community') window.history.replaceState(null, '', '/app/')
    const onMsg = (e: MessageEvent) => {
      if (e.data?.type === 'open' && String(e.data.url).includes('open=recap')) openRecap()
      if (e.data?.type === 'open' && String(e.data.url).includes('open=community')) openCommunity()
    }
    navigator.serviceWorker?.addEventListener('message', onMsg)
    return () => navigator.serviceWorker?.removeEventListener('message', onMsg)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const recapPillWeek = (() => {
    const now = new Date()
    if (now.getDay() === 0 && now.getHours() >= 12) return shiftWeek(localDay(now), 0)
    if (now.getDay() === 1) return shiftWeek(localDay(now), -1)
    return null
  })()
  const [recapDismissed, setRecapDismissed] = useState<string | null>(() => {
    try { return window.localStorage.getItem('rabbit.recap.dismissed') } catch { return null }
  })
  const dismissRecapPill = (wk: string) => {
    setRecapDismissed(wk)
    try { window.localStorage.setItem('rabbit.recap.dismissed', wk) } catch { /* this session only */ }
  }
  const doQuest = (q: QuestId) => {
    if (q === 'garmin' || q === 'notify' || q === 'calendar' || q === 'oura') { setPlanScreen(null); open('settings'); return }
    if (q === 'sports') { showScreen('profile'); return }
    if (q === 'coach') { showScreen('coaches'); return }
    if (q === 'coach_status') { setCoachAsk(true); return }
    if (q === 'gear') { showScreen('gear'); return }
    if (q === 'friend') { openCommunity('people'); return }
    if (q === 'interests') { setRacesView('explore'); goTab('races'); return }
    if (q === 'sync' && builtPlan) { openPlan(); return }
    showScreen('setup')
  }
  // "Message coach" from a session in the plan: open (or create) that workout's thread.
  const messageCoach = async (s: { id: string }) => {
    try {
      const c = (await getCoaches()).coaches[0]
      if (!c) return
      const r = await athleteChat.open({ coach: c.email, session_id: s.id })
      setCoachMsgThread(r.thread.id)
      setPlanScreen('coach')
    } catch (e) { showToast((e as Error).message) }
  }
  const close = () => { setClosing(true); setTimeout(() => { setSheet(null); setClosing(false) }, 200) }
  // Drag-dismiss animates itself out, then unmounts at once (no second exit animation).
  const dismissNow = useCallback(() => { setSheet(null); setClosing(false) }, [])
  const settingsDrag = useSheetDrag(dismissNow)

  function newThread(from?: { thread_id: string; turn_id: string }, seedMsg?: ChatMessage) {
    setPending({ seed: from, seedMsg })
    if (sheet) close()
  }

  const openThread = (id: string) => { setPending(null); setThreadId(id) }

  const [sourcesAsk, setSourcesAsk] = useState(false)
  // Back from connecting Google Calendar or Oura.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const cal = params.get('calendar'), oura = params.get('oura')
    if (!cal && !oura) return
    window.history.replaceState(null, '', '/app/')
    if (cal) showToast(cal === 'connected' ? 'Google Calendar connected' : "Couldn't connect Google Calendar")
    if (oura) showToast(oura === 'connected' ? 'Oura connected' : "Couldn't connect Oura")
    if (oura === 'connected') setSourcesAsk(true)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // Data sources (lib/sources.ts): screens read the current choice; ask once how to use Oura
  // (right after connecting it, or on the next open for anyone connected before this existed).
  useEffect(() => { setCurrentSources(me.settings.data_sources) }, [me.settings.data_sources])
  useEffect(() => {
    if (me.oura.connected && me.settings.data_sources_asked === false) setSourcesAsk(true)
  }, [me.oura.connected, me.settings.data_sources_asked])
  // Tapping a brief or workout-note notification opens Rabbit's log: from a cold start via
  // ?open=coach, or (app already running) via a message from the service worker.
  const openCoach = useRef(openParam === 'coach')
  useEffect(() => {
    if (openCoach.current) window.history.replaceState(null, '', '/app/')
    const onMsg = (e: MessageEvent) => {
      if (e.data?.type !== 'open' || !String(e.data.url).includes('open=coach')) return
      openCoach.current = true
      void refreshThreads() // also picks up the new message's thread state
    }
    navigator.serviceWorker?.addEventListener('message', onMsg)
    return () => navigator.serviceWorker?.removeEventListener('message', onMsg)
  }, [refreshThreads])
  useEffect(() => {
    if (!openCoach.current || !coachId) return
    openCoach.current = false
    setPending(null)
    setThreadId(coachId)
    setSheet(null)
    setClosing(false)
    setPlanScreen(null)
    setTab('rabbit')
  }, [coachId, threads, setTab])

  // First message of a draft chat: only now is the thread created on the server.
  async function sendPending(text: string, attachments: AttachmentMeta[]) {
    if (!pending) return
    setBusy(true)
    try {
      const t = await createThread(pending.seed)
      setQueued({ threadId: t.id, text, attachments })
      setPending(null)
      await refreshThreads(t.id)
    } catch (e) {
      showToast((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const isCoach = !pending && thread?.kind === 'coach'
  // Rabbit's log is home; other chats sit on top of it, with a back button and an edge
  // swipe. The log's last rows are kept so it can be drawn underneath a chat during the
  // swipe, and shown at once on the way back while its history reloads.
  const coachRows = useRef<Row[] | null>(null)
  if (isCoach && ready && status === 'idle') coachRows.current = rows
  const shownRows = ready ? rows : isCoach ? coachRows.current ?? [] : []
  const settled = ready && status !== 'loading'
  const goBack = () => { if (coachId) openThread(coachId) }
  const inChat = !isCoach && !!coachId
  const screen = useRef<HTMLDivElement>(null)
  const under = useRef<HTMLDivElement>(null)
  const underFeed = useRef<HTMLDivElement>(null)
  const { slideIn, slideBack } = useEdgeSwipe(screen, under, { enabled: tab === 'rabbit' && inChat && !sheet && !menu && !peek, onBack: goBack })
  // Opening a chat from the log slides it in over the log.
  const wasInChat = useRef(inChat)
  useLayoutEffect(() => {
    if (inChat && !wasInChat.current) slideIn()
    wasInChat.current = inChat
  }, [inChat, slideIn])
  // The log underneath sits at its newest entries, where the real log opens.
  useLayoutEffect(() => {
    const el = underFeed.current
    if (el) el.scrollTop = el.scrollHeight
  }, [inChat, threadId])

  // This plan week: dots on the Today card, the day list on the Plan tab. Refreshed when
  // either is shown, after each reply (a plan may have changed) and on return to the app.
  const [week, setWeek] = useState<PlanWeek | null>(null)
  const [weekLoading, setWeekLoading] = useState(false)
  const [weekError, setWeekError] = useState(false)
  const needWeek = !!goal && (tab === 'plan' || (tab === 'rabbit' && isCoach))
  const loadWeek = useCallback(() => {
    setWeekLoading(true)
    getPlanWeek().then((w) => { setWeek(w); setWeekError(false) }, () => setWeekError(true))
      .finally(() => setWeekLoading(false))
  }, [])
  useEffect(() => {
    if (!needWeek || status !== 'idle') return
    loadWeek()
    const onVis = () => { if (document.visibilityState === 'visible') loadWeek() }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [needWeek, status, goal?.plan, loadWeek])
  const askDay = (d: WeekDay, session?: PlannedSession) => {
    const when = d.today ? "today's" : `${new Date(`${d.date}T12:00:00`).toLocaleDateString([], { weekday: 'long' })}'s`
    tellRabbit(session ? `About ${when} ${session.title}: ` : `About ${d.today ? 'today' : when.slice(0, -2)}: `)
  }


  const press = useLongPress((el) => {
    if (el.dataset.threadId) { hapticTap(); setPeek(el.dataset.threadId); return }
    const id = el.dataset.msgId
    const item = items.find((it): it is ChatMessage => it.kind === 'message' && it.id === id)
    if (!item || item.error) return
    hapticTap()
    setMenu({ item, el, canDiscuss: isCoach && item.turnKind === 'proactive' && !!item.turnId })
  })

  // Rabbit's log stays a timeline: a message typed there starts a new topic thread.
  // A brief or workout note from the last 18 hours comes along as context (like Discuss).
  async function sendFromLog(text: string, attachments: AttachmentMeta[]) {
    if (!thread) return
    const cutoff = Date.now() / 1000 - 18 * 3600
    const recent = [...items].reverse().find((it): it is ChatMessage =>
      it.kind === 'message' && it.turnKind === 'proactive' && !!it.turnId && (it.ts ?? 0) > cutoff)
    setBusy(true)
    try {
      const t = await createThread(recent ? { thread_id: thread.id, turn_id: recent.turnId! } : undefined)
      setQueued({ threadId: t.id, text, attachments })
      await refreshThreads(t.id)
    } catch (e) {
      showToast((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const intents = intentsOf(me) // lib/intent.ts: what they came for leads Rabbit home
  const suggestions = isCoach ? intentSuggestions(intents, COACH_SUGGESTIONS) : TOPIC_SUGGESTIONS
  // A moment's action chip, routed to the screens that already exist.
  const momentAction = (a: MomentAction) => {
    if (a.id === 'checkin') setVoice({ activityId: a.activity_id, title: a.title })
    else if (a.id === 'reaction') { if (a.activity_id != null) setReaction(a.activity_id) }
    else if (a.id === 'readiness') { if (a.event_id) setFitEvent(a.event_id); else openRaces() }
    else if (a.id === 'racepack') { openRaces(); setPlanScreen('racepack') }
    else if (a.id === 'plan') openPlan()
    else if (a.id === 'progress') openProgress()
    else if (a.id === 'community_share' && a.draft_id) {
      shareDraft(a.draft_id).then(() => showToast('Shared in Community 🎉'), (e) => showToast((e as Error).message))
    } else if (a.id === 'community_later' && a.draft_id) {
      dismissDraft(a.draft_id).then(() => showToast('Okay, kept it to yourself.'), () => showToast('Okay.'))
    } else if (a.id === 'community') { if (a.club_id) openCommunity('clubs', a.club_id); else openCommunity() }
    else if (a.id === 'ask') tellRabbit(a.prompt ?? '')
    else if (a.id === 'race_invite') openRaces() // the invites inbox sits on top of Races
  }
  // Quick replies under Rabbit's latest message when it asks something (max 3).
  const lastRow = shownRows[shownRows.length - 1]
  const chips = status === 'idle' && me.chat.available && lastRow?.kind === 'message' && lastRow.item.role === 'agent' && !lastRow.item.error
    ? replyChips(lastRow.item.text) : []
  const idlePrompt = useRotatingPrompt(tab === 'rabbit' && status === 'idle' && !composerFocus, composerPrompts(intents))
  const countdown = goalCountdown(goal)
  const coachThread = coachId ? byId[coachId] : undefined

  // Rabbit's one status slot, most important first.
  const quest = progress ? nextQuest(progress) : null
  const recapReady = !!recapPillWeek && recapDismissed !== recapPillWeek
  const banner: Banner | null = threadsError ? { kind: 'error' }
    : !me.garmin.connected ? { kind: 'garmin' }
    : isCoach && wantsPlan(intents) && (!goal ? items.length > 0 : !goal.plan) ? { kind: 'plan', goal: goal?.title ?? null }
    : isCoach && quest && progress ? { kind: 'quest', title: quest.title, done: progress.setup.done, total: progress.setup.total }
    : isCoach && recapReady ? { kind: 'recap' }
    : null
  const tapBanner = () => {
    if (!banner) return
    if (banner.kind === 'error') void refreshThreads(threadsError?.select)
    else if (banner.kind === 'garmin') open('settings')
    else if (banner.kind === 'plan') startSetup()
    else if (banner.kind === 'quest' && quest) doQuest(quest.id)
    else if (banner.kind === 'recap') openRecap(recapPillWeek ?? undefined)
  }
  // Typing on a phone: the keyboard needs the room, so the banner, Today and the tab bar step aside.
  const typing = composerFocus

  // "Me" (profile, coaching, Settings) opens from the avatar in every tab header.
  const meButton = (
    <button className="relative flex size-11 shrink-0 items-center justify-center rounded-full" aria-label={
      me.coach_unread > 0 ? `Me, ${me.coach_unread} unread from your coach` : 'Me'} onClick={() => setMeOpen(true)}>
      <Avatar name={me.profile.name || me.user_id} picture={me.profile.picture} photo={photoUrl(me.photo)} />
      {me.coach_unread > 0 && <span className="absolute right-1 top-1 size-2.5 rounded-full bg-(--accent) ring-2 ring-(--bg)" aria-hidden />}
    </button>
  )

  function renderHeader(isLog: boolean, under = false) {
    return (
      <header className="flex shrink-0 items-center gap-2 border-b border-(--border) px-3 pb-2.5 pt-[max(10px,env(safe-area-inset-top))]">
        {!isLog && (
          <Button variant="ghost" size="icon" className="-mr-1" aria-label="Back to Rabbit" onClick={slideBack}>
            <ChevronLeft className="size-5" />
          </Button>
        )}
        <button className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
          aria-label={isLog ? 'Rabbit' : 'Back to Rabbit'} onClick={isLog ? goBack : slideBack}>
          {/* App-icon tile, like the Home Screen icon (hops while Rabbit is replying) */}
          <span className="logo-tile flex size-[38px] shrink-0 items-center justify-center rounded-[11px] bg-(--brand) shadow-sm">
            <RabbitLogo size={32} thinking={!under && status === 'streaming'} />
          </span>
          <span className="min-w-0">
            <span className="block truncate font-display text-lg leading-tight text-(--brand)">
              {isLog ? 'Rabbit' : pending ? 'New chat' : thread?.title || 'New chat'}
            </span>
            <span className="block truncate text-[0.6471rem] leading-tight text-muted-foreground">
              {goal ? `${goal.title}${countdown ? ` · ${countdown}` : ''}` : 'No goal set'}
            </span>
          </span>
        </button>
        <Button variant="ghost" size="icon" aria-label="Chats with Rabbit" onClick={() => open('threads')}>
          <MessagesSquare className="size-5" />
        </Button>
        {meButton}
      </header>
    )
  }

  function renderRows(list: Row[], inLog: boolean) {
    return list.map((r) => {
      if (r.kind === 'link') {
        if (!byId[r.item.threadId]) return null // chat was deleted
        return <ThreadLinkCard key={r.item.id} thread={byId[r.item.threadId]} pressProps={press}
          onOpen={() => openThread(r.item.threadId)} />
      }
      if (r.kind === 'chart') {
        return (
          <div key={r.item.id} className="w-full max-w-[92%] [&>figure]:my-0 [&>figure]:bg-background">
            <Chart spec={r.item.spec} />
          </div>
        )
      }
      if (r.kind === 'approval') {
        return <ApprovalCard key={r.item.id} item={r.item}
          onDecide={(ok, why) => void decide(r.item.id, ok, why).then(() => { if (ok) onChange() })} />
      }
      if (r.kind === 'moment') return <MomentCard key={r.item.id} item={r.item} onAction={momentAction} />
      if (r.kind === 'tool') return <ToolCallCard key={r.item.id} toolCall={r.item} />
      if (r.kind === 'group') return <ToolCallGroup key={`g-${r.items[0]!.id}`} toolCalls={r.items} />
      const m = r.item
      const seed = m.turnKind === 'seed'
      return (
        <div key={m.id} className={seed ? 'rounded-xl border border-dashed border-border p-2' : ''}>
          {seed && <p className="mb-1 pl-1 text-[0.6471rem] font-semibold uppercase tracking-widest text-muted-foreground">From Rabbit's log</p>}
          <CoachHeader label={m.label} ts={m.ts} />
          <MessageBubble message={m} showLabel={r.showLabel} pressProps={press} />
          {inLog && m.turnKind === 'proactive' && m.turnId && coachThread && (
            <DiscussButton busy={busy} onClick={() => newThread({ thread_id: coachThread.id, turn_id: m.turnId! }, m)} />
          )}
        </div>
      )
    })
  }

  // ------------------------------------------------------------------ tabs ---
  const imperial = me.athlete.units === 'imperial'
  const selectTab = (t: TabId) => {
    if (t === tab && t === 'rabbit') {
      // Rabbit again: back to the log from a chat, else to its newest entries.
      if (inChat || pending) { if (pending) setPending(null); else slideBack() }
      else feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: 'smooth' })
      return
    }
    setTab(t)
  }
  const soonRace = !!goal?.date && daysUntil(goal.date) >= 0 && daysUntil(goal.date) <= 14
  const tabDots: Partial<Record<TabId, string | false>> = {
    races: soonRace && 'race soon',
    community: friendsDot && 'new from friends',
  }
  const openMeRow = (r: MeRow) => {
    if (r === 'friends') { setMeOpen(false); openCommunity('people') }
    else if (r === 'settings') open('settings')
    else if (r === 'memory') open('memory')
    else if (r === 'inbox') { setCoachMsgThread(null); showScreen('coach') }
    else if (r === 'coachstatus') setCoachAsk(true)
    else showScreen(r)
  }
  const weekLead = goal ? <WeekList imperial={me.athlete.units === 'imperial'} week={week} loading={weekLoading} error={weekError} onRetry={loadWeek} onAskDay={askDay} /> : null

  function planTab() {
    if (builtPlan) {
      return (
        <TabScreen key="planner" title="Plan" lead={weekLead} action={meButton}>
          <PlanEditor me={me} goalTitle={goal?.title ?? 'Your race'} onClose={noop}
            onRebuild={startSetup}
            onAsk={tellRabbit}
            onChanged={() => { void refreshThreads(); loadWeek() }}
            onMeChanged={onChange}
            onOpenEvents={openRaces}
            onMessage={me.coaches > 0 ? (s) => void messageCoach(s) : undefined} messageLabel="Message coach"
            onOpenWorkout={(id) => setWorkout({ sessionId: id })} />
        </TabScreen>
      )
    }
    return (
      <TabScreen key="start" action={meButton}>
        <Screen title="Plan" subtitle={goal ? goal.title : 'No plan yet'} onClose={noop}>
          {weekLead}
          {goal?.plan ? (
            <Group label="Your plan">
              <SettingsRow icon={<Icon><FileText /></Icon>} title="Plan from your coach or app" subtitle={planLine(week, goal)}
                onClick={() => open('plan')} />
              <SettingsRow icon={<Icon><Sparkles /></Icon>} title="Build my plan in Rabbit"
                subtitle="Editable sessions you can send to your Garmin" onClick={startSetup} />
            </Group>
          ) : (
            <>
              <button type="button" onClick={startSetup}
                className="flex items-center gap-3 rounded-xl border border-(--accent) bg-(--accent-subtle) px-4 py-3.5 text-left shadow-sm active:opacity-80">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-white"><Sparkles className="size-5" /></span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[0.9412rem] font-semibold text-(--accent)">Build my plan</span>
                  <span className="block text-[0.7059rem] text-(--text-muted)">About 3 minutes · race, goals, you, your week</span>
                </span>
                <ChevronRight className="size-4 shrink-0 text-(--accent)" />
              </button>
              <Group>
                <SettingsRow icon={<Icon tone="muted"><Upload /></Icon>} title="I already have a plan"
                  subtitle="A file, screenshots, pasted text or a template" onClick={() => setAddPlan(true)} />
              </Group>
            </>
          )}
        </Screen>
      </TabScreen>
    )
  }

  function progressTab() {
    const seg = <Segmented label="Progress" value={progressView} onChange={setProgressView}
      options={[['overview', 'Overview'], ['recap', 'Weekly recap']] as const} />
    if (progressView === 'recap') {
      return (
        <TabScreen key="recap" title="Progress" top={seg} action={meButton}>
          <RecapSheet week={recapWeek} onClose={() => setProgressView('overview')} onAsk={tellRabbit} />
        </TabScreen>
      )
    }
    return (
      <TabScreen key="overview" title="Progress" top={seg} action={meButton}>
        <StatsScreen onClose={noop} oura={me.oura.connected} onOpenPlan={builtPlan ? openPlan : undefined}
          onOpenSetup={() => showScreen('quests')}
          onAsk={tellRabbit} onOpenGear={() => showScreen('gear')} onOpenSession={(id) => setWorkout({ sessionId: id })} />
      </TabScreen>
    )
  }

  function racesTab() {
    const seg = <Segmented label="Events" value={racesView} onChange={setRacesView}
      options={[['mine', 'My events'], ['explore', 'Explore']] as const} />
    return racesView === 'mine' ? (
      <TabScreen key="mine" title="Events" top={seg} action={meButton}>
        <EventsScreen hasBuiltPlan={builtPlan} imperial={imperial} onClose={noop}
          onChanged={() => { onChange(); void refreshThreads(); loadWeek() }}
          onOpenPlan={openPlan} onBuildPlan={startSetup} />
      </TabScreen>
    ) : (
      <TabScreen key="explore" title="Events" top={seg} action={meButton}>
        <ExploreScreen imperial={imperial} onClose={noop} onAsk={tellRabbit} onChanged={onChange} />
      </TabScreen>
    )
  }

  return (
    <div className={`relative flex min-h-0 flex-1 flex-col overflow-hidden ${typing ? '' : 'with-tabbar'}`}>
      {/* Rabbit stays mounted under the other tabs (its chat, scroll and stream live on). */}
      <div className={`relative min-h-0 flex-1 flex-col overflow-hidden ${tab === 'rabbit' ? 'flex' : 'hidden'}`}>
      {inChat && (
        // A still copy of Rabbit's log under the open chat, revealed by the edge swipe.
        <div ref={under} inert aria-hidden className="absolute inset-0 flex flex-col bg-background" style={{ visibility: 'hidden' }}>
          {renderHeader(true, true)}
          <div ref={underFeed} className="min-h-0 flex-1 overflow-hidden px-4">
            <div className="mx-auto max-w-2xl space-y-4 py-4">{renderRows(coachRows.current ?? [], true)}</div>
          </div>
          <Composer still disabled streaming={false} onStop={() => {}} onSend={() => {}} placeholder="Start a new chat…" />
        </div>
      )}
      <div ref={screen} className="relative flex min-h-0 flex-1 flex-col bg-background">
      {renderHeader(!pending && isCoach)}

      {banner && !typing && (
        <StatusBanner banner={banner} onTap={tapBanner}
          onDismiss={banner.kind === 'recap' && recapPillWeek ? () => dismissRecapPill(recapPillWeek) : undefined} />
      )}
      {isCoach && !typing && stripFirst(intents) && (
        <IntentStrip intents={intents} me={me} progress={progress} refreshKey={feedTick}
          onOpen={(t) => t === 'progress' ? goTab('progress') : t === 'events' ? openRaces() : t === 'explore' ? (setRacesView('explore'), goTab('races')) : t === 'coach' ? openMeRow('inbox') : t === 'friends' ? openCommunity() : showScreen(t)} />
      )}
      {isCoach && today && (today.garmin || !!goal) && !typing && (
        <TodayCard key={today.date} today={today} week={goal ? week?.days : null} onAction={todayAction} onAsk={tellRabbit}
          onOpenWorkout={(id) => setWorkout({ sessionId: id })} insight={topInsight} onOpenInsight={openProgress} />
      )}
      {isCoach && !typing && !stripFirst(intents) && intents.length > 1 && (
        <IntentStrip intents={intents.slice(1)} me={me} progress={progress} refreshKey={feedTick}
          onOpen={(t) => t === 'progress' ? goTab('progress') : t === 'events' ? openRaces() : t === 'explore' ? (setRacesView('explore'), goTab('races')) : t === 'coach' ? openMeRow('inbox') : t === 'friends' ? openCommunity() : showScreen(t)} />
      )}

      {pending ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
          <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col">
            {pending.seedMsg && (
              <div className="rounded-xl border border-dashed border-border p-2">
                <p className="mb-1 pl-1 text-[0.6471rem] font-semibold uppercase tracking-widest text-muted-foreground">From Rabbit's log</p>
                <CoachHeader label={pending.seedMsg.label} ts={pending.seedMsg.ts} />
                <MessageBubble message={pending.seedMsg} showLabel={false} />
              </div>
            )}
            <div className="chat-empty flex flex-1 flex-col items-center justify-center py-6 text-center">
              <EmptyHero suggestions={pending.seedMsg ? undefined : TOPIC_SUGGESTIONS.map((q) => (
                    <button key={q} disabled={!me.chat.available || busy}
                      className="w-full cursor-pointer rounded-(--radius) border border-border bg-background px-3.5 py-2.5 text-left text-[0.7647rem] text-foreground/80 transition-all hover:bg-secondary disabled:opacity-50"
                      onClick={() => void sendPending(q, [])}>{q}</button>
                  ))}>
                {!pending.seedMsg && <RabbitLogo size={64} className="mb-3 opacity-40" />}
                <p className="mb-2 font-display text-xl leading-tight text-(--brand)">
                  {pending.seedMsg ? 'What would you like to ask about this?' : 'Ready when you are.'}
                </p>
              </EmptyHero>
            </div>
          </div>
        </div>
      ) : !ready && !isCoach ? (
        // Opening a chat: Rabbit hops while its messages load.
        <div className="chat-loading flex flex-1 items-center justify-center">
          <RabbitLoader size={56} label="Loading chat" />
        </div>
      ) : loadError && items.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-[0.8235rem] text-muted-foreground" role="alert">
          <p>Couldn't load this chat.</p>
          <button type="button" className="min-h-11 underline" onClick={() => void retry()}>Retry</button>
        </div>
      ) : items.length === 0 && settled && isCoach && !goal && wantsPlan(intents) ? (
        <div className="flex flex-1 flex-col justify-center overflow-y-auto px-4 py-6">
          <div className="mx-auto flex w-full max-w-md flex-col gap-4">
            <div className="flex flex-col items-center text-center">
              <span className="logo-tile mb-4 flex size-16 items-center justify-center rounded-[18px] bg-(--brand) shadow-sm">
                <RabbitLogo size={52} />
              </span>
              <p className="font-display text-[1.6471rem] leading-tight text-(--brand)">
                Hi{me.profile.name ? ` ${me.profile.name.split(' ')[0]}` : ''}, let's build your plan
              </p>
              <p className="mt-2 text-[0.8235rem] leading-snug text-(--text-secondary)">
                Tell Rabbit about your race, your goals and your week. You'll get a plan from today to race day, with workouts you can send straight to your Garmin.
              </p>
            </div>
            <button type="button" onClick={startSetup}
              className="flex items-center gap-3 rounded-xl border border-(--accent) bg-(--accent-subtle) px-4 py-3.5 text-left shadow-sm active:opacity-80">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-white"><Sparkles className="size-5" /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-[0.9412rem] font-semibold text-(--accent)">Build my plan</span>
                <span className="block text-[0.7059rem] text-(--text-muted)">About 3 minutes · race, goals, you, your week</span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-(--accent)" />
            </button>
            <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
              <label htmlFor={ATTACH_INPUT_ID} onClick={() => setDraft((d) => ({ text: "Here's my training plan.", n: (d?.n ?? 0) + 1 }))}
                className="flex cursor-pointer items-center gap-3 px-4 py-3 active:bg-(--bg-inset)">
                <Upload className="size-4 shrink-0 text-(--text-secondary)" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[0.8235rem] text-(--text)">I already have a plan</span>
                  <span className="block text-[0.6471rem] text-(--text-muted)">Send a PDF or screenshots from a coach or app</span>
                </span>
              </label>
              <button type="button" onClick={() => tellRabbit("I'm training for ")}
                className="flex w-full items-center gap-3 border-t border-(--border) px-4 py-3 text-left active:bg-(--bg-inset)">
                <MessageCircle className="size-4 shrink-0 text-(--text-secondary)" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[0.8235rem] text-(--text)">Just chat with Rabbit</span>
                  <span className="block text-[0.6471rem] text-(--text-muted)">Describe your race and training in your own words</span>
                </span>
              </button>
            </div>
          </div>
        </div>
      ) : items.length === 0 && settled ? (
        <div className="chat-empty flex flex-1 flex-col items-center justify-center px-6 text-center">
          <EmptyHero gap={20} suggestions={suggestions.map((s) => (
              <button key={s} disabled={!me.chat.available}
                className="w-full cursor-pointer rounded-(--radius) border border-border bg-background px-3.5 py-2.5 text-left text-[0.7647rem] text-foreground/80 transition-all hover:bg-secondary disabled:opacity-50"
                onClick={() => void (isCoach ? sendFromLog(s, []) : send(s))}>{s}</button>
            ))}>
          <RabbitLogo size={80} className="mb-3 opacity-40" />
          <p className="mb-2 font-display text-2xl leading-tight text-(--brand)">
            {isCoach ? 'Chat with Rabbit' : 'Ready when you are.'}
          </p>
          <p className="text-[0.7647rem] text-muted-foreground">
            {isCoach ? 'Morning briefs and workout notes land here. Ask anything about your training.'
              : 'Ask about your training, recovery or what to do next.'}
          </p>
          </EmptyHero>
        </div>
      ) : (
        <div ref={feed} className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4"
          onScroll={(e) => {
            const el = e.currentTarget
            atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
          }}>
          <div className="mx-auto max-w-2xl space-y-4 py-4">
            <PullToRefresh onRefresh={() => { void refreshThreads(); loadToday(); getProgress().then(setProgress, () => {}) }} />
            {renderRows(shownRows, isCoach)}
            <ReplyChips chips={chips} disabled={busy} onPick={(t) => void (isCoach ? sendFromLog(t, []) : send(t))} />
            {thinking && (
              <div className="flex items-center gap-2 pl-1 text-sm text-muted-foreground">
                <div className="thinking-dots flex items-center gap-[3px]"><span /><span /><span /></div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="contents"
        onFocus={(e) => { if (e.target instanceof HTMLTextAreaElement && coarsePointer()) setComposerFocus(true) }}
        onBlur={(e) => { if (e.target instanceof HTMLTextAreaElement) setComposerFocus(false) }}>
        <Composer
          disabled={pending ? (!me.chat.available || busy || status === 'streaming' || status === 'busy')
            : (status !== 'idle' || !me.chat.available || !threadId || busy)}
          streaming={status === 'streaming'}
          onStop={() => void stop()}
          onSend={(t, a) => void (pending ? sendPending(t, a) : isCoach ? sendFromLog(t, a) : send(t, a))}
          draft={draft}
          onMic={isCoach ? () => setVoice({}) : undefined}
          placeholder={!me.chat.available ? 'Chat isn’t configured yet' : waitingOnYou ? 'Approve or decline above…'
            : status === 'streaming' ? 'Rabbit is replying…' : status === 'busy' ? 'Rabbit is replying in another chat…' : idlePrompt}
        />
      </div>
      </div>
      </div>

      {tab === 'plan' && <div className="tab-page flex min-h-0 flex-1 flex-col">{planTab()}</div>}
      {tab === 'community' && (
        <div className="tab-page flex min-h-0 flex-1 flex-col">
          <TabScreen key="community" action={meButton}>
            <CommunityScreen imperial={imperial} view={communityView} onView={setCommunityView} onChanged={onChange}
              club={communityClub} onClub={setCommunityClub} />
          </TabScreen>
        </div>
      )}
      {tab === 'races' && <div className="tab-page flex min-h-0 flex-1 flex-col">{racesTab()}</div>}
      {tab === 'progress' && <div className="tab-page flex min-h-0 flex-1 flex-col">{progressTab()}</div>}
      {!typing && <TabBar tab={tab} onSelect={selectTab} dots={tabDots} />}

      {menu && (
        <MessageMenu target={menu} onClose={() => setMenu(null)} onToast={showToast}
          onDiscuss={() => { if (thread && menu.item.turnId) newThread({ thread_id: thread.id, turn_id: menu.item.turnId }, menu.item) }} />
      )}
      {peek && byId[peek] && (
        <ThreadPeek thread={byId[peek]!} onClose={() => setPeek(null)}
          onOpen={() => { setPeek(null); openThread(peek) }}
          onDelete={async () => {
            try {
              await deleteThread(peek)
              setPeek(null)
              await refreshThreads()
              reload()
              showToast('Chat deleted')
            } catch (e) { showToast((e as Error).message) }
          }} />
      )}
      <VoiceCheckIn open={!!voice} sessionId={voice?.sessionId} activityId={voice?.activityId} title={voice?.title} onClose={() => setVoice(null)} onSaved={(_, xp) => { loadToday(); if (xp) getProgress().then(setProgress, () => {}) }} />
      {sourcesAsk && me.oura.connected && (
        <DataSourcesSheet me={me} onClose={() => { setSourcesAsk(false); onChange() }}
          onSaved={(msg) => { setSourcesAsk(false); showToast(msg); onChange() }} />
      )}
      {toast && <div key={toast.n} className="rabbit-toast" role="status">{toast.msg}</div>}
      <WelcomeGate me={me} onSaved={onChange} onNext={(s) => s === 'progress' ? goTab('progress') : doQuest(s)} />

      {sheet === 'threads' && (
        <ThreadsSheet goal={goal} threads={threads} activeId={threadId} closing={closing} onDismissed={dismissNow}
          onSelect={(id) => { openThread(id); setTab('rabbit'); close() }}
          onNew={() => { setTab('rabbit'); newThread() }}
          onDelete={async (id) => {
            try { await deleteThread(id); await refreshThreads() } catch (e) { showToast((e as Error).message) }
          }}
          onEditGoal={() => open('memory')} onClose={close} />
      )}
      {sheet === 'memory' && (
        <MemorySheet goal={goal} athlete={me.athlete} closing={closing} onClose={close} onDismissed={dismissNow}
          onChanged={() => { onChange(); void refreshThreads() }}
          onTell={tellRabbit}
          onUploadPlan={() => tellRabbit("Here's my updated training plan.")} />
      )}
      {sheet === 'plan' && goal && (
        <PlanSheet goal={goal} week={week} closing={closing} onClose={close} onDismissed={dismissNow}
          onAsk={() => tellRabbit('About my plan: ')}
          onUploadPlan={() => tellRabbit("Here's my updated training plan.")}
          onEdit={() => open('memory')} onBuild={startSetup} />
      )}
      {addPlan && <AddPlanLauncher onClose={() => setAddPlan(false)} onApplied={() => { setAddPlan(false); onChange(); void refreshThreads(); loadWeek() }} />}
      {meOpen && <MePage me={me} goal={goal} progress={progress} onOpen={openMeRow} onClose={() => setMeOpen(false)} />}
      {planScreen === 'setup' && (
        <SetupWizard me={{ ...me, goal }} onClose={() => setPlanScreen(null)}
          onDone={() => { onChange(); void refreshThreads(); loadWeek(); celebrate(null, 'plan') }}
          onOpenPlan={openPlan}
          onUploadPlan={() => { setPlanScreen(null); setAddPlan(true) }}
          onMeChanged={onChange} />
      )}
      {planScreen === 'coach' && (
        <CoachInbox openThreadId={coachMsgThread} onClose={() => setPlanScreen(null)} onChanged={onChange} />
      )}
      {planScreen === 'coaches' && <CoachesScreen onClose={() => setPlanScreen(null)} onChanged={onChange} onFindCoach={() => setPlanScreen('findcoach')} />}
      {planScreen === 'findcoach' && (
        <FindCoachScreen athleteName={me.profile.name} onClose={() => setPlanScreen(null)} onAsk={tellRabbit} onInvited={onChange} />
      )}
      {coachAsk && (
        <CoachStatusSheet current={me.athlete.coach_status} onClose={() => setCoachAsk(false)}
          onSaved={(s) => {
            setCoachAsk(false); onChange(); getProgress().then(setProgress, () => {})
            if (s === 'looking') showScreen('findcoach')
            else if (s === 'have_coach') showScreen('coaches')
            else showToast('Going solo. Rabbit has your back.')
          }} />
      )}
      {planScreen === 'athletes' && <CoachApp me={me} onClose={() => setPlanScreen(null)} />}
      {fitEvent && <RaceFitScreen eventId={fitEvent} onClose={() => setFitEvent(null)} />}
      {planScreen === 'racepack' && <RacePackScreen imperial={imperial} onClose={() => setPlanScreen(null)} />}
      {workout && (
        <WorkoutDayScreen key={workout.sessionId ?? 'today'} sessionId={workout.sessionId} imperial={imperial}
          onClose={() => setWorkout(null)} onAsk={(t) => { setWorkout(null); tellRabbit(t) }} onCheckIn={(c) => setVoice(c)} />
      )}
      {reaction != null && (
        <ReactionCard key={reaction} activityId={reaction} imperial={imperial}
          onClose={() => setReaction(null)} onOpenSession={(id) => setWorkout({ sessionId: id })}
          onCheckIn={(c) => { setReaction(null); setVoice(c) }} />
      )}
      {planScreen === 'gear' && <GearScreen imperial={imperial} onClose={() => setPlanScreen(null)} onAsk={tellRabbit} />}
      {planScreen === 'quests' && progress && (
        <SetupScreen p={progress} onClose={() => setPlanScreen((sc) => (sc === 'quests' ? null : sc))} onAction={doQuest} />
      )}
      {progress && overlayFree && <Celebration key={progress.xp} p={progress} onDone={() => setProgress((p) => p && { ...p, level_up: false, new_badges: [] })} />}
      {planScreen === 'profile' && (
        <ProfileScreen me={me} hasBuiltPlan={builtPlan} onClose={() => setPlanScreen(null)}
          onSaved={onChange} onRebuild={() => setPlanScreen('setup')} onOpenEvents={openRaces} onOpenGear={() => setPlanScreen('gear')} />
      )}
      {sheet === 'settings' && (
        <div className={`modal-overlay ${closing ? 'modal-overlay--exit' : ''}`} onClick={close}>
          <div className={`modal ${closing ? 'modal--exit' : ''}`} onClick={(e) => e.stopPropagation()} {...settingsDrag}>
            <div className="sheet-handle" />
            <div className="modal-header">
              <h2 className="modal-title">Settings</h2>
              <button className="modal-close" aria-label="Close" onClick={close}><X className="size-4" /></button>
            </div>
            <div className="modal-body overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
              <SettingsPanels me={me} onChange={onChange} onDevDone={() => void reload()} onToast={showToast} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
