// The athlete-profile fields shared by the setup wizard and Settings > Training profile:
// about you, training numbers, and your week.
import { useEffect, useState } from 'react'
import { Watch } from 'lucide-react'
import type { Sport } from '@/lib/api'
import {
  EQUIPMENT, KM_PER_MI, WEEKDAYS, cmToFtIn, fmtPace, ftInToCm, kgToLb, lbToKg, parsePace, type AthleteFull,
} from '@/lib/plan'
import { Card, Choice, Field, MultiChoice, NumberStepper, OptionCard, areaCls, inputCls } from './ui'

type Props = { a: Partial<AthleteFull>; setA: (p: Partial<AthleteFull>) => void; sports: Sport[] }

export function YouFields({ a, setA }: Props) {
  const imperial = a.units === 'imperial'
  return (
    <>
      <div className="flex flex-col gap-2">
        <OptionCard selected={a.level === 'new'} title="New to this" description="First race at this distance, or under a year of steady training." onClick={() => setA({ level: 'new' })} />
        <OptionCard selected={a.level === 'intermediate'} title="A few seasons in" description="You've done races like this and train most weeks." onClick={() => setA({ level: 'intermediate' })} />
        <OptionCard selected={a.level === 'advanced'} title="Experienced" description="Years of structured training; you handle big weeks." onClick={() => setA({ level: 'advanced' })} />
      </div>
      <Card>
        <Field label="Units">
          <Choice value={a.units ?? 'metric'} onChange={(v) => setA({ units: v ?? 'metric' })} options={[['metric', 'Metric'], ['imperial', 'Imperial']]} />
        </Field>
        <Field label="Sex" hint="Optional. Helps Rabbit read heart-rate and recovery data.">
          <Choice value={a.sex ?? null} allowNone onChange={(v) => setA({ sex: v })} options={[['female', 'Female'], ['male', 'Male'], ['other', 'Other']]} />
        </Field>
        <Field label="Age">
          <NumberStepper label="age" value={a.age} min={10} max={100} onChange={(v) => setA({ age: v })} suffix="years" />
        </Field>
        <Field label="Height">
          {imperial ? (
            <HeightImperial cm={a.height_cm ?? null} onChange={(cm) => setA({ height_cm: cm })} />
          ) : (
            <NumberStepper label="height" value={a.height_cm} min={100} max={250} onChange={(v) => setA({ height_cm: v })} suffix="cm" />
          )}
        </Field>
        <Field label="Weight">
          {imperial ? (
            <NumberStepper label="weight" value={a.weight_kg ? kgToLb(a.weight_kg) : null} min={66} max={550}
              onChange={(v) => setA({ weight_kg: v == null ? null : lbToKg(v) })} suffix="lb" />
          ) : (
            <NumberStepper label="weight" value={a.weight_kg} min={30} max={250} step={0.5} decimals={1}
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
  const imperial = a.units === 'imperial'
  return (
    <>
      <Card>
        <Field label="Resting heart rate">
          <NumberStepper label="resting heart rate" value={a.resting_hr} min={25} max={120} onChange={(v) => setA({ resting_hr: v })} suffix="bpm" />
        </Field>
        <Field label="Max heart rate">
          <NumberStepper label="max heart rate" value={a.max_hr} min={100} max={230} onChange={(v) => setA({ max_hr: v })} suffix="bpm" />
        </Field>
        <Field label="Threshold heart rate" hint="Roughly your average heart rate for an all-out hour.">
          <NumberStepper label="threshold heart rate" value={a.threshold_hr} min={80} max={220} onChange={(v) => setA({ threshold_hr: v })} suffix="bpm" />
        </Field>
      </Card>
      <Card>
        {sports.includes('bike') && (
          <Field label="Cycling FTP" hint={a.weight_kg && a.ftp_w ? `${(a.ftp_w / a.weight_kg).toFixed(1)} W/kg. Bike workouts target power.` : 'Bike workouts target power when you have a power meter.'}>
            <NumberStepper label="FTP" value={a.ftp_w} min={50} max={600} step={5} onChange={(v) => setA({ ftp_w: v })} suffix="watts" />
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
          <NumberStepper label="hours per week" value={a.weekly_hours} min={1} max={30} step={0.5} decimals={1}
            onChange={(v) => setA({ weekly_hours: v })} suffix="hours" />
        </Field>
        <Field label="Training days" hint={(a.available_days ?? []).length < 3 ? 'Three or more days works best.' : `${(a.available_days ?? []).length} days a week. The rest are rest days.`}>
          <MultiChoice value={a.available_days ?? []} options={WEEKDAYS} onChange={(v) => setA({ available_days: v, long_day: v.includes(a.long_day ?? '') ? a.long_day : v[v.length - 1] ?? null })} />
        </Field>
        <Field label="Long-session day" hint={sports.includes('bike') && sports.includes('run') ? 'Your long ride (or brick). The long run goes the day after.' : 'Your longest session of the week.'}>
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

export function GarminFill({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={busy}
      className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5 text-left disabled:opacity-60">
      <Watch className="size-4 shrink-0 text-(--accent)" />
      <span className="min-w-0 flex-1 text-[0.8235rem] text-(--accent)">{busy ? 'Asking Garmin…' : 'Fill in from Garmin'}</span>
    </button>
  )
}

export function HeightImperial({ cm, onChange }: { cm: number | null; onChange: (cm: number | null) => void }) {
  const { ft, inch } = cm ? cmToFtIn(cm) : { ft: 5, inch: 9 }
  return (
    <div className="flex gap-3">
      <div className="flex-1"><NumberStepper label="feet" value={cm ? ft : null} min={3} max={8} onChange={(v) => onChange(v == null ? null : ftInToCm(v, inch))} suffix="ft" /></div>
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
      <input className={inputCls} inputMode="numeric" placeholder={placeholder} value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if (!text.trim()) { setBad(false); onChange(null); return }
          const s = parsePace(text)
          setBad(s == null)
          if (s != null) onChange(s)
        }} />
      {bad && <span className="text-[0.7059rem] text-(--danger)">Use minutes:seconds, like {placeholder}.</span>}
    </div>
  )
}

