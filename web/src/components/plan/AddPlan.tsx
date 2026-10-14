// "Add plan": one place to bring a plan in, for athletes (Plan tab) and coaches (athlete ->
// Plan). Drop a file (or several), pick files on a phone, paste text or a screenshot, or start
// from a template the builder sizes to the athlete. Sheets whose columns Rabbit can't place
// get a quick column-mapping step; everything ends in the editable review (PlanReview).
import { useCallback, useEffect, useRef, useState } from 'react'
import { CalendarRange, ChevronDown, ChevronUp, ClipboardPaste, Download, FileSpreadsheet, FileUp, Link2, Sparkles, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import {
  ACCEPT, READ_BY_RABBIT, linkHelp, mondayOf, type ColumnMapping, type ImportApi, type ImportStatus, type MapField,
  type PlanTemplate, type Preview,
} from '@/lib/planimport'
import { Card, Field, Screen, areaCls, inputCls } from './ui'
import { fmtDay } from './PlanParts'
import { PlanReview } from './PlanReview'

type Who = 'coach' | 'athlete'
type Sent = { files: Blob[]; names: string[] }
const short = (d: string) => fmtDay(d, { weekday: 'short', month: 'short', day: 'numeric' })

/** The whole flow: add -> (map columns) -> review -> applied. */
export function AddPlanFlow({ api, status, who, athleteName, hasPlan, onClose, onApplied }: {
  api: ImportApi; status: ImportStatus; who: Who; athleteName: string; hasPlan: boolean
  onClose: () => void; onApplied: () => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  if (preview) {
    return <PlanReview api={api} initial={preview} who={who} athleteName={athleteName}
      onClose={() => setPreview(null)} onApplied={onApplied} />
  }
  return <AddPlanScreen api={api} status={status} hasPlan={hasPlan} onClose={onClose} onPreview={setPreview} />
}

function AddPlanScreen({ api, status, hasPlan, onClose, onPreview }: {
  api: ImportApi; status: ImportStatus; hasPlan: boolean; onClose: () => void; onPreview: (p: Preview) => void
}) {
  const [start, setStart] = useState(status.next_monday)
  const [editStart, setEditStart] = useState(false)
  const [busy, setBusy] = useState<{ label: string; cycle: string[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const [typing, setTyping] = useState(false)
  const [text, setText] = useState('')
  const [mapping, setMapping] = useState<{ info: ColumnMapping; sent: Sent } | null>(null)
  const [draft, setDraft] = useState<Preview | null>(null)
  const [tpl, setTpl] = useState<{ templates: PlanTemplate[]; groups: { id: string; label: string }[] } | null>(null)
  const [help, setHelp] = useState<'tp' | 'csv' | null>(null)
  const [closing, setClosing] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  useEffect(() => {
    api.pending().then((r) => setDraft(r.preview), () => {})
    api.templates().then(setTpl, () => {})
  }, [api])

  const send = useCallback(async (sent: Sent, extra: { map?: { header_row: number; cols: Partial<Record<MapField, number>> }; ai?: boolean } = {}) => {
    if (!sent.files.length) return
    setError(null); setHint(null)
    const reads = extra.ai || sent.names.some((n) => READ_BY_RABBIT.test(n))
    const many = sent.files.length > 1
    setBusy(reads
      ? { label: 'Reading your plan…', cycle: ['Reading your plan…', many ? 'Reading every page…' : 'Finding the sessions…', 'Lining up the weeks…'] }
      : { label: 'Reading your plan…', cycle: ['Reading your plan…', 'Lining up the weeks…'] })
    try {
      const r = await api.upload(sent.files, sent.names, { start, ...extra })
      if (r.mapping) setMapping({ info: r.mapping, sent })
      else onPreview(r.preview)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
      if (input.current) input.current.value = ''
    }
  }, [api, start, onPreview])

  const sendFiles = useCallback((list: FileList | File[]) => {
    const files = Array.from(list).slice(0, 10)
    if (files.length) void send({ files, names: files.map((f, i) => f.name || `image-${i + 1}.png`) })
  }, [send])

  const sendText = useCallback((t: string) => {
    const s = t.trim()
    if (!s) return
    const link = linkHelp(s)
    if (link) { setHint(link); return }
    void send({ files: [new Blob([s], { type: 'text/plain' })], names: ['pasted.txt'] })
  }, [send])

  // Ctrl/Cmd+V anywhere on this screen: a screenshot or copied files go up as files,
  // copied cells (tab-separated) or text as a paste. Typing in the text box is left alone.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (busy || mapping) return
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT')) return
      const files = Array.from(e.clipboardData?.files ?? [])
      if (files.length) { e.preventDefault(); sendFiles(files); return }
      const t = e.clipboardData?.getData('text/plain') ?? ''
      if (t.trim()) { e.preventDefault(); sendText(t) }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [busy, mapping, sendFiles, sendText])

  async function pickTemplate(t: PlanTemplate) {
    setError(null)
    setBusy({ label: `Building ${t.label}…`, cycle: [`Building ${t.label}…`, 'Sizing it to the hours you have…', 'Placing long days…'] })
    try { onPreview((await api.template(t.id, { start })).preview) } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  if (mapping) {
    return <ColumnMapper info={mapping.info} aiLeft={status.ai_per_day > 0 ? status.ai_left : 0} busy={!!busy} error={error}
      onBack={() => { setMapping(null); setError(null) }}
      onUse={(m) => void send(mapping.sent, { map: m })}
      onAi={() => void send(mapping.sent, { ai: true })} />
  }

  const linkTyped = typing ? linkHelp(text) : null
  return (
    <Screen title="Add a plan" subtitle="Drop it in. You'll check every week before anything changes." onBack={close} onClose={close} closing={closing}>
      {draft && !busy && (
        <div className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5">
          <span className="min-w-0 flex-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
            <span className="block font-medium text-(--text)">Pick up where you left off</span>
            {[draft.name, draft.source].filter(Boolean).join(' · ')} · {draft.rows.length} session{draft.rows.length === 1 ? '' : 's'}
          </span>
          <Button variant="primary" className="h-11 px-3 text-[0.7647rem]" onClick={() => onPreview(draft)}>Continue</Button>
          <button type="button" aria-label="Discard the draft" className="hit-44 rounded p-1 text-(--text-muted)"
            onClick={() => { void api.discard(draft.id).catch(() => {}); setDraft(null) }}><X className="size-4" /></button>
        </div>
      )}

      {busy ? (
        <Card className="py-10">
          <RabbitLoader label={busy.label} cycle={busy.cycle} />
        </Card>
      ) : (
        <div
          onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDrag(true) } }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) sendFiles(e.dataTransfer.files) }}
          className={cn('flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-4 py-6 text-center transition-colors',
            drag ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border-strong) bg-(--bg-surface)')}>
          <span className="flex size-12 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)"><Upload className="size-6" /></span>
          <div>
            <p className="font-display text-[1.1765rem] leading-tight text-(--brand)">Drop a file, paste your plan, or pick a template</p>
            <p className="mt-1 text-[0.7059rem] leading-snug text-(--text-muted)">
              Spreadsheets, TrainingPeaks exports, calendars, PDFs, photos, Zwift workouts or plain text.
              <InfoTip label="What works" text="CSV, TSV and Excel (any columns: Rabbit maps them, or asks), week grids (weeks down, Mon–Sun across), TrainingPeaks workout CSV and calendar .ics, PDFs and photos of printed plans (several pages at once), pasted text or email, Zwift .zwo and .erg/.mrc workouts. Garmin .fit files: export as .zwo instead." />
            </p>
          </div>
          <div className="flex w-full max-w-sm flex-col gap-2 sm:flex-row">
            <Button variant="primary" className="h-12 flex-1 gap-1.5 text-[0.8824rem]" onClick={() => input.current?.click()}>
              <FileUp className="size-4" /> Choose files
            </Button>
            <Button variant="default" className="h-12 flex-1 gap-1.5 text-[0.8824rem]" onClick={() => setTyping((x) => !x)} aria-expanded={typing}>
              <ClipboardPaste className="size-4" /> Paste text
            </Button>
          </div>
          <p className="hidden text-[0.6471rem] text-(--text-muted) sm:block">or press Ctrl/⌘+V to paste a screenshot or copied cells</p>
          <input ref={input} type="file" multiple className="hidden" accept={ACCEPT}
            onChange={(e) => { if (e.target.files?.length) sendFiles(e.target.files) }} />
        </div>
      )}

      {typing && !busy && (
        <Card className="flex flex-col gap-2.5 px-4 py-3.5">
          <textarea className={cn(areaCls, 'min-h-36')} autoFocus value={text} onChange={(e) => setText(e.target.value)}
            placeholder={'Paste your plan: an email, notes or copied spreadsheet cells.\nWeek 1: Mon rest, Tue 6x400 at 5K pace, Thu 40\' easy, Sat long run 90\''} />
          {linkTyped && <LinkHint text={linkTyped} />}
          <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" disabled={!text.trim() || !!linkTyped} onClick={() => sendText(text)}>
            <Sparkles className="size-4" /> Read it
          </Button>
          {status.ai_per_day > 0 && <p className="text-[0.6471rem] text-(--text-muted)">Rabbit reads text, PDFs and photos for you: {status.ai_left} of {status.ai_per_day} reads left today. Spreadsheets and workout files don't count.</p>}
        </Card>
      )}

      {hint && <LinkHint text={hint} />}
      {error && <ErrorState compact message={error} />}

      <div className="flex items-center gap-2 px-1 text-[0.7059rem] text-(--text-muted)">
        <span className="min-w-0 flex-1">If it says “Week 1”, week 1 starts <span className="font-medium text-(--text-secondary)">{short(start)}</span></span>
        <button type="button" className="min-h-11 px-1 font-medium text-(--accent)" onClick={() => setEditStart((x) => !x)}>{editStart ? 'Done' : 'Change'}</button>
      </div>
      {editStart && (
        <Card className="px-4 py-3">
          <Field label="Week 1 starts on" hint="Weeks run Monday to Sunday. You can still shift the dates in the review.">
            <input type="date" className={inputCls} value={start} onChange={(e) => e.target.value && setStart(mondayOf(e.target.value))} />
          </Field>
        </Card>
      )}

      <section className="flex flex-col gap-2">
        <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">No file? Start from a template</h3>
        {!tpl ? <RabbitLoader inline className="px-1 text-[0.7059rem]" label="Loading templates" /> : tpl.groups.map((g) => {
          const items = tpl.templates.filter((t) => t.group === g.id)
          if (!items.length) return null
          return (
            <div key={g.id} className="flex flex-col gap-1.5">
              <p className="px-1 text-[0.7059rem] font-medium text-(--text-secondary)">{g.label}</p>
              <div className="grid grid-cols-2 gap-2">
                {items.map((t) => (
                  <button key={t.id} type="button" disabled={!!busy} onClick={() => void pickTemplate(t)}
                    className="flex min-h-16 flex-col items-start justify-center rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2 text-left active:bg-(--bg-inset) disabled:opacity-50">
                    <span className="text-[0.8235rem] font-medium text-(--text)">{t.label}</span>
                    <span className="text-[0.6471rem] leading-snug text-(--text-muted)">{t.weeks} weeks · {t.blurb}</span>
                  </button>
                ))}
              </div>
            </div>
          )
        })}
        <p className="px-1 text-[0.6471rem] leading-snug text-(--text-muted)">Templates are sized to the weekly hours, level and training days in the profile. Tap one to preview it.</p>
      </section>

      <Card>
        <Disclosure open={help === 'tp'} onToggle={() => setHelp(help === 'tp' ? null : 'tp')} icon={<CalendarRange className="size-4" />} title="Coming from TrainingPeaks?">
          <ol className="flex list-decimal flex-col gap-2 pl-5 text-[0.7647rem] leading-snug text-(--text-secondary)">
            <li><span className="font-medium text-(--text)">Workouts (CSV).</span> In TrainingPeaks, open account settings, choose Export Data, export workouts as CSV for the dates you want, then drop the .csv here.</li>
            <li><span className="font-medium text-(--text)">Calendar (iCal).</span> In the calendar settings, copy the iCal feed link, open it in your browser to save the .ics file, then drop it here.</li>
            <li><span className="font-medium text-(--text)">Single workouts.</span> Export them as Zwift .zwo (or .erg/.mrc): the intervals come across as steps that sync to Garmin.</li>
          </ol>
        </Disclosure>
        <div className="border-t border-(--border)" />
        <Disclosure open={help === 'csv'} onToggle={() => setHelp(help === 'csv' ? null : 'csv')} icon={<FileSpreadsheet className="size-4" />} title="Making your own spreadsheet?">
          <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">One row per session with a date, sport, title and time works best. Rabbit also reads a week grid (weeks down, Monday to Sunday across, cells like “45' easy run”).</p>
          <a href={api.templateUrl} download="rabbit-plan-template.csv"
            className="mt-2 inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-(--border) px-3 text-[0.7647rem] font-medium text-(--text)">
            <Download className="size-4" /> Download the CSV template
          </a>
        </Disclosure>
      </Card>

      {hasPlan && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[0.7059rem] text-(--text-muted)">
          <span>Download the current plan:</span>
          <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('csv')} download><Download className="size-3.5" /> CSV</a>
          <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('ics')} download><CalendarRange className="size-3.5" /> Calendar (.ics)</a>
        </div>
      )}
    </Screen>
  )
}

function LinkHint({ text }: { text: string }) {
  return (
    <div className="flex gap-2.5 rounded-xl border border-(--warning-text)/30 bg-(--bg-surface) px-3.5 py-3 text-[0.7647rem] leading-snug text-(--text)" role="status">
      <Link2 className="mt-0.5 size-4 shrink-0 text-(--warning-text)" />
      <span>{text}</span>
    </div>
  )
}

function Disclosure({ open, onToggle, icon, title, children }: { open: boolean; onToggle: () => void; icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex min-h-12 w-full items-center gap-2.5 px-4 text-left active:bg-(--bg-inset)">
        <span className="text-(--accent)">{icon}</span>
        <span className="flex-1 text-[0.8235rem] text-(--text)">{title}</span>
        {open ? <ChevronUp className="size-4 text-(--text-muted)" /> : <ChevronDown className="size-4 text-(--text-muted)" />}
      </button>
      {open && <div className="px-4 pb-3.5">{children}</div>}
    </div>
  )
}

// --------------------------------------------------------- column mapping --
const FIELD_LABEL: Record<MapField, string> = {
  date: 'Date', week: 'Week number', weekday: 'Day of the week', sport: 'Sport', title: 'Workout',
  duration: 'Duration', distance: 'Distance', intensity: 'Intensity / zone / RPE', notes: 'Notes',
}
const FIELD_HINT: Partial<Record<MapField, string>> = {
  date: 'Or week number + day', duration: '45, 1:15, 1h15, 75\'', distance: 'km, mi, m or yd', title: 'Or sport',
}

function ColumnMapper({ info, aiLeft, busy, error, onBack, onUse, onAi }: {
  info: ColumnMapping; aiLeft: number; busy: boolean; error: string | null
  onBack: () => void; onUse: (m: { header_row: number; cols: Partial<Record<MapField, number>> }) => void; onAi: () => void
}) {
  const [cols, setCols] = useState<Partial<Record<MapField, number>>>(() => {
    const out: Partial<Record<MapField, number>> = {}
    for (const f of info.fields) { const g = info.guess[f]; if (g != null) out[f] = g }
    return out
  })
  const letter = (j: number) => String.fromCharCode(65 + (j % 26))
  const name = (j: number) => info.headers[j] || `Column ${letter(j)}`
  const hasWhen = cols.date != null || (cols.week != null && cols.weekday != null)
  const hasWhat = cols.title != null || cols.sport != null || cols.notes != null
  const sample = (j: number | undefined) => j == null ? '' : info.sample.map((r) => r[j]).filter(Boolean).slice(0, 2).join(' · ')
  const footer = (
    <>
      <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={onBack}>Back</Button>
      <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} disabled={!hasWhen || !hasWhat}
        onClick={() => onUse({ header_row: info.header_row, cols })}>Use these columns</Button>
    </>
  )
  return (
    <Screen title="Match the columns" subtitle={info.name} onBack={onBack} onClose={onBack} footer={footer}>
      <p className="px-1 text-[0.7647rem] leading-snug text-(--text-muted)">Rabbit guessed what each column means. Fix anything that's off: it needs a date (or week + day) and what the session is.</p>
      <Card>
        <div className="divide-y divide-(--border)">
          {info.fields.map((f) => (
            <label key={f} className="flex min-h-14 items-center gap-3 px-4 py-2">
              <span className="w-32 shrink-0">
                <span className="block text-[0.7647rem] font-medium text-(--text)">{FIELD_LABEL[f]}</span>
                {FIELD_HINT[f] && <span className="block text-[0.6471rem] text-(--text-muted)">{FIELD_HINT[f]}</span>}
              </span>
              <span className="min-w-0 flex-1">
                <select className={cn(inputCls, 'h-11')} value={cols[f] ?? ''} aria-label={FIELD_LABEL[f]}
                  onChange={(e) => setCols((c) => { const n = { ...c }; if (e.target.value === '') delete n[f]; else n[f] = Number(e.target.value); return n })}>
                  <option value="">Not in this sheet</option>
                  {Array.from({ length: info.columns }, (_, j) => <option key={j} value={j}>{name(j)}</option>)}
                </select>
                {cols[f] != null && sample(cols[f]) && <span className="mt-0.5 block truncate text-[0.6471rem] text-(--text-muted)">e.g. {sample(cols[f])}</span>}
              </span>
            </label>
          ))}
        </div>
      </Card>
      {busy && <RabbitLoader inline className="text-[0.7647rem]" label="Reading your plan…" />}
      {error && <ErrorState compact message={error} />}
      {aiLeft > 0 && (
        <button type="button" disabled={busy} onClick={onAi} className="flex min-h-11 items-center gap-1.5 self-start px-1 text-[0.7647rem] font-medium text-(--accent) disabled:opacity-50">
          <Sparkles className="size-4" /> Let Rabbit read it instead
        </button>
      )}
    </Screen>
  )
}
