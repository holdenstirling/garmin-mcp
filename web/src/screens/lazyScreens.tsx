// Code-split screens, tabs and sheets: each loads on first open (its own chunk) behind a
// RabbitLoader, so the first load only carries the Rabbit home/chat. Same names and props
// as the real components, so call sites don't change.
import { lazy, Suspense, type ComponentProps, type ComponentType, type ReactElement } from 'react'
import { RabbitLoader } from '@/components/RabbitLoader'

type Kind = 'tab' | 'screen'

function Fallback({ kind }: { kind: Kind }) {
  return kind === 'tab'
    ? <div className="flex min-h-0 flex-1 items-center justify-center p-8"><RabbitLoader label="Loading…" /></div>
    : <div className="fixed inset-0 z-50 flex items-center justify-center bg-(--bg)/70"><RabbitLoader label="Loading…" /></div>
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
    return <Suspense fallback={<Fallback kind={kind} />}><Any {...props} /></Suspense>
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
export const RaceFitScreen = split(() => import('@/components/events/RaceFitScreen').then((m) => m.RaceFitScreen))
export const GearScreen = split(() => import('@/components/gear/GearScreen').then((m) => m.GearScreen))
export const CoachInbox = split(() => import('@/components/coach/CoachInbox').then((m) => m.CoachInbox))
export const CoachesScreen = split(() => import('@/components/coach/CoachesScreen').then((m) => m.CoachesScreen))
export const CoachStatusSheet = split(() => import('@/components/coach/CoachStatusSheet').then((m) => m.CoachStatusSheet))
export const FindCoachScreen = split(() => import('@/components/coach/FindCoachScreen').then((m) => m.FindCoachScreen))
export const CoachApp = split(() => import('@/components/coach/CoachApp').then((m) => m.CoachApp))
export const WorkoutDayScreen = split(() => import('@/components/workout/WorkoutDayScreen').then((m) => m.WorkoutDayScreen))
export const SettingsPanels = split(() => import('@/components/SettingsPanels').then((m) => m.SettingsPanels), 'tab')
export const DataSourcesSheet = split(() => import('@/components/settings/DataSourcesSheet').then((m) => m.DataSourcesSheet))
export const MePage = split(() => import('@/components/nav/MePage').then((m) => m.MePage))
export const RewardSheet = split(() => import('@/components/reward/RewardSheet').then((m) => m.RewardSheet))
export const MonthRecapSheet = split(() => import('@/components/reward/MonthRecapSheet').then((m) => m.MonthRecapSheet))
