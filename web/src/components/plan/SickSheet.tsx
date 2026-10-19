// Sick mode: tell Rabbit you're ill and the plan steps back. Two big choices (head cold, or
// fever / chest / body aches / stomach), since when, and until when (or "until I feel better");
// a preview of what changes; then one tap. While it's on, the same sheet shows the day count,
// "I feel better" (an easy return, no catching up), "Still sick" (+2 days) and Undo.
// Only the choice and the dates are saved: no symptoms.
import { useEffect, useState } from 'react'
import { Thermometer, Wind } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { Row, Switch } from '@/components/settings/Grouped'
import { RabbitNap } from '@/components/anim'
import { cn } from '@/lib/utils'
import { Card, Field, inputCls } from './ui'
import { fmtDay, todayStr } from './PlanParts'
import {
  extendSick, feelBetter, getSick, previewSick, startSick, undoSick,
  type SickPreview, type SickSeverity, type SickView,
} from '@/lib/sick'

const short = (d: string) => fmtDay(d, { weekday: 'short', month: 'short', day: 'numeric' })

function Choice({ on, icon, title, sub, onPick }: { on: boolean; icon: React.ReactNode; title: string; sub: string; onPick: () => void }) {
  return (
    <button type="button" role="radio" aria-checked={on} onClick={onPick}
      className={cn('flex min-h-16 w-full items-center gap-3 rounded-xl border px-3.5 py-3 text-left transition-colors active:bg-(--bg-inset)',
        on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
      <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl', on ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-inset) text-(--text-secondary)')} aria-hidden>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8824rem] font-semibold text-(--text)">{title}</span>
        <span className="block text-[0.7059rem] leading-snug text-(--text-muted)">{sub}</span>
      </span>
    </button>
  )
}

export function SickSheet({ today = todayStr(), onClose, onDone }: {
  today?: string
  onClose: () => void
  /** a short line for a toast */
  onDone?: (msg: string) => void
}) {
  const [view, setView] = useState<SickView | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [sev, setSev] = useState<SickSeverity | null>(null)
  const [start, setStart] = useState(today)
  const [openEnded, setOpenEnded] = useState(true)
  const [until, setUntil] = useState(today)
  const [restAll, setRestAll] = useState(false)
  const [pv, setPv] = useState<SickPreview | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    getSick().then((v) => {
      setView(v)
      if (v.active) {
        setSev(v.severity ?? null); setRestAll(!!v.rest_all); setStart(v.start ?? today)
        if (v.until && v.until !== 'better') { setOpenEnded(false); setUntil(v.until) }
      }
    }, (e) => setLoadErr((e as Error).message))
  }, [today])

  const body = sev ? { severity: sev, start, until: openEnded ? null : until, rest_all: sev === 'head' ? restAll : false } : null
  const key = JSON.stringify(body)
  useEffect(() => {
    if (!body) { setPv(null); return }
    let live = true
    previewSick(body).then((p) => { if (live) setPv(p) }, () => { if (live) setPv(null) })
    return () => { live = false }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  async function run(what: string, f: () => Promise<unknown>, msg: string) {
    setBusy(what); setErr(null)
    try { await f(); onDone?.(msg); onClose() }
    catch (e) { setErr((e as Error).message); setBusy(null) }
  }

  const active = !!view?.active && !editing
  const title = active ? 'Sick mode' : view?.active ? 'Change sick mode' : "I'm sick"

  let content: React.ReactNode
  if (!view && !loadErr) {
    content = <div className="flex justify-center py-10"><RabbitNap size={48} mode="sleep" /></div>
  } else if (loadErr) {
    content = <p className="px-1 py-6 text-center text-[0.8235rem] text-(--danger)" role="alert">{loadErr}</p>
  } else if (active && view) {
    content = (
      <>
        <div className="flex flex-col items-center gap-2 pt-1 text-center">
          <RabbitNap size={52} mode="sleep" />
          <p className="font-display text-[1.2941rem] leading-tight text-(--brand)">Day {view.day} · Rest up</p>
          <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-secondary)">{view.line}</p>
          <p className="text-[0.7059rem] text-(--text-muted)">
            Since {short(view.start!)}
            {view.until && view.until !== 'better' ? ` · back by ${short(view.until)}` : ' · until you feel better'}
          </p>
        </div>
        {view.race_note && <p className="rounded-xl border border-(--warning)/30 bg-(--warning-subtle) px-3.5 py-2.5 text-[0.7647rem] leading-snug text-(--warning-text)">{view.race_note}</p>}
        <Button variant="primary" className="h-12 text-[0.8824rem]" loading={busy === 'better'}
          onClick={() => void run('better', feelBetter, 'Welcome back. rabbt eased the next few days.')}>I feel better</Button>
        <p className="-mt-2 px-1 text-center text-[0.7059rem] leading-snug text-(--text-muted)">
          rabbt makes the next few days easy, then your plan picks up where it is. No catching up.
        </p>
        <div className="grid grid-cols-2 gap-2">
          <Button variant="default" className="h-11 text-[0.8235rem]" loading={busy === 'extend'}
            onClick={() => void run('extend', () => extendSick(2), 'Okay. Two more easy days.')}>Still sick</Button>
          <Button variant="default" className="h-11 text-[0.8235rem]" onClick={() => setEditing(true)}>Change</Button>
        </div>
        <button type="button" disabled={!!busy} onClick={() => void run('undo', undoSick, 'Sick mode is off. Your plan is back as it was.')}
          className="mx-auto min-h-11 px-3 text-[0.7647rem] font-medium text-(--text-secondary) underline-offset-2 hover:underline">
          Undo sick mode (put the plan back)
        </button>
      </>
    )
  } else {
    content = (
      <>
        <div className="flex items-center gap-3 px-1">
          <RabbitNap size={40} mode="sleep" className="shrink-0" />
          <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">Sorry you're feeling rough. How is it?</p>
        </div>
        <div role="radiogroup" aria-label="How you're feeling" className="flex flex-col gap-2">
          <Choice on={sev === 'head'} icon={<Wind className="size-5" />} title="Head cold"
            sub="Sniffles, stuffy nose, sore throat" onPick={() => setSev('head')} />
          <Choice on={sev === 'body'} icon={<Thermometer className="size-5" />} title="Fever or worse"
            sub="Fever, chest, body aches or stomach" onPick={() => setSev('body')} />
        </div>
        {sev && (
          <>
            <Card>
              <div className="grid grid-cols-2">
                <Field label="Sick since">
                  <input type="date" className={inputCls} value={start} max={today} onChange={(e) => e.target.value && setStart(e.target.value)} />
                </Field>
                <Field label="Back by">
                  {openEnded
                    ? <button type="button" className={cn(inputCls, 'text-left text-(--text-secondary)')} onClick={() => setOpenEnded(false)}>Not sure yet</button>
                    : <input type="date" className={inputCls} value={until} min={today} onChange={(e) => e.target.value && setUntil(e.target.value)} />}
                </Field>
              </div>
              {!openEnded && (
                <button type="button" className="min-h-11 w-full border-t border-(--border) px-3.5 text-left text-[0.7647rem] font-medium text-(--accent)" onClick={() => setOpenEnded(true)}>
                  Not sure: until I feel better
                </button>
              )}
              {sev === 'head' && (
                <div className="border-t border-(--border)">
                  <Row title="Rest anyway" subtitle="No easy sessions either" trailing={<Switch label="Rest anyway" checked={restAll} onChange={setRestAll} />} />
                </div>
              )}
            </Card>
            <p className="px-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
              {sev === 'head' && !restAll
                ? 'Each day keeps one short, easy session (30 min at most). Skip it if you don\'t feel up to it.'
                : 'Every session becomes rest until you feel better.'}
              {pv && pv.sessions > 0 && <> <b className="text-(--text)">{pv.sessions} session{pv.sessions === 1 ? '' : 's'}</b> change through {short(pv.through)}.</>}
              {pv && pv.sessions === 0 && <> Nothing is planned on those days.</>}
              {' '}Your streak is safe.
            </p>
            {pv?.race_note && <p className="rounded-xl border border-(--warning)/30 bg-(--warning-subtle) px-3.5 py-2.5 text-[0.7647rem] leading-snug text-(--warning-text)">{pv.race_note}</p>}
          </>
        )}
        <p className="px-1 text-[0.6471rem] leading-snug text-(--text-muted)">{view?.safety}</p>
        <Button variant="primary" className="h-12 text-[0.8824rem]" disabled={!sev} loading={busy === 'start'}
          onClick={() => body && void run('start', () => startSick(body), view?.active ? 'Sick mode updated.' : 'Rest up. rabbt cleared the way.')}>
          {view?.active ? 'Save changes' : 'Turn on sick mode'}
        </Button>
        {editing && <button type="button" className="mx-auto min-h-11 px-3 text-[0.7647rem] text-(--text-secondary)" onClick={() => setEditing(false)}>Back</button>}
      </>
    )
  }

  return (
    <Sheet title={title} onClose={onClose}
      bodyClassName="settings flex flex-col gap-3.5 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      {content}
      {err && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{err}</p>}
    </Sheet>
  )
}
