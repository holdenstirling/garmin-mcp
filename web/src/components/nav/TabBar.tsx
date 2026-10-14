// The app's five sections, always one tap away. Rabbit (the AI: log, Today, composer) is home.
import { useEffect, useState } from 'react'
import { CalendarRange, Flag, Rabbit, TrendingUp, Users } from 'lucide-react'
import { getBadge } from '@/lib/social'
import { RabbitLogo } from '@/components/RabbitLogo'
import { REPLY_DONE_EVENT } from '@/components/fx/motion'

// 'races' keeps its id (stored tabs, deep links); the label is Events. "Me" opens from the
// avatar in the tab headers (Chat.tsx), not a tab.
export type TabId = 'rabbit' | 'plan' | 'community' | 'races' | 'progress'

const TABS: { id: TabId; label: string; icon: typeof Rabbit }[] = [
  { id: 'rabbit', label: 'Rabbit', icon: Rabbit },
  { id: 'plan', label: 'Plan', icon: CalendarRange },
  { id: 'community', label: 'Community', icon: Users },
  { id: 'races', label: 'Events', icon: Flag },
  { id: 'progress', label: 'Progress', icon: TrendingUp },
]

const KEY = 'rabbit.tab'

export function readTab(): TabId {
  try {
    const t = window.sessionStorage.getItem(KEY)
    return TABS.some((x) => x.id === t) ? (t as TabId) : 'rabbit'
  } catch { return 'rabbit' }
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
          <button key={id} type="button" className="tab-bar__item" aria-current={tab === id ? 'page' : undefined}
            aria-label={dot ? `${label}, ${dot}` : label}
            onPointerDown={id === 'rabbit' ? () => setTwitch((n) => n + 1) : undefined}
            onClick={() => { if (id !== tab) setHop((h) => ({ id, n: (h?.n ?? 0) + 1 })); onSelect(id) }}>
            {id === 'rabbit' && wiggle > 0 ? (
              <span key={`w${wiggle}`} className="fx-tab-wiggle" aria-hidden><RabbitLogo size={22} /></span>
            ) : (
              <span key={hop?.id === id ? `h${hop.n}` : 'still'} className={hop?.id === id ? 'fx-tab-hop' : 'inline-flex'} aria-hidden>
                {id === 'rabbit'
                  ? <span key={`t${twitch}`} className={twitch ? 'rb-twitch rb-tab-rabbit' : 'rb-tab-rabbit inline-flex'}><RabbitLogo size={22} /></span>
                  : <Icon className="size-[22px]" strokeWidth={tab === id ? 2.25 : 1.75} aria-hidden />}
              </span>
            )}
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
