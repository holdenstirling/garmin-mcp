// Every sport an event can be (server: sports.py, kept in step by tests/test_event_sports.py):
// the event form's sport dropdown, grouped, with an icon each. The pick is stored as the event's
// `activity`; the server derives the coarse event `type` from it (race distances, the plan).
import {
  Activity, Bike, CircleDot, Disc3, Dribbble, Dumbbell, Flag, Flower2, Footprints, Gauge, Goal, Layers, Mountain,
  MountainSnow, Music, PersonStanding, Sailboat, Shield, Snowflake, Swords, Target, Timer, Trophy, Volleyball,
  Waves,
} from 'lucide-react'
import type { ActivityId } from '@/lib/activity'
import type { EventType } from '@/lib/events'

export type SportId = (typeof SPORTS)[number][0]

/** [id, label, group] in dropdown order (server sports.CATALOG order). */
export const SPORTS = [
  ['road_run', 'Road running', 'Running'],
  ['trail_run', 'Trail running', 'Running'],
  ['track', 'Track', 'Running'],
  ['ultra', 'Ultra running', 'Running'],
  ['cross_country', 'Cross-country', 'Running'],
  ['triathlon', 'Triathlon', 'Multisport'],
  ['duathlon', 'Duathlon', 'Multisport'],
  ['aquathlon', 'Aquathlon', 'Multisport'],
  ['road_ride', 'Road cycling', 'Cycling'],
  ['gravel', 'Gravel', 'Cycling'],
  ['mtb', 'Mountain biking', 'Cycling'],
  ['cyclocross', 'Cyclocross', 'Cycling'],
  ['indoor_ride', 'Indoor cycling', 'Cycling'],
  ['pool_swim', 'Pool swimming', 'Swimming'],
  ['open_water', 'Open water swimming', 'Swimming'],
  ['walking', 'Walking', 'Outdoors'],
  ['hiking', 'Hiking', 'Outdoors'],
  ['mountaineering', 'Mountaineering', 'Outdoors'],
  ['climbing', 'Climbing', 'Outdoors'],
  ['bouldering', 'Bouldering', 'Outdoors'],
  ['rowing', 'Rowing', 'Water'],
  ['paddleboard', 'Paddleboarding', 'Water'],
  ['kayak', 'Kayaking', 'Water'],
  ['alpine_ski', 'Alpine skiing', 'Snow'],
  ['nordic_ski', 'Nordic skiing', 'Snow'],
  ['skimo', 'Ski mountaineering', 'Snow'],
  ['snowboard', 'Snowboarding', 'Snow'],
  ['volleyball', 'Volleyball', 'Team sports'],
  ['beach_volleyball', 'Beach volleyball', 'Team sports'],
  ['soccer', 'Soccer', 'Team sports'],
  ['basketball', 'Basketball', 'Team sports'],
  ['softball', 'Softball', 'Team sports'],
  ['kickball', 'Kickball', 'Team sports'],
  ['flag_football', 'Flag football', 'Team sports'],
  ['ultimate', 'Ultimate frisbee', 'Team sports'],
  ['hockey', 'Hockey', 'Team sports'],
  ['rugby', 'Rugby', 'Team sports'],
  ['lacrosse', 'Lacrosse', 'Team sports'],
  ['pickleball', 'Pickleball', 'Racket sports'],
  ['tennis', 'Tennis', 'Racket sports'],
  ['padel', 'Padel', 'Racket sports'],
  ['badminton', 'Badminton', 'Racket sports'],
  ['squash', 'Squash', 'Racket sports'],
  ['yoga', 'Yoga', 'Fitness'],
  ['pilates', 'Pilates', 'Fitness'],
  ['hiit', 'CrossFit / HIIT', 'Fitness'],
  ['hyrox', 'HYROX', 'Fitness'],
  ['strength', 'Strength training', 'Fitness'],
  ['spin', 'Spin class', 'Fitness'],
  ['golf', 'Golf', 'More'],
  ['dance', 'Dance', 'More'],
  ['martial_arts', 'Martial arts', 'More'],
  ['other', 'Something else', 'More'],
] as const

export const SPORT_LABEL = Object.fromEntries(SPORTS.map(([id, label]) => [id, label])) as Record<SportId, string>
export const isSport = (v: unknown): v is SportId => typeof v === 'string' && v in SPORT_LABEL

/** The dropdown's groups, in order. */
export const SPORT_GROUPS: { group: string; sports: { id: SportId; label: string }[] }[] = (() => {
  const out: { group: string; sports: { id: SportId; label: string }[] }[] = []
  for (const [id, label, group] of SPORTS) {
    let g = out.find((x) => x.group === group)
    if (!g) { g = { group, sports: [] }; out.push(g) }
    g.sports.push({ id, label })
  }
  return out
})()

/** Coarse event type for each sport (server sports.event_type), so the form can offer race distances. */
export const SPORT_TYPE: Record<SportId, EventType> = {
  road_run: 'running', trail_run: 'trail', track: 'running', ultra: 'trail', cross_country: 'running',
  triathlon: 'triathlon', duathlon: 'duathlon', aquathlon: 'other',
  road_ride: 'cycling', gravel: 'cycling', mtb: 'cycling', cyclocross: 'cycling', indoor_ride: 'cycling',
  pool_swim: 'swimming', open_water: 'swimming',
  walking: 'other', hiking: 'mountaineering', mountaineering: 'mountaineering', climbing: 'other', bouldering: 'other',
  rowing: 'other', paddleboard: 'other', kayak: 'other',
  alpine_ski: 'other', nordic_ski: 'other', skimo: 'other', snowboard: 'other',
  volleyball: 'team_sport', beach_volleyball: 'team_sport', soccer: 'team_sport', basketball: 'team_sport',
  softball: 'team_sport', kickball: 'team_sport', flag_football: 'team_sport', ultimate: 'team_sport',
  hockey: 'team_sport', rugby: 'team_sport', lacrosse: 'team_sport',
  pickleball: 'team_sport', tennis: 'team_sport', padel: 'team_sport', badminton: 'team_sport', squash: 'team_sport',
  yoga: 'other', pilates: 'other', hiit: 'other', hyrox: 'hyrox', strength: 'other', spin: 'cycling',
  golf: 'other', dance: 'other', martial_arts: 'other', other: 'other',
}

/** A sensible default sport for an event saved before sports existed (from its type). */
export const TYPE_SPORT: Record<EventType, SportId> = {
  triathlon: 'triathlon', running: 'road_run', trail: 'trail_run', cycling: 'road_ride', swimming: 'pool_swim',
  duathlon: 'duathlon', mountaineering: 'mountaineering', team_sport: 'volleyball', hyrox: 'hyrox', other: 'other',
}

/** Local's activity filter (lib/activity) for each sport, so a sport also filters and colors like its group. */
export const SPORT_ACTIVITY: Record<SportId, ActivityId> = {
  road_run: 'run', trail_run: 'trail', track: 'run', ultra: 'trail', cross_country: 'run',
  triathlon: 'tri', duathlon: 'tri', aquathlon: 'tri',
  road_ride: 'ride', gravel: 'ride', mtb: 'ride', cyclocross: 'ride', indoor_ride: 'ride',
  pool_swim: 'swim', open_water: 'swim',
  walking: 'other', hiking: 'trail', mountaineering: 'climbing', climbing: 'climbing', bouldering: 'climbing',
  rowing: 'other', paddleboard: 'other', kayak: 'other',
  alpine_ski: 'other', nordic_ski: 'other', skimo: 'other', snowboard: 'other',
  volleyball: 'volleyball', beach_volleyball: 'volleyball', soccer: 'soccer', basketball: 'basketball',
  softball: 'other', kickball: 'other', flag_football: 'other', ultimate: 'other', hockey: 'other',
  rugby: 'other', lacrosse: 'other',
  pickleball: 'pickleball', tennis: 'other', padel: 'other', badminton: 'other', squash: 'other',
  yoga: 'yoga', pilates: 'yoga', hiit: 'other', hyrox: 'other', strength: 'other', spin: 'ride',
  golf: 'other', dance: 'other', martial_arts: 'other', other: 'other',
}

/** One icon per sport (lucide 0.575 names). */
export const SPORT_ICON: Record<SportId, typeof Bike> = {
  road_run: Footprints, trail_run: Mountain, track: Timer, ultra: Mountain, cross_country: Footprints,
  triathlon: Layers, duathlon: Layers, aquathlon: Layers,
  road_ride: Bike, gravel: Bike, mtb: Bike, cyclocross: Bike, indoor_ride: Gauge,
  pool_swim: Waves, open_water: Waves,
  walking: PersonStanding, hiking: Mountain, mountaineering: MountainSnow, climbing: MountainSnow, bouldering: MountainSnow,
  rowing: Sailboat, paddleboard: Sailboat, kayak: Sailboat,
  alpine_ski: Snowflake, nordic_ski: Snowflake, skimo: Snowflake, snowboard: Snowflake,
  volleyball: Volleyball, beach_volleyball: Volleyball, soccer: Goal, basketball: Dribbble, softball: Target,
  kickball: CircleDot, flag_football: Flag, ultimate: Disc3, hockey: Shield, rugby: Trophy, lacrosse: Trophy,
  pickleball: CircleDot, tennis: CircleDot, padel: CircleDot, badminton: CircleDot, squash: CircleDot,
  yoga: Flower2, pilates: Flower2, hiit: Dumbbell, hyrox: Dumbbell, strength: Dumbbell, spin: Gauge,
  golf: Flag, dance: Music, martial_arts: Swords, other: Activity,
}

/** The sport an event is (its own pick, else a default from its type; null for none). */
export function sportOf(e: { activity?: string | null; type?: string | null } | null | undefined): SportId | null {
  if (e && isSport(e.activity)) return e.activity
  return e?.type && e.type in TYPE_SPORT ? TYPE_SPORT[e.type as EventType] : null
}

/** "Volleyball" / the free-text name for Something else. */
export function sportLabel(e: { activity?: string | null; activity_other?: string | null; type?: string | null }): string | null {
  if (e.activity === 'other' && e.activity_other) return e.activity_other
  const s = sportOf(e)
  return s ? SPORT_LABEL[s] : null
}

