// The athlete-profile fields shared by the setup wizard and Settings > Training profile:
// about you, training numbers, and your week.
import { useEffect, useState } from 'react'
import { DurationInput } from '@/components/ui/DurationInput'
import { Plus, Trash2, Watch } from 'lucide-react'
import type { Sport } from '@/lib/api'
import {
  EQUIPMENT, FAVORITE_SPORTS, KM_PER_MI, M_PER_FT, TERRAIN, TRAITS, WEEKDAYS, cmToFtIn, fmtPace, guessUnits, ftInToCm, kgToLb, lbToKg, parsePace,
  type AthleteFull, type PastRace,
} from '@/lib/plan'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Choice, Field, MultiChoice, NumberStepper, OptionCard, areaCls, inputCls } from './ui'

type Props = { a: Partial<AthleteFull>; setA: (p: Partial<AthleteFull>) => void; sports: Sport[] }

export function YouFields({ a, setA }: Props) {
  const imperial = (a.units ?? guessUnits()) === 'imperial'
  return (
    <>
      <UnitsToggle a={a} setA={setA} />
      <Card>
        <Field label="Favorite sports" hint="What you love doing. Rabbit leans your training and stats toward these.">
          <MultiChoice value={(a.favorite_sports ?? []) as typeof FAVORITE_SPORTS[number][0][]} options={FAVORITE_SPORTS}
            onChange={(v) => setA({ favorite_sports: v })} />
        </Field>
      </Card>
      <div className="flex flex-col gap-2">
        <OptionCard selected={a.level === 'new'} title="New to this" description="First race at this distance, or under a year of steady training." onClick={() => setA({ level: 'new' })} />
        <OptionCard selected={a.level === 'intermediate'} title="A few seasons in" description="You've done races like this and train most weeks." onClick={() => setA({ level: 'intermediate' })} />
        <OptionCard selected={a.level === 'advanced'} title="Experienced" description="Years of structured training; you handle big weeks." onClick={() => setA({ level: 'advanced' })} />
      </div>
      <Card>
        <Field label="Sex" hint="Optional. Helps Rabbit read heart-rate and recovery data.">
          <Choice value={a.sex ?? null} allowNone onChange={(v) => setA({ sex: v })} options={[['female', 'Female'], ['male', 'Male'], ['other', 'Other']]} />
        </Field>
        <Field label="Age">
          <NumberStepper label="age" value={a.age} min={10} max={100} typical={[25, 30, 35, 40, 45, 50]}  onChange={(v) => setA({ age: v })} suffix="years" />
        </Field>
        <Field label="Height">
          {imperial ? (
            <HeightImperial cm={a.height_cm ?? null} onChange={(cm) => setA({ height_cm: cm })} />
          ) : (
            <NumberStepper label="height" value={a.height_cm} min={100} max={250} typical={[160, 165, 170, 175, 180, 185]}  onChange={(v) => setA({ height_cm: v })} suffix="cm" />
          )}
        </Field>
        <Field label="Weight">
          {imperial ? (
            <NumberStepper label="weight" value={a.weight_kg ? kgToLb(a.weight_kg) : null} min={66} max={550} typical={[130, 150, 170, 190, 210]} 
              onChange={(v) => setA({ weight_kg: v == null ? null : lbToKg(v) })} suffix="lb" />
          ) : (
            <NumberStepper label="weight" value={a.weight_kg} min={30} max={250} step={0.5} decimals={1} typical={[55, 65, 75, 85, 95]} 
              onChange={(v) => setA({ weight_kg: v })} suffix="kg" />
          )}
        </Field>
      </Card>
      <Card>
        <Field label="Injuries or limits" hint="Optional. Rabbit keeps these in mind in every brief.">
          <textarea className={areaCls} value={a.injuries ?? ''} maxLength={500} onChange={(e) => setA({ injuries: e.target.value })}
            placeholder="e.g. Achilles gets cranky above 40 km a week" />
        </Field>
      </Card>
    </>
  )
}

export function NumbersFields({ a, setA, sports }: Props) {
  const imperial = (a.units ?? guessUnits()) === 'imperial'
  return (
    <>
      <UnitsToggle a={a} setA={setA} />
      <Card>
        <Field label="Resting heart rate">
          <NumberStepper label="resting heart rate" value={a.resting_hr} min={25} max={120} typical={[45, 50, 55, 60, 65]}  onChange={(v) => setA({ resting_hr: v })} suffix="bpm" />
        </Field>
        <Field label="Max heart rate">
          <NumberStepper label="max heart rate" value={a.max_hr} min={100} max={230} typical={[175, 180, 185, 190, 195]}  onChange={(v) => setA({ max_hr: v })} suffix="bpm" />
        </Field>
        <Field label="Threshold heart rate" hint="Roughly your average heart rate for an all-out hour.">
          <NumberStepper label="threshold heart rate" value={a.threshold_hr} min={80} max={220} typical={[155, 160, 165, 170, 175]}  onChange={(v) => setA({ threshold_hr: v })} suffix="bpm" />
        </Field>
      </Card>
      <Card>
        {sports.includes('bike') && (
          <Field label="Cycling FTP" hint={a.weight_kg && a.ftp_w ? `${(a.ftp_w / a.weight_kg).toFixed(1)} W/kg. Bike workouts target power.` : 'Bike workouts target power when you have a power meter.'}>
            <NumberStepper label="FTP" value={a.ftp_w} min={50} max={600} step={5} typical={[150, 200, 250, 300]}  onChange={(v) => setA({ ftp_w: v })} suffix="watts" />
          </Field>
        )}
        {sports.includes('run') && (
          <Field label={`Threshold run pace (per ${imperial ? 'mile' : 'km'})`} hint="About your 10K-to-half-marathon race pace. Run workouts target pace.">
            <PaceInput seconds={a.run_threshold_pace == null ? null : imperial ? a.run_threshold_pace * KM_PER_MI : a.run_threshold_pace}
              placeholder={imperial ? '7:15' : '4:30'}
              onChange={(s) => setA({ run_threshold_pace: s == null ? null : Math.round(imperial ? s / KM_PER_MI : s) })} />
          </Field>
        )}
        {sports.includes('swim') && (
          <Field label="Swim CSS (per 100 m)" hint="Your sustainable pace for a hard 1500 m. Sets swim distances.">
            <PaceInput seconds={a.swim_css ?? null} placeholder="1:45" onChange={(s) => setA({ swim_css: s })} />
          </Field>
        )}
      </Card>
    </>
  )
}

export function WeekFields({ a, setA, sports }: Props) {
  return (
    <>
      <Card>
        <Field label="Hours a week right now" hint="Average of the last month. Garmin's history helps if you're unsure.">
          <NumberStepper label="hours per week" value={a.weekly_hours} min={1} max={30} step={0.5} decimals={1} typical={[4, 6, 8, 10, 12]} 
            onChange={(v) => setA({ weekly_hours: v })} suffix="hours" />
        </Field>
        {sports.includes('run') && (
          <Field label="Longest run in the last month (optional)" hint="Your first long run starts here, not above it. Skip it if you're not sure.">
            <NumberStepper label="minutes" value={a.longest_run_min} min={10} max={240} step={5} typical={[20, 30, 45, 60, 90]}
              onChange={(v) => setA({ longest_run_min: v })} suffix="min" />
          </Field>
        )}
        {sports.includes('bike') && (
          <Field label="Longest ride in the last month (optional)" hint="Your first long ride starts here, not above it.">
            <NumberStepper label="minutes" value={a.longest_ride_min} min={15} max={420} step={15} typical={[30, 60, 90, 120, 180]}
              onChange={(v) => setA({ longest_ride_min: v })} suffix="min" />
          </Field>
        )}
        <Field label="Training days" hint={(a.available_days ?? []).length < 3 ? 'Three or more days works best.' : `${(a.available_days ?? []).length} days a week. The rest are rest days.`}>
          <MultiChoice value={a.available_days ?? []} options={WEEKDAYS} onChange={(v) => setA({ available_days: v, long_day: v.includes(a.long_day ?? '') ? a.long_day : v[v.length - 1] ?? null })} />
        </Field>
        <Field label="Long-session day" hint={sports.includes('bike') && sports.includes('run') ? 'Your long ride (or brick). The long run goes the day after.' : 'Your longest workout of the week.'}>
          <Choice value={a.long_day ?? null} onChange={(v) => setA({ long_day: v })}
            options={WEEKDAYS.filter(([d]) => (a.available_days ?? []).includes(d))} />
        </Field>
      </Card>
      <Card>
        <Field label="What do you have access to?" hint={sports.includes('swim') && !(a.equipment ?? []).some((e) => e === 'pool' || e === 'open_water') && (a.equipment ?? []).length ? 'No pool or open water selected, so Rabbit will leave out swims.' : 'Optional.'}>
          <MultiChoice value={(a.equipment ?? []) as typeof EQUIPMENT[number][0][]} options={EQUIPMENT} onChange={(v) => setA({ equipment: v })} />
        </Field>
      </Card>
    </>
  )
}

/** Where you train, strengths and limiters, heat, why you race: used by Race fit and Rabbit. */
export function TraitsFields({ a, setA }: Props) {
  const imperial = (a.units ?? guessUnits()) === 'imperial'
  const elev = a.home_elevation_m ?? null
  const acclim = a.altitude_acclimatized == null ? null : a.altitude_acclimatized ? 'yes' : 'no'
  return (
    <>
      <UnitsToggle a={a} setA={setA} />
      <Card>
        <Field label="Home base" hint="Where you live and train most.">
          <input className={inputCls} value={a.home_location ?? ''} maxLength={80} placeholder="e.g. Denver, CO"
            onChange={(e) => setA({ home_location: e.target.value })} />
        </Field>
        <Field label="Home elevation" className="border-t border-(--border)" hint="Race fit compares it with your races.">
          {imperial ? (
            <NumberStepper label="home elevation" value={elev == null ? null : Math.round(elev / M_PER_FT / 10) * 10} min={0} max={18000} step={100}
              onChange={(v) => setA({ home_elevation_m: v == null ? null : Math.min(5500, Math.round(v * M_PER_FT)) })} suffix="ft" />
          ) : (
            <NumberStepper label="home elevation" value={elev} min={0} max={5500} step={50}
              onChange={(v) => setA({ home_elevation_m: v })} suffix="m" />
          )}
        </Field>
        <Field label="Live or train above 1,500 m (5,000 ft)?" className="border-t border-(--border)">
          <Choice value={acclim} allowNone options={[['yes', 'Yes'], ['no', 'No']] as const}
            onChange={(v) => setA({ altitude_acclimatized: v == null ? null : v === 'yes' })} />
        </Field>
        <Field label="Terrain you can train on" className="border-t border-(--border)">
          <MultiChoice value={a.terrain_access ?? []} options={TERRAIN} onChange={(v) => setA({ terrain_access: v })} />
        </Field>
      </Card>
      <Card>
        <Field label="Years of training">
          <NumberStepper label="years of training" value={a.years_training} min={0} max={60} typical={[1, 3, 5, 10]}  onChange={(v) => setA({ years_training: v })} suffix="years" />
        </Field>
        <Field label="Strengths" className="border-t border-(--border)">
          <MultiChoice value={a.strengths ?? []} options={TRAITS} onChange={(v) => setA({ strengths: v })} />
        </Field>
        <Field label="Limiters" className="border-t border-(--border)" hint="What slows you down. Race fit and Rabbit plan around these.">
          <MultiChoice value={a.limiters ?? []} options={TRAITS} onChange={(v) => setA({ limiters: v })} />
        </Field>
        <Field label="Heat tolerance" className="border-t border-(--border)">
          <Choice value={a.heat_tolerance ?? null} allowNone options={[['low', 'Struggle'], ['normal', 'Normal'], ['high', 'Thrive']] as const}
            onChange={(v) => setA({ heat_tolerance: v })} />
        </Field>
        <Field label="Sweat" className="border-t border-(--border)" hint="Salty: white streaks on your kit or stinging eyes.">
          <Choice value={a.sweat ?? null} allowNone options={[['light', 'Light'], ['average', 'Average'], ['heavy', 'Heavy'], ['salty', 'Salty']] as const}
            onChange={(v) => setA({ sweat: v })} />
        </Field>
      </Card>
      <Card>
        <Field label="Why you race" hint="Rabbit reminds you of this when training gets hard.">
          <textarea className={areaCls} value={a.motivation ?? ''} maxLength={200} onChange={(e) => setA({ motivation: e.target.value })} />
        </Field>
      </Card>
      <RaceHistoryField races={a.race_history ?? []} onChange={(v) => setA({ race_history: v })} />
    </>
  )
}

const MAX_RACES = 10

function RaceHistoryField({ races, onChange }: { races: PastRace[]; onChange: (v: PastRace[]) => void }) {
  const set = (i: number, p: Partial<PastRace>) => onChange(races.map((r, j) => (j === i ? { ...r, ...p } : r)))
  return (
    <Card>
      <Field label="Past races" hint="Up to 10. Races without a name aren't saved.">
        <div className="flex flex-col gap-3">
          {races.map((r, i) => (
            <div key={i} className="flex flex-col gap-1.5 rounded-lg bg-(--bg-inset) p-2.5">
              <div className="flex gap-2">
                <input className={inputCls} value={r.name} maxLength={60} placeholder="Race name" aria-label="Race name"
                  onChange={(e) => set(i, { name: e.target.value })} />
                <button type="button" aria-label="Remove race" className="hit-44 shrink-0 rounded p-2 text-(--danger)"
                  onClick={() => onChange(races.filter((_, j) => j !== i))}><Trash2 className="size-4" /></button>
              </div>
              <div className="flex gap-2">
                <input className={inputCls} value={r.date} maxLength={10} placeholder="2024-06" aria-label="When"
                  onChange={(e) => set(i, { date: e.target.value.trim() })} />
                <input className={inputCls} value={r.distance} maxLength={20} placeholder="Distance" aria-label="Distance"
                  onChange={(e) => set(i, { distance: e.target.value })} />
                <input className={inputCls} value={r.result} maxLength={40} placeholder="Result" aria-label="Result"
                  onChange={(e) => set(i, { result: e.target.value })} />
              </div>
            </div>
          ))}
          {races.length < MAX_RACES && (
            <Button variant="default" className="h-9 w-fit gap-1 px-3 text-[0.7647rem]"
              onClick={() => onChange([...races, { name: '', date: '', distance: '', result: '' }])}>
              <Plus className="size-4" /> Add a race
            </Button>
          )}
        </div>
      </Field>
    </Card>
  )
}

/** US or metric, at the top of every step with numbers. Changing it converts nothing: values are
 *  stored metric and only shown in the athlete's units. */
export function UnitsToggle({ a, setA }: Pick<Props, 'a' | 'setA'>) {
  return (
    <div className="flex items-center justify-between gap-3 px-1">
      <span id="units-label" className="text-[0.7647rem] text-(--text-secondary)">Units</span>
      <div role="radiogroup" aria-labelledby="units-label" className="flex rounded-full border border-(--border) p-0.5">
        {([['imperial', 'Miles', 'mi · lb · ft'], ['metric', 'Kilometers', 'km · kg · m']] as const).map(([v, name, hint]) => {
          const on = (a.units ?? guessUnits()) === v
          return (
            <button key={v} type="button" role="radio" aria-checked={on} onClick={() => setA({ units: v })}
              className={cn('hit-44 flex min-h-9 flex-col items-center rounded-full px-3.5 py-1 leading-tight',
                on ? 'bg-(--accent) text-(--on-fill)' : 'text-(--text-secondary)')}>
              <span className="text-[0.7647rem] font-semibold">{name}</span>
              <span className={cn('text-[0.6471rem]', on ? 'opacity-90' : 'text-(--text-muted)')}>{hint}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function GarminFill({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={busy}
      className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5 text-left disabled:opacity-60">
      {busy
        ? <RabbitLoader inline size={18} className="min-w-0 flex-1 text-[0.8235rem] text-(--accent)" label="Asking Garmin…" />
        : <>
          <Watch className="size-4 shrink-0 text-(--accent)" />
          <span className="min-w-0 flex-1 text-[0.8235rem] text-(--accent)">Fill in from Garmin</span>
        </>}
    </button>
  )
}

export function HeightImperial({ cm, onChange }: { cm: number | null; onChange: (cm: number | null) => void }) {
  const { ft, inch } = cm ? cmToFtIn(cm) : { ft: 5, inch: 9 }
  return (
    <div className="flex gap-3">
      <div className="flex-1"><NumberStepper label="feet" value={cm ? ft : null} min={3} max={8} typical={[5, 6]}  onChange={(v) => onChange(v == null ? null : ftInToCm(v, inch))} suffix="ft" /></div>
      <div className="flex-1"><NumberStepper label="inches" value={cm ? inch : null} min={0} max={11} onChange={(v) => onChange(v == null ? null : ftInToCm(ft, v))} suffix="in" /></div>
    </div>
  )
}

export function PaceInput({ seconds, onChange, placeholder }: { seconds: number | null; onChange: (s: number | null) => void; placeholder: string }) {
  const [text, setText] = useState(seconds != null ? fmtPace(seconds) : '')
  const [bad, setBad] = useState(false)
  useEffect(() => { setText(seconds != null ? fmtPace(seconds) : '') }, [seconds])
  return (
    <div className="flex flex-col gap-1">
      <DurationInput label="Pace" withHours={false} placeholder={placeholder} value={text} onChange={setText}
        onBlur={(v) => {
          if (!v.trim()) { setBad(false); onChange(null); return }
          const s = parsePace(v)
          setBad(s == null)
          if (s != null) onChange(s)
        }} />
      {bad && <span role="alert" className="text-[0.7059rem] text-(--danger)">Enter minutes and seconds, like {placeholder}.</span>}
    </div>
  )
}

