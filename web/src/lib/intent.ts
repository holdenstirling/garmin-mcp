// How the athlete uses Rabbit ("What brings you to Rabbit?"), server: intent.py.
// athlete.intents is a list in priority order (tap order); welcomed_at marks the welcome as seen.
// Other screens read the current answer with useIntents() / primaryIntent() (no extra request:
// the app shell sets it from /me), e.g. Events opens on Explore for "events" people.
import { useSyncExternalStore } from 'react'
import { getFeed } from '@/lib/social'
import { postJSON, type Me } from '@/lib/api'

export type Intent = 'train' | 'consistent' | 'community' | 'events' | 'coach' | 'explore'
export type WelcomeMode = 'full' | 'lite' | null
export type IntentView = {
  intents: Intent[]; welcomed_at: string | null; welcome: WelcomeMode
  options: { id: Intent; title: string; help: string }[]
}

/** The two big reasons people come (the welcome's first choice); "More reasons" shows the rest. */
export const QUICK_STARTS: { id: 'local' | 'plan' | 'both'; title: string; help: string; intents: Intent[] }[] = [
  { id: 'local', title: 'Find things to do near me', help: 'Clubs, group runs, leagues and events, or start your own', intents: ['events', 'community'] },
  { id: 'plan', title: 'Get a training plan', help: 'For a race or just to get fitter, and it moves when life does', intents: ['train'] },
  { id: 'both', title: 'Both', help: 'A plan, plus people and places to train with', intents: ['train', 'events', 'community'] },
]

/** Card copy (same as intent.INTENTS on the server). No em dashes in copy. */
export const INTENT_OPTIONS: { id: Intent; title: string; help: string }[] = [
  { id: 'train', title: 'Train for a goal or race', help: 'A plan that adapts to real life, synced to your watch' },
  { id: 'community', title: 'Find my people', help: 'Friends, local clubs and a feed for the moments that matter' },
  { id: 'events', title: 'Find events', help: 'Races, group runs and meetups near you' },
  { id: 'consistent', title: 'Stay active and consistent', help: 'Streaks, challenges and nudges that stick' },
  { id: 'coach', title: 'Work with a coach', help: 'Find one or bring yours' },
  { id: 'explore', title: 'Just exploring', help: 'Look around first, set things up later' },
]
const IDS = new Set<string>(INTENT_OPTIONS.map((o) => o.id))

export const saveIntents = (intents: Intent[]) => postJSON<IntentView>('/api/intent', { intents })
export const skipWelcome = () => postJSON<IntentView>('/api/intent', { skip: true })

/** The saved intents on /me (tolerant of old or junk values). */
export function intentsOf(me: Pick<Me, 'athlete'>): Intent[] {
  const raw = (me.athlete as { intents?: unknown }).intents
  return Array.isArray(raw) ? raw.filter((x): x is Intent => typeof x === 'string' && IDS.has(x)) : []
}
/** /me.welcome: "full" for a new account, "lite" once for an existing one, null after. */
export const welcomeOf = (me: Me): WelcomeMode => (me as Me & { welcome?: WelcomeMode }).welcome ?? null

export const primaryIntent = (intents: readonly Intent[] | null | undefined): Intent | null => intents?.[0] ?? null
/** Plan building stays front and center unless they told us training isn't why they're here. */
export const wantsPlan = (intents: readonly Intent[]) => intents.length === 0 || intents.includes('train')

// ------------------------------------------------- shared current value ---
let current: Intent[] = []
const listeners = new Set<() => void>()
export function setCurrentIntents(next: Intent[]) {
  if (next.join() === current.join()) return
  current = next
  listeners.forEach((l) => l())
}
export function useIntents(): Intent[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l) } }, () => current, () => current)
}

// "How you use Rabbit" (Settings) re-opens the welcome questions from anywhere.
const OPEN_EVENT = 'rabbit:welcome'
export const openWelcome = () => window.dispatchEvent(new Event(OPEN_EVENT))
export function onOpenWelcome(fn: () => void): () => void {
  window.addEventListener(OPEN_EVENT, fn)
  return () => window.removeEventListener(OPEN_EVENT, fn)
}

/** "Train for a goal · Find my people" */
export const intentsSummary = (intents: readonly Intent[]) =>
  intents.length ? intents.map((i) => INTENT_OPTIONS.find((o) => o.id === i)!.title).join(', ') : 'Not set'

// ------------------------------------------------------- composer + chat ---
const PROMPTS: Record<Intent, string[]> = {
  train: ['How should I fuel my long run?', 'Am I ready for intervals today?'],
  consistent: ['Give me a 20 minute workout for today', 'How do I keep my streak going?'],
  community: ['Find a group run this weekend', 'Any running clubs near me?'],
  events: ['Find a race near me next month', 'Any group rides this weekend?'],
  coach: ['What should I look for in a coach?', 'Help me find a coach for my goal'],
  explore: ['What can rabbt do for me?'],
}
const SUGGEST: Record<Intent, string[]> = {
  train: ['How did my training go this week?', 'Am I recovered enough for a hard workout today?'],
  consistent: ['Give me a quick workout I can do today.', 'Help me keep my streak alive this week.'],
  community: ['Find a group run this weekend.', 'How do I find a running club near me?'],
  events: ['Find me a fun race in the next two months.', 'What group activities are near me this weekend?'],
  coach: ['What should I ask a coach before hiring them?', 'Do I need a coach for my goal?'],
  explore: ['What can you help me with?', 'Suggest a goal for me.'],
}
const promptCache = new Map<string, string[]>()
/** The composer's rotating placeholders, leaning toward what they came for (stable per answer). */
export function composerPrompts(intents: readonly Intent[], base = 'Ask rabbt anything…'): string[] {
  const key = intents.join()
  let p = promptCache.get(key)
  if (!p) {
    p = [base, ...intents.flatMap((i) => PROMPTS[i])].slice(0, 4)
    if (p.length === 1) p.push(...PROMPTS.train)
    promptCache.set(key, p)
  }
  return p
}
/** Up to 3 starter questions for Rabbit's empty log. */
export function intentSuggestions(intents: readonly Intent[], fallback: string[]): string[] {
  const out: string[] = []
  for (const s of [...intents.flatMap((i) => SUGGEST[i].slice(0, intents.length > 1 ? 1 : 2)), ...fallback]) {
    if (!out.includes(s)) out.push(s)
  }
  return out.slice(0, 3)
}

// --------------------------------------------------------- "Here's your Rabbit" ---
/** Where the welcome's primary button goes: a setup quest, or the Progress tab. */
export type NextStep = 'garmin' | 'plan' | 'interests' | 'friend' | 'coach_status' | 'progress' | 'local'
export type WelcomePlan = { bullets: string[]; next: { step: NextStep; label: string } | null }

const BULLET: Record<Intent, string> = {
  train: 'A plan built around your week and your goal, sent to your Garmin',
  consistent: 'A daily streak and weekly challenges sized to you',
  community: "Your friends' workouts and kudos, right on your home screen",
  events: 'Races, group runs and meetups near you, picked for you',
  coach: 'Coaches who fit your goals, or invite the one you already have',
  explore: 'Ask rabbt anything about training, recovery or what to try next',
}

export function welcomePlan(intents: readonly Intent[], ctx: { garmin: boolean; hasPlan: boolean }): WelcomePlan {
  const list: Intent[] = intents.length ? [...intents] : ['explore']
  const bullets = list.map((i) => BULLET[i])
  if (!ctx.garmin) bullets.unshift('Connect Garmin so every workout counts automatically')
  const garmin = { step: 'garmin' as const, label: 'Connect Garmin' }
  let next: WelcomePlan['next'] = null
  switch (list[0]) {
    case 'train': next = !ctx.hasPlan ? { step: 'plan', label: 'Build my plan' } : ctx.garmin ? null : garmin; break
    case 'consistent': next = ctx.garmin ? { step: 'progress', label: 'See my streak' } : garmin; break
    case 'community': next = { step: 'friend', label: 'Find my people' }; break
    case 'events': next = { step: 'local', label: "See what's near me" }; break
    case 'coach': next = { step: 'coach_status', label: 'Find a coach' }; break
    default: next = ctx.garmin ? null : garmin
  }
  return { bullets: bullets.slice(0, 4), next }
}

// ------------------------------------------------------- community strip ---
/** One friend or club moment for Rabbit home ("From your community"). */
export type Highlight = { id: string; title: string; subtitle?: string; who?: string }
type HighlightSource = () => Promise<Highlight[]>
/** Default: the latest workouts from people you follow (Friends feed). The Community feature
 *  can replace it with registerCommunityHighlights(() => fetchClubAndFriendHighlights()). */
let source: HighlightSource = async () => {
  const r = await getFeed()
  return r.items.filter((it) => !it.mine).slice(0, 2).map((it) => ({
    id: it.id, who: it.user.name.split(' ')[0], title: it.title,
    subtitle: it.kudos ? `${it.kudos} kudos` : undefined,
  }))
}
export function registerCommunityHighlights(fn: HighlightSource) { source = fn }
/** Never throws: no community data -> [] and the strip hides. */
export async function communityHighlights(): Promise<Highlight[]> {
  try { return (await source()).slice(0, 2) } catch { return [] }
}
