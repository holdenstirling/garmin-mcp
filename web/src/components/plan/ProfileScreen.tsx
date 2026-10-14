// Settings > Training profile: everything the plan builder and coach use about you,
// editable any time. Saving doesn't touch the plan; rebuild it to apply the changes.
import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { putAthlete, type Me, type Sport } from '@/lib/api'
import { getGarminNumbers, sportsFor, type AthleteFull } from '@/lib/plan'
import { Card, Field, Screen, StepIntro, areaCls } from './ui'
import { GarminFill, NumbersFields, WeekFields, YouFields } from './ProfileFields'

type Tab = 'you' | 'numbers' | 'week'

export function ProfileScreen({ me, hasBuiltPlan, onClose, onSaved, onRebuild }: {
  me: Me; hasBuiltPlan: boolean
  onClose: () => void; onSaved: () => void; onRebuild: () => void
}) {
  const initial = me.athlete as AthleteFull
  const [a, setAState] = useState<Partial<AthleteFull>>(() => ({ ...initial }))
  const [tab, setTab] = useState<Tab>('you')
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState<'save' | 'garmin' | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [saved, setSaved] = useState(false)
  const setA = (p: Partial<AthleteFull>) => { setAState((x) => ({ ...x, ...p })); setMsg(null); setSaved(false) }
  const sports: Sport[] = useMemo(() => {
    const s = sportsFor(me.goal?.distance)
    return s.length ? s : ['swim', 'bike', 'run']
  }, [me.goal?.distance])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  const changed = useMemo(() => {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(a)) {
      const before = (initial as unknown as Record<string, unknown>)[k]
      if (JSON.stringify(v ?? null) !== JSON.stringify(before ?? null)) out[k] = v === '' && typeof before !== 'string' ? null : v
    }
    return out
  }, [a, initial])

  async function save() {
    setBusy('save'); setMsg(null)
    try {
      await putAthlete(changed as unknown as Parameters<typeof putAthlete>[0])
      setSaved(true)
      setMsg({ text: 'Saved. Rabbit uses these from now on.', ok: true })
      onSaved()
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }) }
    finally { setBusy(null) }
  }

  async function fill() {
    setBusy('garmin'); setMsg(null)
    try {
      const { numbers } = await getGarminNumbers()
      const got = Object.entries(numbers).filter(([, v]) => v != null)
      setA(Object.fromEntries(got) as Partial<AthleteFull>)
      setMsg({ text: got.length ? `Updated from Garmin: ${got.map(([k]) => k.replace(/_/g, ' ')).join(', ')}. Save to keep them.` : 'Garmin had nothing new.', ok: true })
    } catch (e) { setMsg({ text: (e as Error).message, ok: false }) }
    finally { setBusy(null) }
  }

  const dirty = Object.keys(changed).length > 0 && !saved
  return (
    <Screen title="Training profile" subtitle="Used for your plan, zones and coaching" closing={closing} onClose={close}
      headerExtra={
        <div className="mx-auto mt-2.5 flex max-w-xl gap-1 rounded-lg bg-(--bg-elevated) p-1">
          {([['you', 'You'], ['numbers', 'Zones'], ['week', 'Week']] as [Tab, string][]).map(([t, l]) => (
            <button key={t} type="button" onClick={() => setTab(t)} aria-pressed={tab === t}
              className={`h-8 flex-1 rounded-md text-[0.7647rem] font-medium transition-colors ${tab === t ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)'}`}>{l}</button>
          ))}
        </div>
      }
      footer={<>
        {saved && hasBuiltPlan && <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={onRebuild}>Rebuild plan</Button>}
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy === 'save'} disabled={!dirty} onClick={() => void save()}>
          {saved ? 'Saved' : 'Save'}
        </Button>
      </>}>
      {me.garmin.connected && tab !== 'week' && <GarminFill busy={busy === 'garmin'} onClick={() => void fill()} />}
      {msg && <p className={`px-1 text-[0.7647rem] ${msg.ok ? 'text-(--accent)' : 'text-(--danger)'}`} role="status">{msg.text}</p>}
      {tab === 'you' && (
        <>
          <StepIntro eyebrow="About you" title="Experience and body" />
          <YouFields a={a} setA={setA} sports={sports} />
          <Card>
            <Field label="Background" hint="Races done, years training, anything Rabbit should know.">
              <textarea className={areaCls} value={a.experience ?? ''} maxLength={300} onChange={(e) => setA({ experience: e.target.value })} />
            </Field>
            <Field label="Coaching style" className="border-t border-(--border)" hint="How you like feedback, sessions you love or hate.">
              <textarea className={areaCls} value={a.preferences ?? ''} maxLength={500} onChange={(e) => setA({ preferences: e.target.value })} />
            </Field>
          </Card>
        </>
      )}
      {tab === 'numbers' && (
        <>
          <StepIntro eyebrow="Zones" title="Training numbers">Workouts on your watch target these. Leave blank to use Garmin's heart-rate zones.</StepIntro>
          <NumbersFields a={a} setA={setA} sports={['swim', 'bike', 'run']} />
        </>
      )}
      {tab === 'week' && (
        <>
          <StepIntro eyebrow="Your week" title="Time and equipment" />
          <WeekFields a={a} setA={setA} sports={sports} />
        </>
      )}
      {saved && hasBuiltPlan && (
        <p className="px-1 text-[0.7647rem] text-(--text-muted)">Your plan was built with your old answers. Rebuild it to use these (edited sessions are replaced).</p>
      )}
    </Screen>
  )
}
