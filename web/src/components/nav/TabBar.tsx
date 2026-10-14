// The app's five sections, always one tap away. Rabbit (the AI: log, Today, composer) is home.
import { useEffect, useState } from 'react'
import { CalendarRange, CircleUser, Flag, Rabbit, TrendingUp } from 'lucide-react'
import { getBadge } from '@/lib/social'

export type TabId = 'rabbit' | 'plan' | 'progress' | 'races' | 'me'

const TABS: { id: TabId; label: string; icon: typeof Rabbit }[] = [
  { id: 'rabbit', label: 'Rabbit', icon: Rabbit },
  { id: 'plan', label: 'Plan', icon: CalendarRange },
  { id: 'progress', label: 'Progress', icon: TrendingUp },
  { id: 'races', label: 'Races', icon: Flag },
  { id: 'me', label: 'Me', icon: CircleUser },
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
  return (
    <nav className="tab-bar" aria-label="Sections">
      {TABS.map(({ id, label, icon: Icon }) => {
        const dot = dots?.[id]
        return (
          <button key={id} type="button" className="tab-bar__item" aria-current={tab === id ? 'page' : undefined}
            aria-label={dot ? `${label}, ${dot}` : label} onClick={() => onSelect(id)}>
            <Icon className="size-[22px]" strokeWidth={tab === id ? 2.25 : 1.75} aria-hidden />
            <span aria-hidden>{label}</span>
            {dot && <span className="tab-bar__dot" aria-hidden />}
          </button>
        )
      })}
    </nav>
  )
}

const SEEN_EVENT = 'rabbit:social-seen' // FriendsScreen fires it after marking the feed seen

/** Pending friend requests or new kudos since Friends was last opened. */
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
