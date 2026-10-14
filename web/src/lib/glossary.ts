// Plain-language explanations for training terms, shown by <InfoTip>. Keep each to a sentence or two.

export type Term =
  | 'form' | 'fitness' | 'fatigue' | 'readiness' | 'garmin_readiness' | 'oura_readiness'
  | 'xp' | 'streak' | 'b_race' | 'c_race' | 'phase' | 'race_fit' | 'rpe' | 'adherence'
  | 'training_load' | 'ramp_rate' | 'eighty_twenty' | 'hrv' | 'long_session'

export const GLOSSARY: Record<Term, { title: string; text: string }> = {
  form: { title: 'Form', text: 'How fresh you are: positive = rested, negative = tired from recent training.' },
  fitness: { title: 'Fitness', text: 'Your training load over the last 6 weeks. It rises slowly as you train consistently.' },
  fatigue: { title: 'Fatigue', text: 'Your training load over the last week. It rises fast after hard days and drops with rest.' },
  readiness: { title: 'Readiness', text: 'A 0 to 100 score from your watch or ring for how ready your body is to train today. Higher is better.' },
  garmin_readiness: { title: 'Garmin readiness', text: "Garmin's 0 to 100 score from your sleep, HRV, recovery time and recent load. Higher means ready to train hard." },
  oura_readiness: { title: 'Oura readiness', text: "Oura's 0 to 100 score from your sleep, resting heart rate, HRV and temperature. Higher means better recovered." },
  xp: { title: 'XP', text: 'Points for workouts, finished plan sessions and setup steps. XP adds up to your level.' },
  streak: { title: 'Streak', text: 'Days in a row with a workout. Rest days your plan schedules, plus one free rest day a week, never break it.' },
  b_race: { title: 'B race', text: 'A race that matters but is not your main goal. Your plan eases off a little before it, without a full taper.' },
  c_race: { title: 'C race', text: 'A race you do as training. Your plan keeps going straight through it.' },
  phase: { title: 'Phase', text: 'Base builds your endurance, Build adds race-specific intensity, Peak is your hardest training, Taper cuts volume so you arrive fresh.' },
  race_fit: { title: 'Race fit', text: 'How well your recent training matches what this race asks of you: distance, climbing and duration.' },
  rpe: { title: 'RPE', text: 'Rate of perceived effort: how hard it felt, from 1 (very easy) to 10 (all-out).' },
  adherence: { title: 'Adherence', text: 'The share of your planned sessions you actually did.' },
  training_load: { title: 'Training load', text: 'One number for how much a workout asked of you: its time multiplied by how hard it was. An easy hour is about 50.' },
  ramp_rate: { title: 'Ramp rate', text: 'How fast your weekly training load is rising. Jumps of more than about 30% in a week raise injury risk.' },
  eighty_twenty: { title: '80/20 guideline', text: 'Endurance athletes improve most with about 80% of training time easy (you could chat) and 20% hard.' },
  hrv: { title: 'HRV', text: 'Heart rate variability: the tiny changes between heartbeats overnight. Higher than your usual usually means well recovered.' },
  long_session: { title: 'Long session', text: 'Your longest workout of the week in your race sport. It builds the endurance race day needs.' },
}
