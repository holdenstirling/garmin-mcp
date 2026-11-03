// The app's four sections, always one tap away: Today (rabbt: today + chat), Plan (plan +
// events), Friends (the feed, people, and Near me: runs, clubs and meetups) and You (progress,
// profile, connected apps and settings).
import { useEffect, useState } from 'react'
import { CalendarRange, Rabbit as RabbitGlyph, UserRound, UsersRound } from 'lucide-react'
import { getBadge } from '@/lib/social'
import { RabbitLogo } from '@/components/RabbitLogo'
import { REPLY_DONE_EVENT } from '@/components/fx/motion'

// Ids match the labels. Older ids (stored tabs, links, notifications) map with migrateTab:
// rabbit -> today, feed / community -> friends, clubs -> friends (Near me), races -> plan,
// progress / me -> you.
export type TabId = 'today' | 'plan' | 'friends' | 'you'
/** Any tab id the app has ever used (stored tabs, deep links, older callers). */
export type AnyTabId = TabId | 'rabbit' | 'feed' | 'clubs' | 'progress' | 'community' | 'races' | 'me'

const TABS: { id: TabId; label: string; icon: typeof RabbitGlyph }[] = [
  { id: 'today', label: 'Today', icon: RabbitGlyph },
  { id: 'plan', label: 'Plan', icon: CalendarRange },
  { id: 'friends', label: 'Friends', icon: UsersRound },
  { id: 'you', label: 'You', icon: UserRound },
]

const OLD: Record<string, TabId> = {
  rabbit: 'today', feed: 'friends', community: 'friends', clubs: 'friends', races: 'plan', progress: 'you', me: 'you',
}

/** Any tab id, old or new (stored tab, old link) -> today's tab. */
export function migrateTab(t: string | null | undefined): TabId | null {
  if (!t) return null
  if (t in OLD) return OLD[t]!
  return TABS.some((x) => x.id === t) ? (t as TabId) : null
}

/** Left-to-right order (swipe between tabs: hooks/useTabSwipe). */
export const TAB_IDS: readonly TabId[] = TABS.map((t) => t.id)

const KEY = 'rabbit.tab'

export function readTab(): TabId {
  try {
    return migrateTab(window.sessionStorage.getItem(KEY)) ?? 'today'
  } catch { return 'today' }
}

export function saveTab(t: TabId) {
  try { window.sessionStorage.setItem(KEY, t) } catch { /* this page only */ }
}

export function TabBar({ tab, onSelect, dots }: {
  tab: TabId
  /** also called when the current tab is tapped again (back to its top / to the log) */
  onSelect: (t: TabId) => void
  dots?: Partial<Record<TabId, string | false | null | undefined>>
}) {
  // Motion (styles/fx.css): the tapped tab's icon hops once (not on first paint); the Rabbit
  // tab shows the rabbit mark wiggling when Rabbit finished a reply while you were elsewhere.
  // The Rabbit tab's icon is the app's rabbit mark; its ears twitch on press (styles/rabbit.css).
  const [hop, setHop] = useState<{ id: TabId; n: number } | null>(null)
  const [twitch, setTwitch] = useState(0)
  const [wiggle, setWiggle] = useState(0)
  useEffect(() => {
    const on = () => setWiggle((n) => n + 1)
    window.addEventListener(REPLY_DONE_EVENT, on)
    return () => window.removeEventListener(REPLY_DONE_EVENT, on)
  }, [])
  useEffect(() => {
    if (!wiggle) return
    const t = window.setTimeout(() => setWiggle(0), 1000)
    return () => window.clearTimeout(t)
  }, [wiggle])
  return (
    <nav className="tab-bar" aria-label="Sections">
      {TABS.map(({ id, label, icon: Icon }) => {
        const dot = dots?.[id]
        return (
          <button key={id} type="button" data-tour={`tab-${id}`} className="tab-bar__item" aria-current={tab === id ? 'page' : undefined}
            aria-label={dot ? `${label}, ${dot}` : label}
            onPointerDown={id === 'today' ? () => setTwitch((n) => n + 1) : undefined}
            onClick={() => { if (id !== tab) setHop((h) => ({ id, n: (h?.n ?? 0) + 1 })); onSelect(id) }}>
            <span className="tab-bar__icon" aria-hidden>
              {id === 'today' && wiggle > 0 ? (
                <span key={`w${wiggle}`} className="fx-tab-wiggle"><RabbitLogo size={24} /></span>
              ) : (
                <span key={hop?.id === id ? `h${hop.n}` : 'still'} className={hop?.id === id ? 'fx-tab-hop' : 'inline-flex'}>
                  {id === 'today'
                    ? <span key={`t${twitch}`} className={twitch ? 'rb-twitch rb-tab-rabbit' : 'rb-tab-rabbit inline-flex'}><RabbitLogo size={24} /></span>
                    : <Icon className="size-6" strokeWidth={tab === id ? 2.25 : 1.9} aria-hidden />}
                </span>
              )}
            </span>
            <span aria-hidden>{label}</span>
            {dot && <span className="tab-bar__dot" aria-hidden />}
          </button>
        )
      })}
    </nav>
  )
}

const SEEN_EVENT = 'rabbit:social-seen' // Community → People fires it after marking it seen

/** Pending friend requests or new kudos since People (Community) was last opened. */
export function useSocialBadge(): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    let live = true
    const check = () => { getBadge().then((b) => { if (live) setOn(b.pending + b.new_kudos > 0) }, () => { /* no dot */ }) }
    const seen = () => setOn(false)
    const vis = () => { if (document.visibilityState === 'visible') check() }
    check()
    window.addEventListener(SEEN_EVENT, seen)
    document.addEventListener('visibilitychange', vis)
    return () => { live = false; window.removeEventListener(SEEN_EVENT, seen); document.removeEventListener('visibilitychange', vis) }
  }, [])
  return on
}
