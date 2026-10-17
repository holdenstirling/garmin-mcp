// Code-split screens, tabs and sheets: each loads on first open (its own chunk) behind a
// RabbitLoader, so the first load only carries the Rabbit home/chat. Same names and props
// as the real components, so call sites don't change.
import { Component, lazy, Suspense, type ComponentProps, type ComponentType, type ReactElement, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { RabbitLoader } from '@/components/RabbitLoader'

type Kind = 'tab' | 'screen'

// A screen's loading cover sits over the app like the screen will, so it keeps the way out:
// the X (and Escape/Back via the screen once it loads) closes it even if the chunk is slow.
const HOPS = ['Hopping over…', 'Lacing up…', 'Almost there…']

function Fallback({ kind, onClose }: { kind: Kind; onClose?: () => void }) {
  return kind === 'tab'
    ? <div className="flex min-h-0 flex-1 items-center justify-center p-8"><RabbitLoader label="Loading" cycle={HOPS} /></div>
    : (
      // The dimmed backdrop waits as long as the loader does, so a quick open never flashes.
      <div className="lazy-fallback fixed inset-0 z-(--z-page) flex items-center justify-center bg-(--bg)/70">
        <RabbitLoader label="Loading" cycle={HOPS} />
        {onClose && (
          <button type="button" className="modal-close absolute right-3 top-[max(10px,env(safe-area-inset-top))]" aria-label="Close" onClick={onClose}>
            <X className="size-4" />
          </button>
        )}
      </div>
    )
}

// A chunk that can't load (offline, after the one reload) shows a way out instead of a blank app.
class LoadFailed extends Component<{ kind: Kind; onClose?: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (!this.state.failed) return this.props.children
    const { kind, onClose } = this.props
    return (
      <div className={kind === 'tab' ? 'flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-8 text-center'
        : 'fixed inset-0 z-(--z-page) flex flex-col items-center justify-center gap-3 bg-(--bg) p-8 text-center'} role="alert">
        <p className="text-[0.8235rem] text-(--text-secondary)">This screen didn't load. Check your connection.</p>
        <div className="flex gap-2">
          <button type="button" className="hit-44 rounded-lg border border-(--border) px-4 py-2 text-[0.8235rem] text-(--text)"
            onClick={() => window.location.reload()}>Reload</button>
          {onClose && (
            <button type="button" className="hit-44 rounded-lg px-4 py-2 text-[0.8235rem] text-(--accent)"
              onClick={() => { this.setState({ failed: false }); onClose() }}>Close</button>
          )}
        </div>
      </div>
    )
  }
}

// After a deploy, a page left open still points at the old screen files, which are gone.
// Reload once to pick up the new version instead of showing a broken screen.
const RELOADED = 'rabbit-chunk-reload'
function fresh<T>(load: () => Promise<T>): Promise<T> {
  return load().then((v) => {
    try { sessionStorage.removeItem(RELOADED) } catch { /* private mode */ }
    return v
  }, (err) => {
    let again = false
    try { again = !sessionStorage.getItem(RELOADED); if (again) sessionStorage.setItem(RELOADED, '1') } catch { /* private mode */ }
    if (again) { window.location.reload(); return new Promise<T>(() => {}) }
    throw err
  })
}

function split<T extends ComponentType<any>>(load: () => Promise<T>, kind: Kind = 'screen'): (props: ComponentProps<T>) => ReactElement {
  const L = lazy(() => fresh(load).then((C) => ({ default: C })))
  function Split(props: ComponentProps<T>) {
    const Any = L as ComponentType<any>
    const onClose = typeof (props as { onClose?: unknown }).onClose === 'function' ? (props as { onClose: () => void }).onClose : undefined
    return (
      <LoadFailed kind={kind} onClose={onClose}>
        <Suspense fallback={<Fallback kind={kind} onClose={onClose} />}><Any {...props} /></Suspense>
      </LoadFailed>
    )
  }
  return Split
}

// Tabs
export const PlanEditor = split(() => import('@/components/plan/PlanEditor').then((m) => m.PlanEditor), 'tab')
export const EventsScreen = split(() => import('@/components/events/EventsScreen').then((m) => m.EventsScreen), 'tab')
export const ExploreScreen = split(() => import('@/components/explore/ExploreScreen').then((m) => m.ExploreScreen), 'tab')
export const StatsScreen = split(() => import('@/components/stats/StatsScreen').then((m) => m.StatsScreen), 'tab')
export const RecapSheet = split(() => import('@/components/recap/RecapSheet').then((m) => m.RecapSheet), 'tab')
export const CommunityScreen = split(() => import('@/components/community/CommunityScreen').then((m) => m.CommunityScreen), 'tab')

// Full-screen screens and sheets
export const MemorySheet = split(() => import('@/components/MemorySheet').then((m) => m.MemorySheet))
export const PlanSheet = split(() => import('@/components/PlanSheet').then((m) => m.PlanSheet))
export const ThreadsSheet = split(() => import('@/components/ThreadsSheet').then((m) => m.ThreadsSheet))
export const AddPlanLauncher = split(() => import('@/components/plan/PlanImport').then((m) => m.AddPlanLauncher))
export const SetupWizard = split(() => import('@/components/plan/SetupWizard').then((m) => m.SetupWizard))
export const ProfileScreen = split(() => import('@/components/plan/ProfileScreen').then((m) => m.ProfileScreen))
export const RacePackScreen = split(() => import('@/components/events/RacePackScreen').then((m) => m.RacePackScreen))
export const RaceWeekScreen = split(() => import('@/components/raceweek/RaceWeekScreen').then((m) => m.RaceWeekScreen))
export const RaceFitScreen = split(() => import('@/components/events/RaceFitScreen').then((m) => m.RaceFitScreen))
export const GearScreen = split(() => import('@/components/gear/GearScreen').then((m) => m.GearScreen))
export const CoachInbox = split(() => import('@/components/coach/CoachInbox').then((m) => m.CoachInbox))
export const CoachesScreen = split(() => import('@/components/coach/CoachesScreen').then((m) => m.CoachesScreen))
export const CoachStatusSheet = split(() => import('@/components/coach/CoachStatusSheet').then((m) => m.CoachStatusSheet))
export const FindCoachScreen = split(() => import('@/components/coach/FindCoachScreen').then((m) => m.FindCoachScreen))
export const CoachApp = split(() => import('@/components/coach/CoachApp').then((m) => m.CoachApp))
export const WorkoutDayScreen = split(() => import('@/components/workout/WorkoutDayScreen').then((m) => m.WorkoutDayScreen))
export const SettingsPanels = split(() => import('@/components/SettingsPanels').then((m) => m.SettingsPanels), 'tab')
// Me -> Connected apps (hub page) and the one connect popup per app
export const ConnectionsScreen = split(() => import('@/components/connect/ConnectionsScreen').then((m) => m.ConnectionsScreen))
export const ConnectSheet = split(() => import('@/components/connect/ConnectSheet').then((m) => m.ConnectSheet))
export const AccessScreen = split(() => import('@/components/settings/AccessScreen').then((m) => m.AccessScreen))
export const MePage = split(() => import('@/components/nav/MePage').then((m) => m.MePage))
export const RewardSheet = split(() => import('@/components/reward/RewardSheet').then((m) => m.RewardSheet))
export const MonthRecapSheet = split(() => import('@/components/reward/MonthRecapSheet').then((m) => m.MonthRecapSheet))
// Me -> Usage (owners only)
// Shared training blocks (blocks.py): the block page and the create flow
export const BlockScreen = split(() => import('@/components/blocks/BlockScreen').then((m) => m.BlockScreen))
export const UsageScreen = split(() => import('@/components/settings/UsageScreen').then((m) => m.UsageScreen))
// Me -> Partners (owners only)
export const PartnersScreen = split(() => import('@/components/settings/PartnersScreen').then((m) => m.PartnersScreen))
