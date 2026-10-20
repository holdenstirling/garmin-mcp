import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ASK_EVENT } from '@/lib/askrabbt'
import { smooth } from '@/lib/scrollMotion'
import { requestPlanFix } from '@/lib/plancal'
import { Bell, ChevronLeft, ChevronRight, FileText, History, MessageCircle, MessagesSquare, Plus, Upload } from 'lucide-react'
import { AddSheet } from '@/components/nav/AddSheet'
import { useEdgeSwipe } from '@/hooks/useEdgeSwipe'
import { Avatar } from '@/components/Avatar'
import { photoUrl } from '@/lib/photo'
import { ConversationScreen, NewMessageSheet, AccessScreen, AddPlanLauncher, CoachApp, CoachInbox, CoachStatusSheet, CoachesScreen, CommunityScreen, ConnectSheet, ConnectionsScreen, EventsScreen, ExploreScreen, FindCoachScreen, GearScreen, MePage, MemorySheet, PlanEditor, PlanSheet, ProfileScreen, RaceFitScreen, RacePackScreen, RaceWeekScreen, RecapSheet, ActivityScreen, RaceChecklistScreen, ConvertPlanScreen, SettingsPanels, SetupWizard, StatsScreen, ThreadsSheet, WorkoutDayScreen } from '@/screens/lazyScreens'
import { planLine } from '@/components/chat/PlanPins'
import { PageStack, Screen, TabScreen } from '@/components/plan/ui'
import { Sheet as BottomSheet } from '@/components/ui/Sheet'
import type { ConnApp, ConnectRequest } from '@/lib/connections'
import { TPPlanSection } from '@/components/plan/TPItems'
import type { CommunityView } from '@/components/community/CommunityScreen'
import { Celebration, SetupScreen } from '@/components/progress/Progress'
import { getProgress, nextQuest, type Progress, type QuestId } from '@/lib/progress'
import { athleteChat, getCoaches } from '@/lib/coach'
import { daysUntil } from '@/lib/events'
import { dismissDraft, shareDraft } from '@/lib/community'
import { UpNextCard, UpNextSkeleton } from '@/components/home/UpNextCard'
import { WeekPanel } from '@/components/home/WeekPanel'
import { NextDays } from '@/components/home/NextDays'
import { HomeGreeting } from '@/components/home/HomeGlance'
import { Section, SeeAll } from '@/components/ui/section'
import { ReadinessSnapshot } from '@/components/home/ReadinessSnapshot'
import { FitnessCountdown } from '@/components/home/FitnessCountdown'
import { OPEN_PLAN_DAY_EVENT, PLAN_VIEW_KEY, openPlanDay } from '@/lib/plancal'
import { OPEN_EVENT_EVENT } from '@/lib/events'
import { OPEN_TRAVEL_EVENT, openTravel } from '@/lib/plantools'
import { openSick } from '@/lib/sick'
import { SickBanner, SickHost } from '@/components/plan/SickHost'
import { OPEN_WORKOUT_EVENT, type OpenWorkout } from '@/lib/workoutnav'
import { OPEN_ACTIVITY_EVENT, type OpenActivity } from '@/lib/activitynav'
import { OPEN_CHECKLIST_EVENT } from '@/lib/racechecklist'
import { RaceChecklistCard } from '@/components/home/RaceChecklistCard'
import { DM_CHANGED_EVENT, NEW_DM_EVENT, OPEN_DM_EVENT, dmUnread as getDmUnread, type DMShare } from '@/lib/dm'
import { CONVERT_PLAN_EVENT, startPlanConversion } from '@/lib/planconvert'
import { OPEN_PLACE_EVENT, TAB_SHOWN_EVENT, type Place } from '@/lib/nav'
import { RaceWeekCard } from '@/components/raceweek/RaceWeekCard'
import { QuickActions, SharePrompt } from '@/components/home/QuickActions'
import { FriendsLatest } from '@/components/home/FriendsLatest'
import { GetStartedCard } from '@/components/home/GetStartedCard'
import { startBadgeSync } from '@/lib/unread'
import { FirstVisitCard, firstVisitHidden } from '@/components/home/FirstVisitCard'
import { CONNECT_GARMIN_EVENT, getUpNext, type UpNext } from '@/lib/upnext'
import { useTopInsight } from '@/lib/insights'
import { localDay, shiftWeek, syncNow, type Today, type TodayActionKind } from '@/lib/live'
import { markReactionShown, reactionShown } from '@/lib/workout'
import { MonthRecapSheet, NotificationsSheet, PartnersScreen, PersonScreen, RewardSheet, UsageScreen } from '@/screens/lazyScreens'
import { NOTIFS_CHANGED_EVENT, OPEN_PERSON_EVENT, OPEN_TARGET_EVENT, getNotifications, type DeepKind, type NotifOpen } from '@/lib/people'
import { RaceSwitcher } from '@/components/plan/PlanFlow'
import { CelebrationHost } from '@/components/reward/CelebrationHost'
import { BodyHost } from '@/components/body/BodyHost'
import { NiggleNudge } from '@/components/home/NiggleNudge'
import { CalendarNudge } from '@/components/home/CalendarNudge'
import { MonthRecapEntry } from '@/components/reward/MonthRecapEntry'
import { getReward, lastMonth, type Reward } from '@/lib/reward'
import { RabbitLogo } from '@/components/RabbitLogo'
import { RabbitLoader } from '@/components/RabbitLoader'
import { setCurrentSources } from '@/lib/sources'
import { Group, Icon, Row as SettingsRow } from '@/components/settings/Grouped'
import { WeekList } from '@/components/week/WeekStrip'
import { TAB_IDS, TabBar, readTab, saveTab, useSocialBadge, type TabId } from '@/components/nav/TabBar'
import { useTabSwipe } from '@/hooks/useTabSwipe'
import { setUsageOff, track, trackAppOpen } from '@/lib/usage'
import { PullToRefresh, celebrate, reducedMotion, signalReplyDone } from '@/components/fx'
import { Segmented } from '@/components/nav/Segmented'
import type { MeRow } from '@/components/nav/MePage'
import type { LegalSlug } from '@/lib/legal'
import { DocScreen, PostScreen, PrivacyLegalScreen } from '@/screens/lazyScreens'
import { StatusBanner, type Banner } from '@/components/nav/StatusBanner'
import { CoachHeader, DiscussButton, ThreadLinkCard } from '@/components/chat/CoachCards'
import { ATTACH_INPUT_ID, Composer } from '@/components/chat/Composer'
import type { AttachmentMeta } from '@/lib/attachments'
import { MessageBubble } from '@/components/chat/MessageBubble'
import { ToolCallCard, ToolCallGroup } from '@/components/chat/ToolCallCard'
import { Button } from '@/components/ui/button'
import {
  createThread, deleteThread, getPlanWeek, listThreads, putSettings,
  type Goal, type Me, type PlannedSession, type PlanWeek, type Thread, type WeekDay,
} from '@/lib/api'
import { useCoach, type QueuedSend, type ChartItem, type Approval, type ChatItem, type ChatMessage, type MomentAction, type MomentItem, type ThreadLink, type ToolCall } from '@/hooks/useCoach'
import { MomentCard } from '@/components/chat/MomentCard'
import { ReplyChips, replyChips, useRotatingPrompt } from '@/components/chat/ReplyChips'
import { ApprovalCard } from '@/components/chat/ApprovalCard'
import { Chart, VoiceCheckIn } from '@/screens/lazyScreens'
import type { MenuTarget } from '@/components/chat/MessageMenu'
import { MessageMenu, ReactionCard, ThreadPeek } from '@/screens/lazyScreens'
import { EmptyHero } from '@/components/chat/EmptyHero'
import { useLongPress } from '@/hooks/useLongPress'
import { hapticTap } from '@/lib/haptics'
import { WelcomeGate } from '@/components/onboarding/WelcomeFlow'
import { IntentStrip, stripFirst } from '@/components/onboarding/IntentHome'
import { composerPrompts, intentSuggestions, intentsOf, wantsPlan } from '@/lib/intent'
import { BlockScreen } from '@/screens/lazyScreens'
import { FindFriendsScreen } from '@/screens/lazyScreens'
import { OPEN_FRIENDS_EVENT, type FriendsOpen } from '@/lib/friends'
import { BlocksEntry } from '@/components/blocks/BlocksEntry'
import { OPEN_BLOCK_EVENT, blockMomentAction } from '@/lib/blocks'
import { PaceHost } from '@/components/paces/PaceSheet'
import { dismissPace, openPaceSuggestion } from '@/lib/paces'
import { SearchButton } from '@/components/search/Search'
import { Tour } from '@/components/onboarding/Tour'
import { SEARCH_OPEN_EVENT, type SearchPick } from '@/lib/search'
import { cn } from '@/lib/utils'
import { HomeStart } from '@/components/home/HomeStart'
import { NearTonight } from '@/components/home/NearTonight'
import { NEW_EVENT_EVENT } from '@/lib/events'
import { HowItWorksHost, openHowItWorks } from '@/components/onboarding/HowItWorks'
import { CircleQuestionMark } from 'lucide-react'
import { CALENDAR_KINDS, requestPostRun } from '@/lib/events'
import { NewEventSheet } from '@/screens/lazyScreens'

const COACH_SUGGESTIONS = [
  'How did my training go this week?',
  'Am I recovered enough for a hard workout today?',
  "How's my sleep been lately?",
]
const TOPIC_SUGGESTIONS = ['Find me a run club this week.', 'Build me a plan for a 10K.', 'What should I eat before a long run?']

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
// Full-screen pages over the tabs: plan setup, profile, people, gear.
type PlanScreen = 'setup' | 'profile' | 'coach' | 'coaches' | 'athletes' | 'racepack' | 'quests' | 'gear' | 'findcoach'
// Pages over the tabs are ONE stack and only its top page is drawn (nothing piles up): a page
// opened from a page is pushed (back arrow to the previous one + X), a top-level destination
// (the avatar, Up next, a moment, a notification) replaces the stack, a tab switch clears it.
// Phone Back / Escape pop one level (Screen + lib/overlays); X closes the whole stack.
type Page = { k: 'me' } | { k: 'screen'; s: PlanScreen } | { k: 'fit'; id: string } | { k: 'workout'; sessionId?: string } | { k: 'activity'; id: string } | { k: 'checklist'; id: string }
  | { k: 'dm'; id: string } | { k: 'connections' } | { k: 'access' } | { k: 'usage' } | { k: 'partners' } | { k: 'legal'; doc?: LegalSlug } | { k: 'raceweek'; id: string; section?: string } | { k: 'block'; id: string }
  | { k: 'person'; id: string } | { k: 'friends'; section?: 'me'; add?: string; q?: string } | { k: 'post'; id: string; comment?: string }
const pageKey = (p: Page) => p.k === 'block' ? `block:${p.id}` : p.k === 'screen' ? p.s : p.k === 'workout' ? `workout:${p.sessionId ?? ''}` : p.k === 'activity' ? `activity:${p.id}` : p.k === 'checklist' ? `checklist:${p.id}` : p.k === 'dm' ? `dm:${p.id}` : p.k === 'fit' ? `fit:${p.id}` : p.k === 'raceweek' ? `raceweek:${p.id}` : p.k === 'person' ? `person:${p.id}` : p.k === 'friends' ? `friends:${p.add ?? ''}` : p.k === 'post' ? `post:${p.id}:${p.comment ?? ''}` : p.k === 'legal' ? `legal:${p.doc ?? ''}` : p.k
type ProgressView = 'overview' | 'recap'
// Schedule tab: the plan calendar, your events, or finding races and events nearby.
type ScheduleView = 'plan' | 'events' | 'discover'
/** Schedule "+ Add" / an event tapped on the calendar: open the event editor (new, or that event). */
type EventRequest = { add?: boolean; open?: string; n: number }
const localToday = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }

// Touch devices: focusing the composer means the keyboard is coming, so make room for it.
const coarsePointer = () => { try { return window.matchMedia('(pointer: coarse)').matches } catch { return false } }

const HEADER_ICON = 'relative flex size-11 shrink-0 items-center justify-center rounded-full text-(--text-secondary) active:bg-(--bg-inset)'


/** The header's goal line: "Boulder 70.3 · 33 weeks to go" (two facts, not three). */
function goalLeft(goal: { date?: string | null }): string {
  if (!goal.date) return ''
  const days = daysUntil(goal.date)
  if (days < 0) return 'done'
  if (days <= 7) return days === 0 ? 'race day' : 'race week'
  const weeks = Math.floor(days / 7)
  return `${weeks} ${weeks === 1 ? 'week' : 'weeks'} to go`
}

/** Home's nudges, most important first (one shows under the hero, the rest in More for you). */
type HomeNudge = 'notes' | 'banner' | 'niggle' | 'calendar' | 'next'

export function Chat({ me, onChange }: { me: Me; onChange: () => void }) {
  const [threads, setThreads] = useState<Thread[]>([])
  const [goal, setGoal] = useState<Goal | null>(me.goal)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [queued, setQueued] = useState<QueuedSend | null>(null)
  // A new chat is a client-side draft until its first message is sent (then it's created).
  const [pending, setPending] = useState<{ seed?: { thread_id: string; turn_id: string }; seedMsg?: ChatMessage } | null>(null)
  const { items, ready, status, send, stop, decide, reload, loadError, retry } =
    useCoach(threadId, { turn: me.chat.active_turn, thread: me.chat.active_thread }, queued, () => setQueued(null))
  const [sheet, setSheet] = useState<Sheet | null>(null)
  const [closing, setClosing] = useState(false)
  const [pages, setPages] = useState<Page[]>([])
  const [revealed, setRevealed] = useState(false) // the top page came back from a pop: no slide-in
  const topPage = pages[pages.length - 1] ?? null
  const meOpen = topPage?.k === 'me'
  // At most one sheet: opening a page closes the sheet that opened it first.
  const dropSheet = () => { setSheet(null); setClosing(false); setCoachAsk(false) }
  const pushPage = (pg: Page) => {
    dropSheet(); setRevealed(false)
    setPages((st) => {
      const i = st.findIndex((x) => pageKey(x) === pageKey(pg))
      return i >= 0 ? [...st.slice(0, i), pg] : [...st, pg]
    })
  }
  const showPage = (pg: Page) => { dropSheet(); setRevealed(false); setPages([pg]) }
  // Back slides the page away first (170 ms; instant under reduced motion), then reveals the one under it.
  const [leaving, setLeaving] = useState(false)
  const popPage = () => {
    const done = () => { setLeaving(false); setRevealed(true); setPages((st) => st.slice(0, -1)) }
    if (reducedMotion() || leaving) { done(); return }
    setLeaving(true)
    window.setTimeout(done, 170)
  }
  const closePages = () => setPages([])
  // The one connect popup (components/connect/ConnectSheet): any screen via requestConnect(app).
  const [connect, setConnect] = useState<ConnectRequest | null>(null)
  const [addPlan, setAddPlan] = useState(false)
  // A plan file -> full Rabbit workouts (lib/planconvert): read, review, apply.
  const [converting, setConverting] = useState(false)
  // Direct messages (lib/dm): the Chats sheet's People view, unread total for the header dot,
  // and New message / Send to a friend.
  const [chatsView, setChatsView] = useState<'rabbit' | 'people'>('rabbit')
  const [dmCount, setDmCount] = useState(0)
  // Notifications (lib/people): the bell's unread dot and its inbox sheet.
  const [notifCount, setNotifCount] = useState(0)
  const [notifsOpen, setNotifsOpen] = useState(false)
  const [newDm, setNewDm] = useState<{ to?: string[]; share?: DMShare } | null>(null)
  const [coachMsgThread, setCoachMsgThread] = useState<string | null>(null)
  const [coachAsk, setCoachAsk] = useState(false) // "Do you want a coach?" sheet
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<{ text: string; n: number } | null>(null)
  const [menu, setMenu] = useState<MenuTarget | null>(null)
  const [peek, setPeek] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; n: number } | null>(null)
  const [voice, setVoice] = useState<{ sessionId?: string; activityId?: number; title?: string } | null>(null)
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
    : openParam === 'community' ? 'feed' : readTab())
  const setTab = useCallback((t: TabId) => { setTabState(t); saveTab(t) }, [])
  // Tabs stay mounted once visited (hidden when not shown): switching back is instant, with no
  // refetch flash and the scroll position kept.
  const [visited, setVisited] = useState<ReadonlySet<TabId>>(() => new Set([tab]))
  useEffect(() => {
    setVisited((v) => (v.has(tab) ? v : new Set(v).add(tab)))
    try { window.dispatchEvent(new CustomEvent(TAB_SHOWN_EVENT, { detail: tab })) } catch { /* ignore */ }
  }, [tab])
  const tabCls = (t: TabId) => `tab-page min-h-0 flex-1 flex-col ${tab === t ? 'flex' : 'hidden'}`
  const [progressView, setProgressView] = useState<ProgressView>(openParam === 'recap' ? 'recap' : 'overview')
  const [recapWeek, setRecapWeek] = useState<string | undefined>(undefined)
  // A tab stored before the split as 'races' (Events) opens Schedule on Events.
  const [schedView, setSchedView] = useState<ScheduleView>(() => { try { return sessionStorage.getItem('rabbit.tab') === 'races' ? 'events' : 'plan' } catch { return 'plan' } })
  // Schedule "+ Add": the add sheet, and requests handed to the plan / events pages.
  const [addOpen, setAddOpen] = useState(false)
  const [calendarAdd, setCalendarAdd] = useState(false) // Plan + Add -> Add to my calendar (race, trip, big day)
  const [addWorkout, setAddWorkout] = useState<{ date: string; n: number } | null>(null)
  const [eventReq, setEventReq] = useState<EventRequest | null>(null)
  const [communityView, setCommunityView] = useState<CommunityView>('feed')
  const [communityClub, setCommunityClub] = useState<string | null>(null)
  const [friendsLatest, setFriendsLatest] = useState(false)
  const [shareAsk, setShareAsk] = useState(false)  // Home: the share-workouts question is showing
  // Home nudges that load themselves: whether each is up (Home shows one at a time).
  const [homeNudges, setHomeNudges] = useState<{ niggle: boolean; calendar: boolean }>({ niggle: false, calendar: false })
  const setHomeNudge = useCallback((k: 'niggle' | 'calendar', v: boolean) => setHomeNudges((n) => (n[k] === v ? n : { ...n, [k]: v })), [])
  const [composerFocus, setComposerFocus] = useState(false)
  // Rabbit tab: Home (dashboard) or Chat (Rabbit's log + composer); kept for this browser session.
  const [homeView, setHomeViewState] = useState<'home' | 'chat'>(() => {
    if (openParam === 'coach') return 'chat'
    try { return sessionStorage.getItem('rabbit.home.view') === 'chat' ? 'chat' : 'home' } catch { return 'home' }
  })
  const setHomeView = useCallback((v: 'home' | 'chat') => {
    setHomeViewState(v)
    try { sessionStorage.setItem('rabbit.home.view', v) } catch { /* this render only */ }
  }, [])
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
  }, [threadId, pending, items.length === 0, homeView])

  // An approval is waiting on you: bring it into view.
  const pendingCount = items.filter((it) => it.kind === 'approval' && it.status === 'pending').length
  useEffect(() => {
    if (pendingCount) feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: smooth() })
  }, [pendingCount])

  // Stick to the bottom while streaming, unless the user scrolled up to read.
  useEffect(() => {
    const el = feed.current
    if (!el) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 150 || status !== 'streaming') {
      el.scrollTo({ top: el.scrollHeight, behavior: status === 'streaming' ? 'instant' : smooth() })
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
    closePages()
    setTab('rabbit')
    setHomeView('chat')
  }
  // "Ask why" buttons deep in a screen (lib/askrabbt) prefill the chat the same way.
  const tellRef = useRef(tellRabbit)
  tellRef.current = tellRabbit
  useEffect(() => {
    const on = (e: Event) => tellRef.current(String((e as CustomEvent<string>).detail ?? ''))
    window.addEventListener(ASK_EVENT, on)
    return () => window.removeEventListener(ASK_EVENT, on)
  }, [])
  const builtPlan = goal?.plan_source === 'builder'
  const showScreen = (sc: PlanScreen) => pushPage({ k: 'screen', s: sc })
  const startSetup = () => showScreen('setup')
  // A tab, with whatever was open on top of it closed.
  const goTab = (t: TabId) => {
    if (sheet) { setSheet(null); setClosing(false) }
    closePages()
    setTab(t)
  }
  const openPlan = () => { setSchedView('plan'); goTab('plan') }
  const newEvent = () => { closePages(); setSchedView('events'); setEventReq((r) => ({ add: true, n: (r?.n ?? 0) + 1 })); goTab('plan') }
  useEffect(() => {
    window.addEventListener(NEW_EVENT_EVENT, newEvent)
    return () => window.removeEventListener(NEW_EVENT_EVENT, newEvent)
  })
  const openRaces = () => { setSchedView('events'); goTab('plan') }
  const openDiscover = () => { setSchedView('discover'); goTab('plan') }
  const openEvent = (id: string) => { setSchedView('events'); setEventReq((r) => ({ open: id, n: (r?.n ?? 0) + 1 })); goTab('plan') }
  const openProgress = () => { setProgressView('overview'); goTab('progress') }
  const openRecap = (week?: string) => { setRecapWeek(week); setProgressView('recap'); goTab('progress') }
  const openCommunity = (v: CommunityView = 'feed', club?: string) => {
    // Feed is its own tab; clubs and people share the Local tab (id 'clubs').
    if (v === 'feed') { goTab('feed'); return }
    setCommunityView(v); setCommunityClub(club ?? null); goTab('clubs')
  }
  // Nothing open over the tabs: progress, Today and live sync refresh.
  const overlayFree = !pages.some((p) => p.k === 'screen') && !sheet && !connect
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
  // Up next (upnext.py) wraps the Today card: one fetch for both.
  const [upnext, setUpNext] = useState<UpNext | null>(null)
  const [upnextTried, setUpNextTried] = useState(false) // first load done (skeleton until then)
  const loadToday = useCallback(() => { getUpNext().then((u) => { setUpNext(u); setToday(u.today) }, () => {}).finally(() => setUpNextTried(true)) }, [])
  useEffect(() => {
    // GarminEmpty, setup quests, any screen: that app's connect popup (lib/connections).
    const onConnect = (e: Event) => setConnect({ app: ((e as CustomEvent<ConnApp | undefined>).detail) ?? 'garmin' })
    window.addEventListener(CONNECT_GARMIN_EVENT, onConnect)
    return () => window.removeEventListener(CONNECT_GARMIN_EVENT, onConnect)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // Shared training blocks (lib/blocks openBlock): Plan, Community, a moment -> the block page.
    const onBlock = (e: Event) => showPage({ k: 'block', id: (e as CustomEvent<string>).detail || 'new' })
    window.addEventListener(OPEN_BLOCK_EVENT, onBlock)
    return () => window.removeEventListener(OPEN_BLOCK_EVENT, onBlock)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // Home's week, a moment, any screen (lib/plancal openPlanDay): the Plan tab on that day.
    const onDay = () => { setSheet(null); setClosing(false); closePages(); setSchedView('plan'); setTab('plan') }
    window.addEventListener(OPEN_PLAN_DAY_EVENT, onDay)
    return () => window.removeEventListener(OPEN_PLAN_DAY_EVENT, onDay)
  }, [setTab])
  useEffect(() => {
    // lib/nav openPlace: any component can send people somewhere (e.g. New group -> find friends).
    const onPlace = (e: Event) => {
      const p = (e as CustomEvent<Place>).detail
      setSheet(null); setClosing(false)
      if (p === 'people' || p === 'clubs' || p === 'feed') openCommunity(p)
      else if (p === 'events') openRaces()
      else if (p === 'plan') openPlan()
      else if (p === 'progress') goTab('progress')
      else if (p === 'connections') pushPage({ k: 'connections' })
    }
    window.addEventListener(OPEN_PLACE_EVENT, onPlace)
    return () => window.removeEventListener(OPEN_PLACE_EVENT, onPlace)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // lib/plantools openTravel (Add sheet, Adjust my plan, anywhere): Schedule > Plan, where
    // PlanEditor opens travel mode (it also reads the pending request when it mounts).
    const onTravel = () => { setSheet(null); setClosing(false); closePages(); setSchedView('plan'); setTab('plan') }
    window.addEventListener(OPEN_TRAVEL_EVENT, onTravel)
    return () => window.removeEventListener(OPEN_TRAVEL_EVENT, onTravel)
  }, [setTab])
  useEffect(() => {
    // lib/events openEvent (a plan day's "From your events", search): Schedule > Events, where
    // EventsScreen opens that event (it reads the stored id on mount and listens while shown).
    const onEvent = () => { setSheet(null); setClosing(false); closePages(); setSchedView('events'); setTab('plan') }
    window.addEventListener(OPEN_EVENT_EVENT, onEvent)
    return () => window.removeEventListener(OPEN_EVENT_EVENT, onEvent)
  }, [setTab])
  useEffect(() => {
    // lib/workoutnav openWorkout (Home's week, Up next, Schedule views): the full workout page.
    const onWorkout = (e: Event) => { const id = (e as CustomEvent<OpenWorkout>).detail?.id; if (id) { setSheet(null); setClosing(false); setWorkout({ sessionId: id }) } }
    window.addEventListener(OPEN_WORKOUT_EVENT, onWorkout)
    return () => window.removeEventListener(OPEN_WORKOUT_EVENT, onWorkout)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // lib/activitynav openActivity (Home's week, Schedule, Feed, Progress, search): a recorded
    // workout's page. From a planned workout's page it stacks on top (Back returns there).
    const onActivity = (e: Event) => {
      const id = (e as CustomEvent<OpenActivity>).detail?.id
      if (!id) return
      dropSheet(); setRevealed(false)
      setPages((st) => st[st.length - 1]?.k === 'workout' ? [...st, { k: 'activity', id }] : [{ k: 'activity', id }])
    }
    window.addEventListener(OPEN_ACTIVITY_EVENT, onActivity)
    return () => window.removeEventListener(OPEN_ACTIVITY_EVENT, onActivity)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // lib/racechecklist openChecklist (event page, race cards, race pack, race week, Home): the
    // race checklist page; from another page (race pack, race week) it stacks (Back returns).
    const onChecklist = (e: Event) => {
      const id = (e as CustomEvent<string>).detail
      if (!id) return
      dropSheet(); setRevealed(false)
      setPages((st) => st.length ? [...st, { k: 'checklist', id }] : [{ k: 'checklist', id }])
    }
    window.addEventListener(OPEN_CHECKLIST_EVENT, onChecklist)
    return () => window.removeEventListener(OPEN_CHECKLIST_EVENT, onChecklist)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // Direct messages: open a chat (lib/dm openConversation, a push, a shared card) or start one.
    const onOpen = (e: Event) => {
      const id = (e as CustomEvent<{ id?: string }>).detail?.id
      if (!id) return
      dropSheet(); setRevealed(false); setNewDm(null)
      setPages((st) => (st.length && st[st.length - 1]?.k !== 'me' ? [...st, { k: 'dm', id }] : [{ k: 'dm', id }]))
    }
    const onNew = (e: Event) => setNewDm((e as CustomEvent<{ to?: string[]; share?: DMShare }>).detail ?? {})
    window.addEventListener(OPEN_DM_EVENT, onOpen)
    window.addEventListener(NEW_DM_EVENT, onNew)
    return () => { window.removeEventListener(OPEN_DM_EVENT, onOpen); window.removeEventListener(NEW_DM_EVENT, onNew) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (me.role !== 'athlete') return
    let live = true
    const check = () => { getDmUnread().then((r) => { if (live) setDmCount(r.unread) }, () => {}) }
    check()
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') check() }, 60_000)
    const onVis = () => { if (document.visibilityState === 'visible') check() }
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener(DM_CHANGED_EVENT, check)
    // ?open=dm&c=<id> (a message push), or the push tapped while the app is open.
    const c = new URLSearchParams(window.location.search)
    if (c.get('open') === 'dm' && c.get('c')) window.setTimeout(() => setPages([{ k: 'dm', id: c.get('c')! }]), 0)
    const onSw = (e: MessageEvent) => {
      const url = String(e.data?.url ?? '')
      if (e.data?.type !== 'open' || !url.includes('open=dm')) return
      const id = new URL(url, window.location.origin).searchParams.get('c')
      if (id) setPages([{ k: 'dm', id }])
    }
    navigator.serviceWorker?.addEventListener('message', onSw)
    return () => {
      live = false; window.clearInterval(t)
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener(DM_CHANGED_EVENT, check)
      navigator.serviceWorker?.removeEventListener('message', onSw)
    }
  }, [me.role])
  useEffect(() => {
    const onConvert = () => { dropSheet(); closePages(); setConverting(true) }
    window.addEventListener(CONVERT_PLAN_EVENT, onConvert)
    return () => window.removeEventListener(CONVERT_PLAN_EVENT, onConvert)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // Search everywhere (components/search): a picked result -> its tab or page.
    const onPick = (e: Event) => {
      const p = (e as CustomEvent<SearchPick>).detail
      if (p.kind === 'person') { dropSheet(); setRevealed(false); setPages((st) => [...st.filter((x) => x.k !== 'person'), { k: 'person', id: p.id }]) }
      else if (p.kind === 'club') openCommunity('clubs', p.source === 'club' ? p.id : undefined)
      else if (p.kind === 'event') openRaces()
      else if (p.kind === 'session') { setSchedView('plan'); goTab('plan') }
      else { dropSheet(); setRevealed(false); setPages([{ k: 'activity', id: String(p.id) }]) } // a past workout: its full page
    }
    window.addEventListener(SEARCH_OPEN_EVENT, onPick)
    return () => window.removeEventListener(SEARCH_OPEN_EVENT, onPick)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // Connected screens (lib/people). A person's profile stacks on whatever page is open, so Back
  // returns there (the same person again moves to the top instead of stacking twice).
  const openPersonPage = (id: string) => {
    if (!id) return
    if (id === me.user_id) { showPage({ k: 'me' }); return }
    pushPage({ k: 'person', id })
  }
  // Any "open this item" target (a notification, a Related row, a card): its exact page or tab.
  const openTargetNow = (t: NotifOpen) => {
    dropSheet(); setNotifsOpen(false)
    switch (t.k) {
      case 'dm': setRevealed(false); setPages((st) => (st.length && st[st.length - 1]?.k !== 'me' ? [...st, { k: 'dm', id: t.id }] : [{ k: 'dm', id: t.id }])); break
      case 'person': openPersonPage(t.id); break
      case 'activity': setRevealed(false); setPages((st) => st.length ? [...st, { k: 'activity', id: t.id }] : [{ k: 'activity', id: t.id }]); break
      case 'checklist': pushPage({ k: 'checklist', id: t.id }); break
      case 'post': setRevealed(false); setPages((st) => st.length ? [...st, { k: 'post', id: t.id, comment: t.comment }] : [{ k: 'post', id: t.id, comment: t.comment }]); break
      case 'people': closePages(); openCommunity('people'); break
      case 'feed': closePages(); openCommunity('feed'); break
      case 'club': closePages(); openCommunity('clubs', t.id); break
    }
  }
  // Deep links (lib/people deepLink): /app/?open=<kind>&id=<id>[&date=], from a pasted or shared
  // link, a push tap, or an in-app link inside a message.
  const openDeep = (kind: DeepKind, id: string, date: string | null) => {
    if (kind === 'workout') { if (id) { dropSheet(); setWorkout({ sessionId: id }) } else if (date) openPlanDay(date) }
    else if (kind === 'event') { if (id) { dropSheet(); closePages(); openEvent(id) } }
    else if (kind === 'activity' || kind === 'person' || kind === 'checklist') { if (id) openTargetNow({ k: kind, id }) }
    else if (kind === 'club') { if (id) openTargetNow({ k: 'club', id }) }
    // A post (an @mention push): the third value is the comment to jump to.
    else if (kind === 'post') { if (id) openTargetNow({ k: 'post', id, comment: date ?? undefined }) }
  }
  const DEEP = useRef<ReadonlySet<string>>(new Set(['workout', 'activity', 'event', 'club', 'person', 'checklist', 'post'])).current
  const deepFrom = (url: string): [DeepKind, string, string | null] | null => {
    try {
      const u = new URL(url, window.location.origin)
      if (u.origin !== window.location.origin || !u.pathname.startsWith('/app')) return null
      const k = u.searchParams.get('open') ?? ''
      if (!DEEP.has(k)) return null
      const id = (u.searchParams.get('id') ?? '').slice(0, 120)
      if (k === 'post') { const c = u.searchParams.get('c'); return ['post', id, c && /^c[0-9a-f]{6,24}$/.test(c) ? c : null] }
      const date = u.searchParams.get('date')
      return [k as DeepKind, id, date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null]
    } catch { return null }
  }
  useEffect(() => {
    if (me.role !== 'athlete') return
    const onPerson = (e: Event) => openPersonPage(String((e as CustomEvent<string>).detail ?? ''))
    const onTarget = (e: Event) => { const t = (e as CustomEvent<NotifOpen>).detail; if (t?.k) openTargetNow(t) }
    const onFriends = (e: Event) => { const d = (e as CustomEvent<FriendsOpen>).detail ?? {}; pushPage({ k: 'friends', section: d.section, add: d.add, q: d.q }) }
    window.addEventListener(OPEN_FRIENDS_EVENT, onFriends)
    // A friend's QR code or follow link (/app/?add=CODE): open Find friends with them on top.
    try {
      const add = new URL(window.location.href).searchParams.get('add') ?? ''
      if (/^[A-Z2-9]{8}$/.test(add)) { window.history.replaceState(null, '', '/app/'); window.setTimeout(() => pushPage({ k: 'friends', add }), 0) }
    } catch { /* no URL support */ }
    window.addEventListener(OPEN_PERSON_EVENT, onPerson)
    window.addEventListener(OPEN_TARGET_EVENT, onTarget)
    // On load: ?open=<kind>&id=..; then the address is cleaned so a reload doesn't reopen it.
    const first = deepFrom(window.location.href)
    if (first) { window.history.replaceState(null, '', '/app/'); window.setTimeout(() => openDeep(...first), 0) }
    // A push tapped while the app is open (the service worker posts its url).
    const onSw = (e: MessageEvent) => {
      if (e.data?.type !== 'open') return
      const d = deepFrom(String(e.data?.url ?? ''))
      if (d) openDeep(...d)
    }
    // An in-app link in a message or a note: open it here instead of reloading the app.
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      const a = (e.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
      if (!a || (a.target && a.target !== '_self')) return
      const d = deepFrom(a.href)
      if (!d) return
      e.preventDefault()
      openDeep(...d)
    }
    navigator.serviceWorker?.addEventListener('message', onSw)
    document.addEventListener('click', onClick)
    return () => {
      window.removeEventListener(OPEN_PERSON_EVENT, onPerson)
      window.removeEventListener(OPEN_FRIENDS_EVENT, onFriends)
      window.removeEventListener(OPEN_TARGET_EVENT, onTarget)
      navigator.serviceWorker?.removeEventListener('message', onSw)
      document.removeEventListener('click', onClick)
    }
  }, [me.role]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // The bell's dot: unread notifications, checked on open, every minute while visible, and
    // whenever something marks them read (lib/people notifsChanged).
    if (me.role !== 'athlete') return
    let live = true
    const check = () => { getNotifications().then((r) => { if (live) setNotifCount(r.unread) }, () => {}) }
    check()
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') check() }, 60_000)
    const onVis = () => { if (document.visibilityState === 'visible') check() }
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener(NOTIFS_CHANGED_EVENT, check)
    window.addEventListener(DM_CHANGED_EVENT, check)
    return () => {
      live = false; window.clearInterval(t)
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener(NOTIFS_CHANGED_EVENT, check)
      window.removeEventListener(DM_CHANGED_EVENT, check)
    }
  }, [me.role])
  // Workout day: the pre-workout screen (a page: from Today / the plan) and the post-workout reaction.
  const setWorkout = (w: { sessionId?: string }) => showPage({ k: 'workout', sessionId: w.sessionId })
  const [reaction, setReaction] = useState<number | null>(null)
  // Post-workout reward (reward.py): once per workout, on the next open, after a sync or from
  // the workout push (?open=reward&activity=<id>); the monthly share card (Progress, moment).
  const [reward, setReward] = useState<{ id: number; data?: Reward | null } | null>(() => {
    const id = Number(new URLSearchParams(window.location.search).get('activity'))
    return openParam === 'reward' && id > 0 ? { id } : null
  })
  const [monthCard, setMonthCard] = useState<string | null>(null)
  const showReward = (r: Reward) => { markReactionShown(r.activity_id); setReward({ id: r.activity_id, data: r }) }
  const rewardChecked = useRef(false)
  useEffect(() => {
    if (openParam === 'reward') window.history.replaceState(null, '', '/app/')
    const onMsg = (e: MessageEvent) => {
      const url = String(e.data?.url ?? '')
      if (e.data?.type !== 'open' || !url.includes('open=reward')) return
      const id = Number(new URL(url, window.location.origin).searchParams.get('activity'))
      if (id > 0) setReward({ id })
    }
    navigator.serviceWorker?.addEventListener('message', onMsg)
    return () => navigator.serviceWorker?.removeEventListener('message', onMsg)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (rewardChecked.current || !overlayFree || !me.garmin.connected || reward) return
    rewardChecked.current = true
    getReward().then((x) => { if (x.reward) showReward(x.reward) }, () => { /* offline or a coach account */ })
  }, [overlayFree, me.garmin.connected]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (homeInView) loadToday() }, [homeInView, me, loadToday])
  const todayAction = (kind: TodayActionKind) => {
    if (kind === 'open_racepack') { openRaces(); pushPage({ k: 'screen', s: 'racepack' }) }
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
        const rw = a?.id != null && !reactionShown(a.id) ? (await getReward().catch(() => null))?.reward : null
        if (rw) { showReward(rw); return }
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
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void run() }, 60_000)  // hidden: the visibility handler catches up
    return () => { document.removeEventListener('visibilitychange', onVis); window.clearInterval(timer) }
  }, [overlayFree, me.garmin.connected, loadToday]) // eslint-disable-line react-hooks/exhaustive-deps
  // App icon badge (lib/unread.ts): unread cheers, requests, invites, coach messages.
  useEffect(() => (me.role === 'athlete' ? startBadgeSync() : undefined), [me.role])
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
    if (q === 'garmin' || q === 'calendar' || q === 'oura') { setConnect({ app: q }); return }
    if (q === 'notify') { open('settings'); return }
    if (q === 'sports') { showScreen('profile'); return }
    if (q === 'coach') { showScreen('coaches'); return }
    if (q === 'coach_status') { setCoachAsk(true); return }
    if (q === 'gear') { showScreen('gear'); return }
    if (q === 'friend') { pushPage({ k: 'friends' }); return }
    if (q === 'interests') { openDiscover(); return }
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
      showScreen('coach')
    } catch (e) { showToast((e as Error).message) }
  }
  const close = () => { setClosing(true); setTimeout(() => { setSheet(null); setClosing(false) }, 200) }
  // Drag-dismiss animates itself out, then unmounts at once (no second exit animation).
  const dismissNow = useCallback(() => { setSheet(null); setClosing(false) }, [])

  function newThread(from?: { thread_id: string; turn_id: string }, seedMsg?: ChatMessage) {
    setPending({ seed: from, seedMsg })
    if (sheet) close()
  }

  const openThread = (id: string) => { setPending(null); setThreadId(id) }

  // Back from connecting Google Calendar, Oura or WHOOP: the same popup reopens in its success
  // (import, then Done) or failure state.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const cal = params.get('calendar'), oura = params.get('oura'), whoop = params.get('whoop')
    if (!cal && !oura && !whoop) return
    window.history.replaceState(null, '', '/app/')
    if (oura) setConnect({ app: 'oura', result: oura === 'connected' ? 'connected' : 'failed' })
    else if (whoop) setConnect({ app: 'whoop', result: whoop === 'connected' ? 'connected' : 'failed' })
    else if (cal) setConnect({ app: 'calendar', result: cal === 'connected' ? 'connected' : 'failed' })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // Data sources (lib/sources.ts): screens read the current choice; the Oura popup asks once
  // how to use Oura (right after connecting it, or on the next open for anyone connected before).
  useEffect(() => { setCurrentSources(me.settings.data_sources) }, [me.settings.data_sources])
  useEffect(() => {
    if (me.oura.connected && me.settings.data_sources_asked === false) setConnect((c) => c ?? { app: 'oura', ask: true })
  }, [me.oura.connected, me.settings.data_sources_asked])
  const closeConnect = () => {
    // Closing the Oura popup without saving keeps the defaults and doesn't ask again.
    if (connect?.app === 'oura' && me.oura.connected && me.settings.data_sources_asked === false) {
      void putSettings({ data_sources_asked: true }).then(onChange, () => {})
    }
    setConnect(null)
  }
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
    closePages()
    setTab('rabbit')
    setHomeView('chat')
  }, [coachId, threads, setTab, setHomeView])

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
  // Home or Chat at Rabbit's log (also while the chat list is still loading).
  const atLog = !pending && (isCoach || !threadId)
  const showHome = atLog && homeView === 'home'
  // What's new in Rabbit's log since it was last read in Chat (a "N new" row on Home).
  const [logSeen, setLogSeen] = useState<number>(() => {
    try { const v = Number(window.localStorage.getItem('rabbit.log.seen')); if (v > 0) return v } catch { /* first run */ }
    const now = Date.now() / 1000
    try { window.localStorage.setItem('rabbit.log.seen', String(now)) } catch { /* ignore */ }
    return now
  })
  const itemTs = (it: ChatItem) => (it as { ts?: number }).ts ?? 0
  const readingLog = tab === 'rabbit' && isCoach && homeView === 'chat'
  useEffect(() => {
    if (!readingLog || !items.length) return
    const newest = Math.max(...items.map(itemTs))
    if (newest > logSeen) {
      setLogSeen(newest)
      try { window.localStorage.setItem('rabbit.log.seen', String(newest)) } catch { /* ignore */ }
    }
  }, [readingLog, items]) // eslint-disable-line react-hooks/exhaustive-deps
  const logNew = isCoach ? items.filter((it) => (it.kind === 'moment' || (it.kind === 'message' && it.role === 'agent')) && itemTs(it) > logSeen).length : 0
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
    else if (a.id === 'readiness') { if (a.event_id) showPage({ k: 'fit', id: a.event_id }); else openRaces() }
    else if (a.id === 'racepack') { openRaces(); pushPage({ k: 'screen', s: 'racepack' }) }
    else if (a.id === 'raceweek') { if (a.event_id) showPage({ k: 'raceweek', id: a.event_id, section: a.section }); else openRaces() }
    else if (a.id === 'plan') openPlan()
    else if (a.id === 'sick') openSick()
    else if (a.id === 'plan_fix') { openPlan(); requestPlanFix(a.session_id) }
    else if (a.id === 'progress') openProgress()
    else if (a.id === 'community_share' && a.draft_id) {
      shareDraft(a.draft_id).then(() => showToast('Shared to your Feed 🎉'), (e) => showToast((e as Error).message))
    } else if (a.id === 'community_later' && a.draft_id) {
      dismissDraft(a.draft_id).then(() => showToast('Okay, kept it to yourself.'), () => showToast('Okay.'))
    } else if (a.id === 'community') { if (a.club_id) openCommunity('clubs', a.club_id); else openCommunity(a.view === 'people' ? 'people' : 'feed') }
    else if (a.id === 'ask') tellRabbit(a.prompt ?? '')
    else if (a.id === 'race_invite') openRaces() // the invites inbox sits on top of Races
    else if (a.id === 'month_recap') setMonthCard(a.month ?? lastMonth().month)
    else if (a.id === 'block' || a.id === 'block_checkin') blockMomentAction(a).then((m) => { if (m) showToast(m) }, (e) => showToast((e as Error).message))
    else if (a.id === 'pace' || a.id === 'pace_accept') openPaceSuggestion({ sport: a.sport, sid: a.sid, accept: a.id === 'pace_accept' })
    else if (a.id === 'pace_later' && a.sid) dismissPace(a.sid).then(() => showToast('Okay, rabbt will check again later.'), (e) => showToast((e as Error).message))
  }
  // Quick replies under Rabbit's latest message when it asks something (max 3).
  const lastRow = shownRows[shownRows.length - 1]
  const chips = status === 'idle' && me.chat.available && lastRow?.kind === 'message' && lastRow.item.role === 'agent' && !lastRow.item.error
    ? replyChips(lastRow.item.text) : []
  const idlePrompt = useRotatingPrompt(tab === 'rabbit' && status === 'idle' && !composerFocus, composerPrompts(intents))
  const coachThread = coachId ? byId[coachId] : undefined

  // Rabbit's one status slot, most important first.
  const quest = progress ? nextQuest(progress) : null
  const recapReady = !!recapPillWeek && recapDismissed !== recapPillWeek
  const banner: Banner | null = threadsError ? { kind: 'error' }
    : !me.garmin.connected && firstVisitHidden() ? { kind: 'garmin' }
    : isCoach && wantsPlan(intents) && (!goal ? items.length > 0 : !goal.plan) ? { kind: 'plan', goal: goal?.title ?? null }
    : isCoach && quest && progress ? { kind: 'quest', title: quest.short ?? quest.title, done: progress.setup.done, total: progress.setup.total }
    : isCoach && recapReady ? { kind: 'recap' }
    : null
  const tapBanner = () => {
    if (!banner) return
    if (banner.kind === 'error') void refreshThreads(threadsError?.select)
    else if (banner.kind === 'garmin') setConnect({ app: 'garmin' })
    else if (banner.kind === 'plan') startSetup()
    else if (banner.kind === 'quest' && quest) doQuest(quest.id)
    else if (banner.kind === 'recap') openRecap(recapPillWeek ?? undefined)
  }
  // Typing on a phone: the keyboard needs the room, so the banner, Today and the tab bar step aside.
  const typing = composerFocus

  // "Me" (profile, coaching, Settings) opens from the avatar in every tab header.
  // Header icons are 44px buttons side by side: no enlarged tap areas reaching into a neighbour
  // (the bell's and chat's used to overlap, so a tap near the bell could open Chats).
  const meButton = (<div className="-mr-1 flex shrink-0 items-center">
    <SearchButton imperial={me.athlete.units !== 'metric'} />
    {me.role === 'athlete' && (
      <button type="button" className={HEADER_ICON}
        aria-label={notifCount > 0 ? `Notifications, ${notifCount} unread` : 'Notifications'}
        onClick={() => { dropSheet(); setNotifsOpen(true) }}>
        <Bell className="size-6" aria-hidden />
        {notifCount > 0 && <span className="absolute right-2 top-2 size-2.5 rounded-full bg-(--accent) ring-2 ring-(--bg)" aria-hidden />}
      </button>
    )}
    {/* Chat with Rabbit, from every tab: the chats list (pick one or start a new one). */}
    <button type="button" className={HEADER_ICON} data-tour="chat"
      aria-label={dmCount > 0 ? `Messages, ${dmCount} unread` : 'Messages'}
      onClick={() => { setChatsView('people'); open('threads') }}>
      <MessagesSquare className="size-6" aria-hidden />
      {dmCount > 0 && <span className="absolute right-2 top-2 size-2.5 rounded-full bg-(--accent) ring-2 ring-(--bg)" aria-hidden />}
    </button>
    <button className="relative flex size-11 shrink-0 items-center justify-center rounded-full" aria-label={
      me.coach_unread > 0 ? `Me, ${me.coach_unread} unread from your coach` : 'Me'} onClick={() => showPage({ k: 'me' })}>
      <Avatar name={me.profile.name || me.user_id} picture={me.profile.picture} photo={photoUrl(me.photo)} />
      {me.coach_unread > 0 && <span className="absolute right-1 top-1 size-2.5 rounded-full bg-(--accent) ring-2 ring-(--bg)" aria-hidden />}
    </button>
  </div>)

  function renderHeader(isLog: boolean, under = false) {
    return (
      <header className={cn('flex min-h-14 shrink-0 items-center gap-2 pl-4 pr-2 pt-[max(6px,env(safe-area-inset-top))]',
        isLog ? 'pb-1' : 'border-b border-(--border) pb-2')}>
        {!isLog && (
          <Button variant="ghost" size="icon" className="-ml-1" aria-label="Back to rabbt" onClick={slideBack}>
            <ChevronLeft className="size-6" />
          </Button>
        )}
        <h1 className="sr-only">{isLog ? 'rabbt' : pending ? 'New chat' : thread?.title || 'New chat'}</h1>
        <button type="button" className="flex min-h-11 min-w-0 flex-1 items-center gap-2.5 text-left"
          aria-label={isLog ? 'rabbt' : 'Back to rabbt'} onClick={isLog ? goBack : slideBack}>
          {/* App-icon tile, like the Home Screen icon (hops while rabbt is replying) */}
          <span className="logo-tile flex size-9 shrink-0 items-center justify-center rounded-[11px] bg-(--brand) shadow-sm">
            <RabbitLogo size={30} thinking={!under && status === 'streaming'} />
          </span>
          <span className="min-w-0">
            <span className={cn('block truncate font-display leading-tight text-(--brand)', isLog ? 'text-title-md' : 'text-title-sm')}>
              {isLog ? 'rabbt' : pending ? 'New chat' : thread?.title || 'New chat'}
            </span>
            {/* Home shows the race in its greeting; elsewhere a short line says what you're training for. */}
            {!(isLog && homeView === 'home' && atLog) && (
              <span className="line-clamp-2 text-meta leading-tight text-(--text-muted) max-[359px]:hidden">
                {goal ? `${goal.title}${goalLeft(goal) ? ` · ${goalLeft(goal)}` : ''}` : 'No goal set'}
              </span>
            )}
          </span>
        </button>
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
          {seed && <p className="mb-1 pl-1 text-caption font-semibold text-muted-foreground">From rabbt's log</p>}
          <CoachHeader label={m.label} ts={m.ts} />
          <MessageBubble message={m} showLabel={r.showLabel} pressProps={press} />
          {inLog && m.turnKind === 'proactive' && m.turnId && coachThread && (
            <DiscussButton busy={busy} onClick={() => newThread({ thread_id: coachThread.id, turn_id: m.turnId! }, m)} />
          )}
        </div>
      )
    })
  }

  // ------------------------------------------------------------------ home ---
  // Rabbit's Home: one scrolling dashboard with everything at a glance; Chat holds the log.
  const homeScroll = useRef<HTMLDivElement>(null)
  const refreshHome = () => {
    loadToday(); loadWeek(); setFeedTick((n) => n + 1)
    return Promise.all([refreshThreads(), getProgress().then(setProgress, () => {})])
  }
  const askFromHome = () => { setDraft((d) => ({ text: '', n: (d?.n ?? 0) + 1 })); setHomeView('chat') }
  function renderHome() {
    const athlete = me.role === 'athlete'
    const waiting = isCoach ? pendingCount : 0
    // One nudge at a time right under the hero (most important first); the rest wait in
    // "More for you" further down. The share question / first-visit card is the last resort.
    const kinds: HomeNudge[] = []
    if (logNew > 0 || waiting > 0) kinds.push('notes')
    if (banner) kinds.push('banner')
    if (athlete && homeNudges.niggle) kinds.push('niggle')
    if (athlete && goal && homeNudges.calendar) kinds.push('calendar')
    const top: HomeNudge = kinds[0] ?? 'next'
    const nudge = (k: HomeNudge) => {
      if (k === 'notes') {
        return (logNew > 0 || waiting > 0) ? (
          <button key="notes" type="button" onClick={() => setHomeView('chat')}
            className="flex min-h-14 w-full items-center gap-3.5 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-4 py-3 text-left active:opacity-80">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--brand)"><RabbitLogo size={24} /></span>
            <span className="min-w-0 flex-1 text-body font-medium leading-snug text-(--accent)">
              {waiting > 0 ? `rabbt needs your OK on ${waiting === 1 ? 'a change' : `${waiting} changes`}`
                : `rabbt has ${logNew} new ${logNew === 1 ? 'note' : 'notes'} for you`}
            </span>
            <ChevronRight className="size-5 shrink-0 text-(--accent)" aria-hidden />
          </button>
        ) : null
      }
      if (k === 'banner') {
        return banner ? (
          <StatusBanner key="banner" flush banner={banner} onTap={tapBanner}
            onDismiss={banner.kind === 'recap' && recapPillWeek ? () => dismissRecapPill(recapPillWeek) : undefined} />
        ) : null
      }
      if (k === 'niggle') return athlete ? <NiggleNudge key="niggle" refreshKey={feedTick} onShown={(v) => setHomeNudge('niggle', v)} /> : null
      if (k === 'calendar') return athlete && goal ? <CalendarNudge key="calendar" refreshKey={feedTick} onShown={(v) => setHomeNudge('calendar', v)} /> : null
      // The one-time share question, or what a first visitor without a watch can do now.
      if (banner) return null
      return (
        <Fragment key="next">
          {athlete && <SharePrompt onShown={setShareAsk} />}
          {!shareAsk && (
            <FirstVisitCard connected={me.garmin.connected} onConnect={() => setConnect({ app: 'garmin' })}
              onOpen={(id) => id === 'clubs' ? openCommunity('clubs') : id === 'events' ? openDiscover() : id === 'friends' ? openCommunity('people') : openCommunity()} />
          )}
        </Fragment>
      )
    }
    const rest = (['notes', 'banner', 'niggle', 'calendar', 'next'] as const).filter((k) => k !== top)
    const race = goal?.date ? { title: goal.title || 'Your race', days: daysUntil(goal.date) } : null
    return (
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div ref={homeScroll} className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
          <PullToRefresh onRefresh={refreshHome} />
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-7 px-5 pb-10 pt-3">
            {/* 1. Hello, today's date and the race you're training for. */}
            <HomeGreeting name={me.profile.name} race={athlete ? race : null} onRace={goal ? openPlan : undefined} />

            {/* 1b. The two things people come for: something to do near you, and a plan. */}
            {athlete && (
              <HomeStart hasPlan={builtPlan}
                planLine={upnext?.session ? `Today: ${upnext.session.title}${upnext.session.minutes ? `, ${upnext.session.minutes} min` : ''}` : null}
                onLocal={() => openCommunity('clubs')} onNewEvent={() => { openCommunity('clubs'); requestPostRun() }} onPlan={openPlan} onSetup={startSetup} />
            )}
            {athlete && <NearTonight hasPlan={builtPlan} refreshKey={feedTick} onOpenClub={(c) => openCommunity('clubs', c)}
              onPlanChanged={() => { loadToday(); loadWeek() }} />}

            {/* 2. The one thing to do now (race week and sick mode sit right on top of it). */}
            <div className="flex flex-col gap-3 empty:hidden">
              {athlete && <RaceWeekCard refreshKey={feedTick} onOpen={(id) => showPage({ k: 'raceweek', id })} />}
              {athlete && builtPlan && <SickBanner />}
              {!upnext && !upnextTried && me.garmin.connected && <UpNextSkeleton />}
              {/* No plan and no goal: the "Get a plan" start card above already says it. */}
              {upnext && upnext.kind !== 'set_goal' && (
                <UpNextCard key={upnext.today?.date ?? upnext.kind} up={upnext} week={null} insight={topInsight} onOpenInsight={openProgress}
                  onStart={(id) => setWorkout({ sessionId: id })} onToday={todayAction} onPlan={openPlan} onSetup={startSetup}
                  onClubs={(c) => openCommunity('clubs', c)} onAsk={tellRabbit} onSynced={() => { loadToday(); loadWeek() }}
                  hideStreak={intents[0] === 'consistent' || (!stripFirst(intents) && intents[1] === 'consistent')} hideReadiness={me.role === 'athlete'} />
              )}
            </div>

            {/* 3. One nudge (the most important thing to fix or answer), never a pile. */}
            <div className="flex flex-col gap-3 empty:hidden">{nudge(top)}</div>

            {stripFirst(intents) && (
              <IntentStrip intents={intents} me={me} progress={progress} refreshKey={feedTick}
                onOpen={(tg) => tg === 'progress' ? goTab('progress') : tg === 'events' ? openRaces() : tg === 'explore' ? openDiscover() : tg === 'coach' ? openMeRow('inbox') : tg === 'friends' ? openCommunity() : showScreen(tg)} />
            )}

            {/* 4. This week: every day at a glance, then the next 3 days with the weather. */}
            {goal && (
              <Section title="This week">
                <WeekPanel week={week} loading={weekLoading} error={weekError} onRetry={loadWeek} imperial={imperial}
                  refreshKey={feedTick} onOpenDay={openPlanDay} onOpenPlan={openPlan} onAskDay={askDay}
                  onOpenWeek={() => { try { sessionStorage.setItem(PLAN_VIEW_KEY, 'week') } catch { /* storage off */ } openPlan() }} />
                {athlete && <NextDays refreshKey={feedTick} />}
              </Section>
            )}

            {/* 5. How you're doing: sleep, HRV, readiness, form and one call for today. */}
            {athlete && (
              <Section title="How you're doing" action={<SeeAll label="Details" ariaLabel="Open Progress" onClick={openProgress} />}>
                <ReadinessSnapshot refreshKey={feedTick} onOpen={openProgress} onConnect={() => setConnect({ app: 'garmin' })} />
              </Section>
            )}

            {/* 6. Friends: who trained today, who races soon, their latest posts. */}
            {athlete && <FriendsLatest refreshKey={feedTick} imperial={imperial} onOpenFeed={() => openCommunity('feed')} onShown={setFriendsLatest} />}

            {/* 7. Coming up: the goal race (grade, countdown, fitness trend) and its checklist. */}
            {athlete && (
              <Section title="Coming up" hideWhenEmpty>
                {goal && <FitnessCountdown refreshKey={feedTick} onOpen={(id) => showPage({ k: 'fit', id })} />}
                <RaceChecklistCard refreshKey={feedTick} />
              </Section>
            )}

            {/* 8. Everything else, most useful first: one-tap actions, the other nudges, setup. */}
            <Section title="More for you" hideWhenEmpty>
              {athlete && (
                <QuickActions refreshKey={feedTick} imperial={imperial} onToast={showToast}
                  skipWatchFor={upnext?.secondary?.kind === 'send_to_watch' ? upnext.session?.id : null} skipCheer={friendsLatest} />
              )}
              {rest.map((k) => nudge(k))}
              {athlete && (me.garmin.connected || firstVisitHidden()) && (
                <GetStartedCard garmin={me.garmin.connected} hasGoal={!!goal} progress={progress} onStep={(st) => {
                  if (st === 'garmin') setConnect({ app: 'garmin' })
                  else if (st === 'plan') startSetup()
                  else if (st === 'race') openRaces()
                  else if (st === 'friends') openCommunity('people')
                  else if (st === 'club') openCommunity('clubs')
                  else doQuest('notify')
                }} />
              )}
            </Section>
            <button type="button" onClick={openHowItWorks}
              className="inline-flex min-h-11 items-center gap-2 self-center rounded-full px-4 text-small font-semibold text-(--accent) active:bg-(--bg-inset)">
              <CircleQuestionMark className="size-5" aria-hidden /> New here? How rabbt works
            </button>
          </div>
        </div>
        {/* Ask Rabbit: switches to Chat with the composer focused. */}
        <div className="shrink-0 border-t border-(--border) bg-background px-4 pb-2 pt-2">
          <button type="button" onClick={askFromHome} disabled={!me.chat.available}
            className="mx-auto flex min-h-11 w-full max-w-2xl items-center gap-2.5 rounded-full border border-(--border) bg-(--bg-surface) px-4 text-left text-body text-(--text-muted) active:bg-(--bg-inset) disabled:opacity-50">
            <MessageCircle className="size-5 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{me.chat.available ? 'Ask rabbt anything…' : 'Chat isn’t configured yet'}</span>
          </button>
        </div>
      </div>
    )
  }

  // ------------------------------------------------------------------ tabs ---
  const imperial = me.athlete.units !== 'metric'
  const selectTab = (t: TabId) => {
    if (t === tab && t === 'rabbit') {
      // Rabbit again: back to the log from a chat, else to its newest entries.
      if (inChat || pending) { if (pending) setPending(null); else slideBack() }
      else if (showHome) homeScroll.current?.scrollTo({ top: 0, behavior: smooth() })
      else setHomeView('home') // Today again from rabbt's chat: back to Today
      return
    }
    if (t === 'clubs' && t !== tab) { setCommunityView('clubs'); setCommunityClub(null) } // Clubs opens on its list
    setTab(t)
  }
  // Swipe between tabs (touch; hooks/useTabSwipe) and usage counts (lib/usage: tab views, app open).
  const shell = useRef<HTMLDivElement>(null)
  useTabSwipe(shell, { tabs: TAB_IDS, current: tab, enabled: overlayFree && !pages.length && !typing && !inChat && !pending, onSwipe: setTab })
  useEffect(() => { setUsageOff(me.settings.usage_off === true); trackAppOpen() }, [me.settings.usage_off])
  useEffect(() => { track('tab_view', { tab: meOpen ? 'me' : tab }) }, [tab, meOpen])
  const soonRace = !!goal?.date && daysUntil(goal.date) >= 0 && daysUntil(goal.date) <= 14
  const tabDots: Partial<Record<TabId, string | false>> = {
    plan: soonRace && 'race soon',
    feed: friendsDot && 'new from friends',
  }
  const openMeRow = (r: MeRow) => {
    if (r === 'friends') openCommunity('people')
    else if (r === 'settings') open('settings')
    else if (r === 'connections' || r === 'access' || r === 'usage' || r === 'partners' || r === 'legal') pushPage({ k: r })
    else if (r === 'memory') open('memory')
    else if (r === 'inbox') { setCoachMsgThread(null); showScreen('coach') }
    else if (r === 'coachstatus') setCoachAsk(true)
    else showScreen(r)
  }
  const weekLead = goal ? <WeekList imperial={me.athlete.units !== 'metric'} week={week} loading={weekLoading} error={weekError} onRetry={loadWeek} onAskDay={askDay} /> : null

  function planTab() {
    if (builtPlan) {
      return (
        <TabScreen key="planner" title="Plan" top={scheduleTop} action={meButton}>
          <PlanEditor me={me} goalTitle={goal?.title ?? 'Your race'}
            addRequest={addWorkout} onAddHandled={() => setAddWorkout(null)} onOpenEvent={openEvent}
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
      <TabScreen key="start" title="Plan" top={scheduleTop} action={meButton}>
        <Screen title="Plan" subtitle={goal ? goal.title : 'No plan yet'}>
          {goal && <RaceSwitcher title={goal.title} date={goal.date}
            sub={goal.plan ? `Your plan file${week?.index ? ` · wk ${week.index}${week.weeks ? `/${week.weeks}` : ''}` : ''}` : 'No plan for this race yet'}
            onSwitched={() => { void refreshThreads(); loadWeek(); onChange() }} onAddRace={openRaces} onBuild={startSetup} />}
          {goal?.plan && (
            <button type="button" onClick={startPlanConversion}
              className="flex min-h-12 items-center gap-3 rounded-xl border border-(--accent) bg-(--accent-subtle) px-4 py-3 text-left active:opacity-80">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--accent) text-(--on-fill)"><RabbitLogo size={18} current /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-body-lg font-semibold text-(--accent)">Turn your plan into full workouts</span>
                <span className="block text-meta text-(--text-muted)">Zones, pace and cadence for every day. You review it first.</span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-(--accent)" aria-hidden />
            </button>
          )}
          {weekLead}
          <TPPlanSection imperial={me.athlete.units !== 'metric'} />
          {goal?.plan ? (
            <Group label="Your plan">
              <SettingsRow icon={<Icon><FileText /></Icon>} title="Your plan file" subtitle={planLine(week, goal)}
                onClick={() => open('plan')} />
              <SettingsRow icon={<Icon><RabbitLogo current /></Icon>} title="Get a plan in rabbt"
                subtitle="Editable sessions you can send to your Garmin" onClick={startSetup} />
            </Group>
          ) : (
            <>
              <button type="button" onClick={startSetup}
                className="flex items-center gap-3 rounded-xl border border-(--accent) bg-(--accent-subtle) px-4 py-3.5 text-left shadow-sm active:opacity-80">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-(--on-fill)"><RabbitLogo size={20} current /></span>
                <span className="min-w-0 flex-1">
                  <span className="block text-lead font-semibold text-(--accent)">Get a plan</span>
                  <span className="block text-meta text-(--text-muted)">About 3 minutes · race, goals, you, your week</span>
                </span>
                <ChevronRight className="size-5 shrink-0 text-(--accent)" />
              </button>
              <Group>
                <SettingsRow icon={<Icon tone="muted"><Upload /></Icon>} title="I already have a plan"
                  subtitle="A file, screenshots, pasted text or a template" onClick={() => setAddPlan(true)} />
              </Group>
            </>
          )}
          {(goal || builtPlan) && <BlocksEntry />}
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
      <TabScreen key="overview" title="Progress" top={seg} action={meButton} lead={<MonthRecapEntry onOpen={setMonthCard} />}>
        <StatsScreen onOpenPlan={builtPlan ? openPlan : undefined}
          onOpenSetup={() => showScreen('quests')}
          onAsk={tellRabbit} onOpenGear={() => showScreen('gear')} onOpenSession={(id) => setWorkout({ sessionId: id })} />
      </TabScreen>
    )
  }

  // Schedule = the plan calendar + your events + finding events, one "+ Add" for all of it.
  const scheduleTop = (
    <div className="mx-auto flex w-full max-w-xl items-center gap-2">
      <div className="min-w-0 flex-1">
        <Segmented label="Plan" value={schedView} onChange={setSchedView}
          options={[['plan', 'Training'], ['events', 'Calendar'], ['discover', 'Find a race']] as const} />
      </div>
      <Button variant="primary" className="h-11 shrink-0 gap-1.5 px-4 text-body max-[359px]:w-11 max-[359px]:px-0" aria-haspopup="dialog"
        aria-label="Add a workout, event or plan" data-tour="add" onClick={() => setAddOpen(true)}>
        <Plus className="size-5" aria-hidden /><span className="max-[359px]:sr-only">Add</span>
      </Button>
    </div>
  )
  function scheduleTab() {
    if (schedView === 'plan') return planTab()
    return schedView === 'events' ? (
      <TabScreen key="events" title="Plan" top={scheduleTop} action={meButton}>
        <EventsScreen hasBuiltPlan={builtPlan} imperial={imperial} request={eventReq} onRequestHandled={() => setEventReq(null)} onDiscover={openDiscover}
          onChanged={() => { onChange(); void refreshThreads(); loadWeek() }}
          onOpenPlan={() => setSchedView('plan')} onBuildPlan={startSetup} />
      </TabScreen>
    ) : (
      <TabScreen key="discover" title="Plan" top={scheduleTop} action={meButton}>
        <ExploreScreen imperial={imperial} onAsk={tellRabbit} onChanged={onChange} />
      </TabScreen>
    )
  }

  function renderPage(pg: Page) {
    switch (pg.k) {
      case 'me': return <MePage me={me} goal={goal} progress={progress} onOpen={openMeRow} onOpenDoc={(doc) => pushPage({ k: 'legal', doc })} onClose={closePages} />
      case 'legal': return pg.doc
        ? <DocScreen slug={pg.doc} onClose={pages.length > 1 ? popPage : closePages} />
        : <PrivacyLegalScreen me={me} onClose={closePages} onOpenSettings={() => open('settings')} onOpenConnections={() => pushPage({ k: 'connections' })} />
      case 'connections': return <ConnectionsScreen onClose={closePages} />
      case 'access': return <AccessScreen onClose={closePages} />
      case 'usage': return <UsageScreen onClose={closePages} />
      case 'partners': return <PartnersScreen onClose={closePages} />
      case 'friends': return <FindFriendsScreen section={pg.section} add={pg.add} q={pg.q} onClose={pages.length > 1 ? popPage : closePages} />
      case 'block': return <BlockScreen id={pg.id} imperial={imperial} onClose={closePages} />
      case 'fit': return <RaceFitScreen eventId={pg.id} onClose={closePages} />
      case 'raceweek': return <RaceWeekScreen eventId={pg.id} section={pg.section} onClose={closePages} onAsk={tellRabbit} />
      case 'dm':
        return <ConversationScreen id={pg.id} imperial={imperial} onClose={pages.length > 1 ? popPage : closePages} />
      case 'checklist':
        return <RaceChecklistScreen eventId={pg.id} onClose={pages.length > 1 ? popPage : closePages} />
      case 'post':
        return <PostScreen key={`${pg.id}:${pg.comment ?? ''}`} id={pg.id} comment={pg.comment} imperial={imperial} onClose={pages.length > 1 ? popPage : closePages} />
      case 'person':
        return <PersonScreen key={pg.id} uid={pg.id} imperial={imperial} onClose={pages.length > 1 ? popPage : closePages} />
      case 'activity':
        return <ActivityScreen id={pg.id} imperial={imperial} onClose={pages.length > 1 ? popPage : closePages} onAsk={tellRabbit} />
      case 'workout':
        return (
          <WorkoutDayScreen sessionId={pg.sessionId} imperial={imperial}
            onClose={closePages} onAsk={tellRabbit} onCheckIn={(c) => setVoice(c)} />
        )
    }
    switch (pg.s) {
      case 'setup':
        return (
          <SetupWizard me={{ ...me, goal }} onClose={closePages}
            onDone={() => { onChange(); void refreshThreads(); loadWeek(); celebrate(null, 'plan') }}
            onOpenPlan={openPlan}
            onUploadPlan={() => { closePages(); setAddPlan(true) }}
            onMeChanged={onChange} />
        )
      case 'coach': return <CoachInbox openThreadId={coachMsgThread} onClose={closePages} onChanged={onChange} />
      case 'coaches': return <CoachesScreen onClose={closePages} onChanged={onChange} onFindCoach={() => showScreen('findcoach')} />
      case 'findcoach': return <FindCoachScreen athleteName={me.profile.name} onClose={closePages} onAsk={tellRabbit} onInvited={onChange} />
      case 'athletes': return <CoachApp me={me} onClose={closePages} />
      case 'racepack': return <RacePackScreen imperial={imperial} onClose={closePages} />
      case 'gear': return <GearScreen imperial={imperial} onClose={closePages} onAsk={tellRabbit} />
      case 'quests': return progress ? <SetupScreen p={progress} onClose={closePages} onAction={doQuest} /> : null
      case 'profile':
        return (
          <ProfileScreen me={me} hasBuiltPlan={builtPlan} onClose={closePages}
            onSaved={onChange} onRebuild={() => showScreen('setup')} onOpenEvents={openRaces} onOpenGear={() => showScreen('gear')} />
        )
    }
  }

  return (
    <div ref={shell} className={`relative flex min-h-0 flex-1 flex-col overflow-hidden ${typing ? '' : 'with-tabbar'}`}>
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
      {atLog && !typing && homeView === 'chat' && (
        <div className="shrink-0 px-5 pb-1 pt-1">
          {/* One way to rabbt: the Ask bar on Today opens this chat; Back returns to Today. */}
          {homeView === 'chat' && (
            <div className="flex items-center gap-2">
              <Button variant="ghost" className="-ml-2 h-11 gap-1 px-2 text-body" onClick={() => setHomeView('home')}>
                <ChevronLeft className="size-5" aria-hidden /> Today
              </Button>
              <span className="flex-1" />
              <Button variant="ghost" className="h-11 gap-1.5 px-3 text-body" onClick={() => { setChatsView('rabbit'); open('threads') }}>
                <History className="size-5" aria-hidden /> Past chats
              </Button>
            </div>
          )}
        </div>
      )}
      {showHome ? renderHome() : (
        <>
      {/* Chat keeps only problems (errors, Garmin); setup steps and the recap are Home's next step. */}
      {banner && !typing && (banner.kind === 'error' || banner.kind === 'garmin') && (
        <StatusBanner banner={banner} onTap={tapBanner}
          />
      )}
      {pending ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
          <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col">
            {pending.seedMsg && (
              <div className="rounded-xl border border-dashed border-border p-2">
                <p className="mb-1 pl-1 text-caption font-semibold text-muted-foreground">From rabbt's log</p>
                <CoachHeader label={pending.seedMsg.label} ts={pending.seedMsg.ts} />
                <MessageBubble message={pending.seedMsg} showLabel={false} />
              </div>
            )}
            <div className="chat-empty flex flex-1 flex-col items-center text-center">
              <EmptyHero suggestions={pending.seedMsg ? undefined : TOPIC_SUGGESTIONS.map((q) => (
                    <button key={q} disabled={!me.chat.available || busy}
                      className="min-h-12 w-full cursor-pointer rounded-(--radius) border border-border bg-(--bg-surface) px-4 py-3 text-left text-body leading-snug text-(--text) transition-all hover:bg-secondary active:bg-(--bg-inset) disabled:opacity-50"
                      onClick={() => void sendPending(q, [])}>{q}</button>
                  ))}>
                {!pending.seedMsg && <RabbitLogo size={64} className="mb-3 opacity-40" />}
                <p className="mb-2 font-display text-title leading-tight text-(--brand)">
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
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-body text-muted-foreground" role="alert">
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
              <p className="font-display text-display leading-tight text-(--brand)">
                Hi{me.profile.name ? ` ${me.profile.name.split(' ')[0]}` : ''}, let's build your plan
              </p>
              <p className="mt-2 text-body leading-snug text-(--text-secondary)">
                Tell rabbt about your race, your goals and your week. You'll get a plan from today to race day, with workouts you can send straight to your Garmin.
              </p>
            </div>
            <button type="button" onClick={startSetup}
              className="flex items-center gap-3 rounded-xl border border-(--accent) bg-(--accent-subtle) px-4 py-3.5 text-left shadow-sm active:opacity-80">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent) text-(--on-fill)"><RabbitLogo size={20} current /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-lead font-semibold text-(--accent)">Get a plan</span>
                <span className="block text-meta text-(--text-muted)">About 3 minutes · race, goals, you, your week</span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-(--accent)" />
            </button>
            <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
              <label htmlFor={ATTACH_INPUT_ID} onClick={() => setDraft((d) => ({ text: "Here's my training plan.", n: (d?.n ?? 0) + 1 }))}
                className="flex cursor-pointer items-center gap-3 px-4 py-3 active:bg-(--bg-inset)">
                <Upload className="size-5 shrink-0 text-(--text-secondary)" />
                <span className="min-w-0 flex-1">
                  <span className="block text-body text-(--text)">I already have a plan</span>
                  <span className="block text-caption text-(--text-muted)">Send a PDF or screenshots from a coach or app</span>
                </span>
              </label>
              <button type="button" onClick={() => tellRabbit("I'm training for ")}
                className="flex w-full items-center gap-3 border-t border-(--border) px-4 py-3 text-left active:bg-(--bg-inset)">
                <MessageCircle className="size-5 shrink-0 text-(--text-secondary)" />
                <span className="min-w-0 flex-1">
                  <span className="block text-body text-(--text)">Just chat with rabbt</span>
                  <span className="block text-caption text-(--text-muted)">Describe your race and training in your own words</span>
                </span>
              </button>
            </div>
          </div>
        </div>
      ) : items.length === 0 && settled ? (
        <div className="chat-empty flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-6 text-center">
          <EmptyHero gap={20} suggestions={suggestions.map((s) => (
              <button key={s} disabled={!me.chat.available}
                className="min-h-12 w-full cursor-pointer rounded-(--radius) border border-border bg-(--bg-surface) px-4 py-3 text-left text-body leading-snug text-(--text) transition-all hover:bg-secondary active:bg-(--bg-inset) disabled:opacity-50"
                onClick={() => void (isCoach ? sendFromLog(s, []) : send(s))}>{s}</button>
            ))}>
          <RabbitLogo size={72} className="mb-3 opacity-40" />
          <p className="mb-2 font-display text-title-lg leading-tight text-(--brand)">
            {isCoach ? 'Chat with rabbt' : 'Ready when you are.'}
          </p>
          <p className="max-w-[34ch] text-body leading-snug text-(--text-secondary)">
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
            <PullToRefresh onRefresh={() => { loadToday(); return Promise.all([refreshThreads(), getProgress().then(setProgress, () => {})]) }} />
            {renderRows(shownRows, isCoach)}
            <ReplyChips chips={chips} disabled={busy} onPick={(t) => void (isCoach ? sendFromLog(t, []) : send(t))} />
            {thinking && (
              <div className="flex items-center gap-2 pl-1 text-body text-muted-foreground">
                <div className="thinking-dots flex items-center gap-[3px]" role="status" aria-label="rabbt is thinking"><span /><span /><span /></div>
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
            : status === 'streaming' ? 'rabbt is replying…' : status === 'busy' ? 'rabbt is replying in another chat…' : idlePrompt}
        />
      </div>
        </>
      )}
      </div>
      </div>

      {visited.has('plan') && <div className={tabCls('plan')} data-tab-hidden={tab !== 'plan' || undefined}>{scheduleTab()}</div>}
      {addOpen && (
        <AddSheet hasPlan={builtPlan} onClose={() => setAddOpen(false)}
          onWorkout={() => { setSchedView('plan'); setAddWorkout((r) => ({ date: localToday(), n: (r?.n ?? 0) + 1 })); goTab('plan') }}
          onEvent={() => setCalendarAdd(true)}
          onTravel={openTravel} onSick={openSick}
          onBuildPlan={startSetup} onImportPlan={() => { closePages(); setAddPlan(true) }} />
      )}
      {calendarAdd && (
        <NewEventSheet only={CALENDAR_KINDS} title="Add to my calendar" imperial={imperial} onClose={() => setCalendarAdd(false)}
          onSaved={() => { onChange(); loadWeek(); setEventReq((r) => ({ n: (r?.n ?? 0) + 1 })) }} onOpenPlan={openPlan} onBuildPlan={startSetup} />
      )}
      {visited.has('feed') && (
        <div className={tabCls('feed')} data-tab-hidden={tab !== 'feed' || undefined}>
          <TabScreen key="feed" action={meButton}>
            <CommunityScreen section="feed" imperial={imperial} view="feed" onView={(v) => { if (v !== 'clubs') openCommunity(v) }} onChanged={onChange}
              club={null} onClub={(id) => { if (id) openCommunity('clubs', id) }} />
          </TabScreen>
        </div>
      )}
      {visited.has('clubs') && (
        <div className={tabCls('clubs')} data-tab-hidden={tab !== 'clubs' || undefined}>
          <TabScreen key="clubs" action={meButton}>
            <CommunityScreen section="clubs" imperial={imperial} view={communityView === 'feed' ? 'clubs' : communityView}
              onView={(v) => openCommunity(v)} onChanged={onChange} club={communityClub} onClub={setCommunityClub}
              onOpenPlan={openPlan} onBuildPlan={startSetup} />
          </TabScreen>
        </div>
      )}
      {visited.has('progress') && <div className={tabCls('progress')} data-tab-hidden={tab !== 'progress' || undefined}>{progressTab()}</div>}
      {!typing && <TabBar tab={tab} onSelect={selectTab} dots={tabDots} />}
      {topPage && (
        <div key={pageKey(topPage)} className={`page-stack${leaving ? ' page-stack--leaving' : revealed ? ' page-stack--revealed' : pages.length > 1 ? ' page-stack--pushed' : ''}`}>
          <PageStack back={pages.length > 1 ? popPage : undefined}>{renderPage(topPage)}</PageStack>
        </div>
      )}

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
      {voice && <VoiceCheckIn open sessionId={voice?.sessionId} activityId={voice?.activityId} title={voice?.title} onClose={() => setVoice(null)} onSaved={(_, xp) => { loadToday(); if (xp) getProgress().then(setProgress, () => {}) }} />}
      <div role="status" aria-live="polite" aria-atomic="true">{toast && <div key={toast.n} className="rabbit-toast">{toast.msg}</div>}</div>
      {me.role === 'athlete' && <Tour userId={me.user_id} auto={!typing} onStart={() => { closePages(); goTab('rabbit') }} />}
      <HowItWorksHost />
      <WelcomeGate me={me} onSaved={onChange} onNext={(s) => s === 'progress' ? goTab('progress') : s === 'local' ? openCommunity('clubs') : doQuest(s)} />

      {notifsOpen && <NotificationsSheet onClose={() => setNotifsOpen(false)} />}
      {newDm && (
        <NewMessageSheet to={newDm.to} share={newDm.share} onClose={() => setNewDm(null)}
          onOpened={(id) => { setNewDm(null); dropSheet(); setPages((st) => [...st.filter((p) => p.k !== 'dm'), { k: 'dm', id }]) }} />
      )}
      {sheet === 'threads' && (
        <ThreadsSheet goal={goal} threads={threads} activeId={threadId} closing={closing} onDismissed={dismissNow}
          onSelect={(id) => { openThread(id); setTab('rabbit'); setHomeView('chat'); close() }}
          onNew={() => { setTab('rabbit'); setHomeView('chat'); newThread() }}
          onDelete={async (id) => {
            try { await deleteThread(id); await refreshThreads() } catch (e) { showToast((e as Error).message) }
          }}
          onEditGoal={() => open('memory')} onClose={close}
          {...(me.role === 'athlete' ? {
            view: chatsView, onView: setChatsView, dmUnread: dmCount,
            onOpenDm: (id: string) => { close(); setPages([{ k: 'dm', id }]) },
            onNewDm: () => { close(); setNewDm({}) },
          } : {})} />
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
      {converting && (
        <ConvertPlanScreen onClose={() => setConverting(false)}
          onImportOther={() => { setConverting(false); setAddPlan(true) }}
          onApplied={() => { setConverting(false); onChange(); void refreshThreads(); loadWeek(); setSchedView('plan'); setTab('plan') }} />
      )}
      {addPlan && <AddPlanLauncher onClose={() => setAddPlan(false)} onApplied={() => { setAddPlan(false); onChange(); void refreshThreads(); loadWeek() }} />}
      {coachAsk && (
        <CoachStatusSheet current={me.athlete.coach_status} onClose={() => setCoachAsk(false)}
          onSaved={(s) => {
            setCoachAsk(false); onChange(); getProgress().then(setProgress, () => {})
            if (s === 'looking') showScreen('findcoach')
            else if (s === 'have_coach') showScreen('coaches')
            else showToast('Going solo. rabbt has your back.')
          }} />
      )}
      {reward && (
        <RewardSheet key={reward.id} activityId={reward.id} initial={reward.data} onClose={() => setReward(null)}
          onBreakdown={(id) => setReaction(id)} onCheckIn={(c) => setVoice(c)}
          onFeel={(xp) => { if (xp) getProgress().then(setProgress, () => {}) }} />
      )}
      {monthCard && <MonthRecapSheet month={monthCard} onClose={() => setMonthCard(null)} />}
      {me.role === 'athlete' && <CelebrationHost ready={overlayFree && !reward && reaction == null && !monthCard} />}
      {me.role === 'athlete' && <BodyHost imperial={imperial} />}
      {me.role === 'athlete' && <SickHost onToast={showToast} />}
      <PaceHost />
      {reaction != null && (
        <ReactionCard key={reaction} activityId={reaction} imperial={imperial}
          onClose={() => setReaction(null)} onOpenSession={(id) => { setReaction(null); setWorkout({ sessionId: id }) }}
          onCheckIn={(c) => { setReaction(null); setVoice(c) }} />
      )}
      {progress && overlayFree && <Celebration key={progress.xp} p={progress} onDone={() => setProgress((p) => p && { ...p, level_up: false, new_badges: [] })} />}
      {sheet === 'settings' && (
        <BottomSheet title="Settings" closing={closing} onClose={close} onDismissed={dismissNow}>
          <SettingsPanels me={me} onChange={onChange} onDevDone={() => void reload()}
            onOpenConnections={() => pushPage({ k: 'connections' })} />
        </BottomSheet>
      )}
      {connect && (
        <ConnectSheet key={`${connect.app}:${connect.result ?? ''}`} me={me} req={connect} onClose={closeConnect}
          onChanged={onChange} onToast={showToast} />
      )}
    </div>
  )
}
