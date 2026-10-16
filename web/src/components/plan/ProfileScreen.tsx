// Settings > Training profile: everything the plan builder and coach use about you,
// editable any time. Saving doesn't touch the plan; rebuild it to apply the changes.
import { useMemo, useState } from 'react'
import { ChevronRight, Compass, Footprints } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { type Me, type Sport } from '@/lib/api'
import { getGarminNumbers, sportsFor, type AthleteFull } from '@/lib/plan'
import { Card, Field, Screen, StepIntro, areaCls } from './ui'
import { GarminFill, NumbersFields, TraitsFields, WeekFields, YouFields } from './ProfileFields'
import { GoalsTab } from './GoalsTab'
import { PhotoField } from './PhotoField'
import { TrainingPaces } from '@/components/paces/TrainingPaces'
import { InterestsSheet } from '@/components/explore/InterestsSheet'
import { interestsSummary, type Interests } from '@/lib/foryou'
import { useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { DraftRestored, useUnsavedGuard } from '@/components/ui/UnsavedGuard'

type Tab = 'you' | 'goals' | 'numbers' | 'week'

export function ProfileScreen({ me, hasBuiltPlan, onClose, onSaved, onRebuild, onOpenEvents, onOpenGear }: {
  me: Me; hasBuiltPlan: boolean
  onClose: () => void; onSaved: () => void; onRebuild: () => void
  /** opens the Events screen (full event editing) */
  onOpenEvents?: () => void
  /** opens the Gear garage */
  onOpenGear?: () => void
}) {
  const initial = me.athlete as AthleteFull
  // Unsaved answers are kept as a draft on this device (lib/drafts) until saved or discarded.
  const [a, setAState, draft] = useDraft<Partial<AthleteFull>>('profile', () => ({ ...initial }), { label: 'training profile' })
  const [queued, setQueued] = useState(false)
  const [tab, setTab] = useState<Tab>('you')
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState<'save' | 'garmin' | null>(null)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [saved, setSaved] = useState(false)
  const [interests, setInterests] = useState<Interests | undefined>((me.athlete as { interests?: Interests }).interests)
  const [editInterests, setEditInterests] = useState(false)
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
    setBusy('save'); setMsg(null); setQueued(false)
    try {
      const body = { ...changed }
      // Past races without a name are dropped rather than refused.
      if (Array.isArray(body.race_history)) body.race_history = (body.race_history as { name: string }[]).filter((r) => r.name.trim())
      // Durable PUT (lib/outbox): offline / 5xx keeps it queued and retries.
      await saveDurably({ method: 'PUT', path: '/api/athlete', body, label: 'training profile', coalesce: 'athlete' },
        () => setQueued(true))
      draft.clear(); setQueued(false)
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
  const guard = useUnsavedGuard(dirty && !queued, draft.discard)
  return (<>
    <Screen title="Training profile" subtitle="Used for your plan, zones and coaching" closing={closing} onClose={guard.wrap(close)}
      headerExtra={
        <div className="mx-auto mt-2.5 flex max-w-xl gap-1 rounded-lg bg-(--bg-elevated) p-1">
          {([['you', 'You'], ['goals', 'Goals'], ['numbers', 'Zones'], ['week', 'Week']] as [Tab, string][]).map(([t, l]) => (
            <button key={t} type="button" onClick={() => setTab(t)} aria-pressed={tab === t}
              className={`hit-44 h-8 flex-1 rounded-md text-[0.7647rem] font-medium transition-colors ${tab === t ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)'}`}>{l}</button>
          ))}
        </div>
      }
      footer={<>
        {saved && hasBuiltPlan && <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={onRebuild}>Rebuild plan</Button>}
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy === 'save'} disabled={!dirty} onClick={() => void save()}>
          {saved ? 'Saved' : 'Save'}
        </Button>
      </>}>
      {me.garmin.connected && (tab === 'you' || tab === 'numbers') && <GarminFill busy={busy === 'garmin'} onClick={() => void fill()} />}
      {guard.dialog}
      {draft.restored && <DraftRestored onDiscard={draft.discard} note="tap Save to keep it" />}
      {queued && <SaveStatus state="queued" className="px-1" />}
      {saved && !msg && <SaveStatus state="saved" className="px-1" />}
      {msg && <p className={`px-1 text-[0.7647rem] ${msg.ok ? 'text-(--accent)' : 'text-(--danger)'}`} role="status">{msg.text}</p>}
      {tab === 'you' && (
        <>
          <PhotoField me={me} onChanged={onSaved} />
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
          <StepIntro eyebrow="Race fit" title="Strengths and where you train">Race fit compares these with each race.</StepIntro>
          <TraitsFields a={a} setA={setA} sports={sports} />
          <button type="button" onClick={() => setEditInterests(true)}
            className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3 text-left active:bg-(--bg-inset)">
            <Compass className="size-5 shrink-0 text-(--accent)" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block text-[0.8824rem] font-medium text-(--text)">Race interests</span>
              <span className="block truncate text-[0.6471rem] text-(--text-muted)">{interestsSummary(interests).join(' · ') || 'What you like to race: powers your picks in Explore'}</span>
            </span>
            <ChevronRight className="size-4 shrink-0 text-(--text-muted)" />
          </button>
          {onOpenGear && (
            <button type="button" onClick={onOpenGear}
              className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3 text-left active:bg-(--bg-inset)">
              <Footprints className="size-5 shrink-0 text-(--accent)" />
              <span className="min-w-0 flex-1">
                <span className="block text-[0.8824rem] font-medium text-(--text)">Gear garage</span>
                <span className="block text-[0.6471rem] text-(--text-muted)">Shoes, bikes and more: mileage and retirement alerts</span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-(--text-muted)" />
            </button>
          )}
        </>
      )}
      {tab === 'goals' && (
        <>
          <StepIntro eyebrow="Goals" title="Your races this season" />
          <GoalsTab seasonGoal={a.season_goal ?? ''} onSeasonGoal={(v) => setA({ season_goal: v })}
            onOpenEvents={onOpenEvents ? () => { setClosing(true); setTimeout(onOpenEvents, 200) } : undefined} />
        </>
      )}
      {tab === 'numbers' && (
        <>
          <StepIntro eyebrow="Zones" title="Training numbers">Workouts on your watch target these. Leave blank to use Garmin's heart-rate zones.</StepIntro>
          <TrainingPaces onChanged={(p) => { setAState((x) => ({ ...x, ...p } as Partial<AthleteFull>)); onSaved() }} />
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
    {editInterests && <InterestsSheet initial={interests} onClose={() => setEditInterests(false)} onSaved={(i) => { setInterests(i); onSaved() }} />}
  </>)
}
