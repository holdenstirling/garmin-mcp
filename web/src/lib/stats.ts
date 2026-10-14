// Stats screen data: streaks, totals, weekly volume, calendar, bests, badges, plan adherence.
import { getJSON } from '@/lib/api'
import { fmtClimb, fmtDist, fmtDuration } from '@/lib/format'

export type Sport = 'run' | 'bike' | 'swim' | 'brick' | 'strength' | 'hike' | 'climb' | 'ski' | 'paddle' | 'rest' | 'other'

export type Totals = { workouts: number; hours: number; km: number; climb_m: number; days: number; vs_last_week_hours?: number }
export type Best = { value: number; date: string; name: string; sport: Sport }
export type Badge = { id: string; title: string; description: string; earned: boolean; progress: number }
export type Stats = {
  today: string; units: 'metric' | 'imperial'
  streak: { current: number; best: number; today_done: boolean; weeks_current: number; weeks_best: number; active_week: number }
  totals: { week: Totals; month: Totals; year: Totals }
  weekly: { start: string; hours: number; workouts: number; by_sport: Partial<Record<Sport, number>> }[]
  calendar: { start: string; days: Record<string, number> }
  by_sport: (Totals & { sport: Sport; favorite: boolean; longest_min: number })[]
  bests: Partial<Record<'longest_workout_min' | 'longest_run_km' | 'longest_ride_km' | 'longest_swim_km' | 'biggest_climb_m', Best>>
  badges: Badge[]
  plan: null | {
    week: { done: number; planned: number; due: number; minutes_done: number; minutes_planned: number } | null
    to_date: { done: number; planned: number; pct: number | null }
    perfect_weeks: number
    recent_weeks: { start: string; done: number; planned: number }[]
  }
  recent: { date: string; name: string; sport: Sport; minutes: number; km: number; id: number }[]
  headline: string
}

export const getStats = (fresh = false) => getJSON<Stats>(`/api/stats${fresh ? '?fresh=1' : ''}`)

export const SPORT_COLOR: Record<Sport, string> = {
  run: '#3f9a70', bike: '#d0952f', swim: '#3a86c8', brick: '#8b62c9', strength: '#c45d74', hike: '#8d7b4f',
  climb: '#b5683a', ski: '#5fa9c9', paddle: '#4a9e9a', rest: '#7a8a84', other: '#7a8a84',
}
export const SPORT_NAME: Record<Sport, string> = {
  run: 'Run', bike: 'Bike', swim: 'Swim', brick: 'Multisport', strength: 'Strength & yoga', hike: 'Hike & walk',
  climb: 'Climb', ski: 'Ski', paddle: 'Row & paddle', rest: 'Rest', other: 'Other',
}

export function dist(km: number, units: Stats['units'], sport?: Sport): string {
  return fmtDist(km, units === 'imperial', sport)
}
export function climb(m: number, units: Stats['units']): string {
  return fmtClimb(m, units === 'imperial')
}
export function hours(h: number): string {
  return fmtDuration(h * 60)
}
