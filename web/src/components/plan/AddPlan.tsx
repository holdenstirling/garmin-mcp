// "Add a plan": one sheet, three equal ways in (upload a file, paste text, build in Rabbit),
// plus templates the builder sizes to the athlete (and a coach's own). Shared by the athlete's
// Plan tab and CoachApp -> athlete -> Plan. Files: drag and drop anywhere on desktop, the file
// picker on a phone, several at once (screenshots of a printed plan are read together); HEIC
// and big photos become JPEG in the browser first. Pasted Google Sheets/Docs links are fetched
// by the server. Sheets whose columns Rabbit can't place get a column-mapping step; every way
// in ends in the editable review (PlanReview).
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CalendarRange, ChevronDown, ChevronUp, ClipboardPaste, Download, FileSpreadsheet, LayoutGrid, Link2, ScanText, Trash2, Upload, X,
} from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { fitForUpload } from '@/lib/imagefit'
import {
  ACCEPT, READ_BY_RABBIT, isGoogleDocLink, linkHelp, mondayOf, type ColumnMapping, type ImportApi, type ImportStatus, type MapField,
  type PlanTemplate, type Preview, type TemplateLevel, type TemplateList, type UploadResult,
} from '@/lib/planimport'
import { Card, Chip, ChipRow, Field, Screen, areaCls, inputCls } from './ui'
import { fmtDay } from './PlanParts'
import { PlanReview } from './PlanReview'
import { GridBuilder } from './PlanGrid'

type Who = 'coach' | 'athlete'
type Sent = { files: Blob[]; names: string[]; sheet?: number }
type MapChoice = { header_row: number; cols: Partial<Record<MapField, number>> }
const short = (d: string) => fmtDay(d, { weekday: 'short', month: 'short', day: 'numeric' })

/** The whole flow: add -> (map columns) -> review -> applied. */
export function AddPlanFlow({ api, status, who, athleteName, hasPlan, onClose, onApplied }: {
  api: ImportApi; status: ImportStatus; who: Who; athleteName: string; hasPlan: boolean
  onClose: () => void; onApplied: () => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [grid, setGrid] = useState(false)
  // The last files sent, so a workbook can be read again from another sheet.
  const last = useRef<Sent | null>(null)
  if (preview) {
    const sent = last.current
    return <PlanReview api={api} initial={preview} who={who} athleteName={athleteName} canSaveTemplate={!!status.can_save_templates}
      onClose={() => setPreview(null)} onApplied={onApplied}
      onSheet={sent && (preview.sheets?.length ?? 0) > 1 ? async (i) => {
        const r = await api.upload(sent.files, sent.names, { sheet: i })
        if (r.preview) { last.current = { ...sent, sheet: i }; setPreview(r.preview) } else throw new Error('Pick that sheet\'s columns: drop the file again.')
      } : undefined} />
  }
  if (grid) return <GridBuilder api={api} onClose={() => setGrid(false)} onPreview={(p) => { last.current = null; setPreview(p) }} />
  return <AddPlanScreen api={api} status={status} hasPlan={hasPlan} who={who} onClose={onClose}
    onBuild={() => setGrid(true)} onPreview={(p, sent) => { last.current = sent ?? null; setPreview(p) }} />
}

function AddPlanScreen({ api, status, hasPlan, who, onClose, onPreview, onBuild }: {
  api: ImportApi; status: ImportStatus; hasPlan: boolean; who: Who; onClose: () => void
  onPreview: (p: Preview, sent?: Sent) => void; onBuild: () => void
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
  const [tpl, setTpl] = useState<TemplateList | null>(null)
  const [help, setHelp] = useState<'tp' | 'csv' | null>(null)
  const [closing, setClosing] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const drags = useRef(0)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  useEffect(() => {
    api.pending().then((r) => setDraft(r.preview), () => {})
    api.templates().then(setTpl, () => {})
  }, [api])

  const handle = useCallback((r: UploadResult, sent: Sent) => {
    if (r.mapping) setMapping({ info: r.mapping, sent: { ...sent, sheet: r.mapping.sheet ?? sent.sheet } })
    else onPreview(r.preview, sent)
  }, [onPreview])

  const send = useCallback(async (sent: Sent, extra: { map?: MapChoice; ai?: boolean } = {}) => {
    if (!sent.files.length) return
    setError(null); setHint(null)
    const reads = extra.ai || sent.names.some((n) => READ_BY_RABBIT.test(n))
    const many = sent.files.length > 1
    setBusy(reads
      ? { label: 'Reading your plan…', cycle: ['Reading your plan…', many ? `Reading all ${sent.files.length} pages…` : 'Finding the workouts…', 'Lining up the weeks…'] }
      : { label: 'Reading your plan…', cycle: ['Reading your plan…', 'Lining up the weeks…'] })
    try {
      handle(await api.upload(sent.files, sent.names, { start, sheet: sent.sheet, ...extra }), sent)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
      if (input.current) input.current.value = ''
    }
  }, [api, start, handle])

  const sendFiles = useCallback(async (list: FileList | File[]) => {
    const files = Array.from(list).slice(0, 10)
    if (!files.length) return
    if (list.length > 10) setHint('Up to 10 files at a time: the first 10 are being read.')
    void send(await fitForUpload(files))
  }, [send])

  const openLink = useCallback(async (url: string) => {
    setError(null); setHint(null)
    setBusy({ label: 'Opening the link…', cycle: ['Opening the link…', 'Reading the sheet…', 'Lining up the weeks…'] })
    try {
      handle(await api.link(url, { start }), { files: [new Blob([url], { type: 'text/plain' })], names: ['pasted.txt'] })
    } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }, [api, start, handle])

  const sendText = useCallback((t: string) => {
    const s = t.trim()
    if (!s) return
    if (isGoogleDocLink(s)) { void openLink(s); return }
    const link = linkHelp(s)
    if (link) { setHint(link); return }
    void send({ files: [new Blob([s], { type: 'text/plain' })], names: ['pasted.txt'] })
  }, [send, openLink])

  // Ctrl/Cmd+V anywhere on this screen: a screenshot or copied files go up as files,
  // copied cells (tab-separated) or text as a paste. Typing in the text box is left alone.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (busy || mapping) return
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT')) return
      const files = Array.from(e.clipboardData?.files ?? [])
      if (files.length) { e.preventDefault(); void sendFiles(files); return }
      const t = e.clipboardData?.getData('text/plain') ?? ''
      if (t.trim()) { e.preventDefault(); sendText(t) }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [busy, mapping, sendFiles, sendText])

  async function pickTemplate(t: PlanTemplate, opts: { level?: TemplateLevel; end?: 'race' }) {
    setError(null)
    setBusy({ label: `Building ${t.label}…`, cycle: [`Building ${t.label}…`, 'Sizing it to the hours there are…', 'Placing long days…'] })
    try { onPreview((await api.template(t.id, { start, ...opts })).preview) } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  if (mapping) {
    return <ColumnMapper info={mapping.info} aiLeft={status.ai_per_day > 0 ? status.ai_left : 0} busy={!!busy} error={error}
      onBack={() => { setMapping(null); setError(null) }}
      onUse={(m) => void send(mapping.sent, { map: m })}
      onAi={() => void send(mapping.sent, { ai: true })} />
  }

  const linkTyped = typing ? linkHelp(text) : null
  const googleTyped = typing && isGoogleDocLink(text)
  const dropProps = {
    onDragEnter: (e: React.DragEvent) => { if (e.dataTransfer.types.includes('Files')) { drags.current += 1; setDrag(true) } },
    onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes('Files')) e.preventDefault() },
    onDragLeave: () => { drags.current = Math.max(0, drags.current - 1); if (!drags.current) setDrag(false) },
    onDrop: (e: React.DragEvent) => { e.preventDefault(); drags.current = 0; setDrag(false); if (e.dataTransfer.files.length && !busy) void sendFiles(e.dataTransfer.files) },
  }
  return (
    <Screen title="Add a plan" subtitle="You'll check every week before anything changes" onBack={close} onClose={close} closing={closing}>
      <div {...dropProps} className="relative flex flex-col gap-5">
        {drag && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-start justify-center rounded-2xl border-2 border-dashed border-(--accent) bg-(--accent-subtle)/90 pt-16" aria-hidden>
            <span className="flex items-center gap-2 font-display text-[1.1765rem] text-(--accent)"><Upload className="size-5" /> Drop to read it</span>
          </div>
        )}
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
          <Card className="py-10"><RabbitLoader label={busy.label} cycle={busy.cycle} /></Card>
        ) : (
          <section className="flex flex-col gap-2.5" aria-label="How do you have it?">
            <div className="grid grid-cols-3 gap-2">
              <WayIn icon={<Upload />} title="Upload a file" text="Sheets, PDFs, photos, TrainingPeaks, Word"
                onClick={() => input.current?.click()} />
              <WayIn icon={<ClipboardPaste />} title="Paste text" text="An email, notes or a Google link"
                selected={typing} onClick={() => setTyping((x) => !x)} />
              <WayIn icon={<LayoutGrid />} title="Build in Rabbit" text="Week by week, with presets" onClick={onBuild} />
            </div>
            <input ref={input} type="file" multiple className="hidden" accept={ACCEPT}
              onChange={(e) => { if (e.target.files?.length) void sendFiles(e.target.files) }} />
            <p className="flex flex-wrap items-center gap-x-1 px-1 text-[0.6471rem] leading-snug text-(--text-muted)">
              <span className="hidden sm:inline">Drag files anywhere here, or press Ctrl/⌘+V to paste a screenshot or copied cells. </span>
              <span>Several photos of one plan? Pick them all at once.</span>
              <InfoTip label="What works" text="CSV, TSV, Excel and OpenDocument sheets (any columns: Rabbit maps them, or asks; workbooks with several sheets too), week grids (weeks down, Mon–Sun across), TrainingPeaks workout CSV and calendar .ics, Zwift .zwo and .erg/.mrc workouts, Word .docx, PDFs and photos of printed plans, pasted text or email, and Google Sheets/Docs links that are published or shared with anyone. Garmin .fit files: export as .zwo instead." />
            </p>
            <button type="button" onClick={() => setHelp(help === 'tp' ? null : 'tp')} aria-expanded={help === 'tp'}
              className="flex min-h-11 items-center gap-1.5 self-start px-1 text-[0.7647rem] font-medium text-(--accent)">
              <CalendarRange className="size-4" /> From TrainingPeaks? Here's how {help === 'tp' ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
            </button>
            {help === 'tp' && (
              <Card className="px-4 py-3">
                <ol className="flex list-decimal flex-col gap-2 pl-5 text-[0.7647rem] leading-snug text-(--text-secondary)">
                  <li><span className="font-medium text-(--text)">Workouts (CSV).</span> In TrainingPeaks open Settings → Export Data, export workouts as CSV for the dates you want, then upload the .csv.</li>
                  <li><span className="font-medium text-(--text)">Calendar (iCal).</span> In calendar settings copy the iCal feed link, open it in a browser to save the .ics, then upload it.</li>
                  <li><span className="font-medium text-(--text)">A training plan with weeks, not dates.</span> Upload it and choose “End on race day” in the review: Rabbit lines the last week up with your race, like applying a plan in TrainingPeaks.</li>
                  <li><span className="font-medium text-(--text)">Single structured workouts.</span> Export as Zwift .zwo (or .erg/.mrc): the intervals arrive as steps that sync to Garmin.</li>
                </ol>
              </Card>
            )}
          </section>
        )}

        {typing && !busy && (
          <Card className="flex flex-col gap-2.5 px-4 py-3.5">
            <textarea aria-label="Plan text" className={cn(areaCls, 'min-h-36')} autoFocus value={text} onChange={(e) => setText(e.target.value)}
              placeholder={'Paste the plan: an email, notes, copied spreadsheet cells, or a Google Sheets/Docs link.\nWeek 1: Mon rest, Tue 6x400 at 5K pace, Thu 40\' easy, Sat long run 90\''} />
            {linkTyped && <LinkHint text={linkTyped} />}
            {googleTyped && <p className="text-[0.7059rem] leading-snug text-(--text-muted)">Rabbit opens Google links that are published to the web or shared with “anyone with the link”.</p>}
            <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" disabled={!text.trim() || !!linkTyped} onClick={() => sendText(text)}>
              {googleTyped ? <><Link2 className="size-4" /> Open the link</> : <><ScanText className="size-4" aria-hidden /> Read it</>}
            </Button>
            {status.ai_per_day > 0 && !googleTyped && <p className="text-[0.6471rem] text-(--text-muted)">Rabbit reads text, PDFs and photos: {status.ai_left} of {status.ai_per_day} reads left today. Spreadsheets and workout files don't count.</p>}
          </Card>
        )}

        {hint && <LinkHint text={hint} />}
        {error && <ErrorState compact message={error} />}

        <div className="-mt-2 flex items-center gap-2 px-1 text-[0.7059rem] text-(--text-muted)">
          <span className="min-w-0 flex-1">Plans without dates (“Week 1, Tue”) start <span className="font-medium text-(--text-secondary)">{short(start)}</span>; change it in the review.</span>
          <button type="button" className="min-h-11 px-1 font-medium text-(--accent)" onClick={() => setEditStart((x) => !x)}>{editStart ? 'Done' : 'Change'}</button>
        </div>
        {editStart && (
          <Card className="px-0 py-0">
            <Field label="Week 1 starts on" hint="Weeks run Monday to Sunday.">
              <input type="date" className={inputCls} value={start} onChange={(e) => e.target.value && setStart(mondayOf(e.target.value))} />
            </Field>
          </Card>
        )}

        <Templates tpl={tpl} busy={!!busy} who={who} api={api} onPick={(t, o) => void pickTemplate(t, o)} onMine={(mine) => setTpl((x) => x && { ...x, mine })} />

        <Card>
          <button type="button" onClick={() => setHelp(help === 'csv' ? null : 'csv')} aria-expanded={help === 'csv'}
            className="flex min-h-12 w-full items-center gap-2.5 px-4 text-left active:bg-(--bg-inset)">
            <FileSpreadsheet className="size-4 text-(--accent)" />
            <span className="flex-1 text-[0.8235rem] text-(--text)">Making your own spreadsheet?</span>
            {help === 'csv' ? <ChevronUp className="size-4 text-(--text-muted)" /> : <ChevronDown className="size-4 text-(--text-muted)" />}
          </button>
          {help === 'csv' && (
            <div className="px-4 pb-3.5">
              <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">One row per workout with a date (or week + day), sport, title and time works best, in any column order. A week grid works too (weeks down, Monday to Sunday across, cells like “45' easy run”).</p>
              <a href={api.templateUrl} download="rabbit-plan-template.csv"
                className="mt-2 inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-(--border) px-3 text-[0.7647rem] font-medium text-(--text)">
                <Download className="size-4" /> Download the CSV template
              </a>
            </div>
          )}
        </Card>

        {hasPlan && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[0.7059rem] text-(--text-muted)">
            <span>Download the current plan:</span>
            <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('csv')} download><Download className="size-3.5" /> CSV</a>
            <a className="inline-flex min-h-11 items-center gap-1 font-medium text-(--accent)" href={api.exportUrl('ics')} download><CalendarRange className="size-3.5" /> Calendar (.ics)</a>
          </div>
        )}
      </div>
    </Screen>
  )
}

function WayIn({ icon, title, text, onClick, selected }: { icon: React.ReactNode; title: string; text: string; onClick: () => void; selected?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={cn('flex min-h-32 flex-col items-center justify-start gap-1.5 rounded-2xl border px-2 py-3.5 text-center transition-colors active:bg-(--bg-inset)',
        selected ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
      <span className="flex size-11 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent) [&>svg]:size-5">{icon}</span>
      <span className="text-[0.8235rem] font-semibold leading-tight text-(--text)">{title}</span>
      <span className="text-[0.6471rem] leading-snug text-(--text-muted)">{text}</span>
    </button>
  )
}

// ------------------------------------------------------------- templates --
const FEATURED = ['5k', '10k', 'half', 'marathon', '50k', 'olympic', '70.3']

function Templates({ tpl, busy, who, api, onPick, onMine }: {
  tpl: TemplateList | null; busy: boolean; who: Who; api: ImportApi
  onPick: (t: PlanTemplate, o: { level?: TemplateLevel; end?: 'race' }) => void
  onMine: (mine: PlanTemplate[]) => void
}) {
  const [level, setLevel] = useState<TemplateLevel>('beginner')
  const [onRace, setOnRace] = useState(true)
  const [more, setMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!tpl) return <RabbitLoader inline className="px-1 text-[0.7059rem]" label="Loading templates" />
  const race = tpl.race_date && onRace ? 'race' as const : undefined
  const featured = FEATURED.map((id) => tpl.templates.find((t) => t.id === id)).filter((t): t is PlanTemplate => !!t)
  const rest = tpl.templates.filter((t) => !FEATURED.includes(t.id))
  const tile = (t: PlanTemplate, raceable: boolean) => (
    <button key={t.id} type="button" disabled={busy} onClick={() => onPick(t, raceable ? { level, end: race } : {})}
      className="flex min-h-16 flex-col items-start justify-center rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2 text-left active:bg-(--bg-inset) disabled:opacity-50">
      <span className="text-[0.8235rem] font-medium text-(--text)">{t.label}</span>
      <span className="text-[0.6471rem] leading-snug text-(--text-muted)">{raceable && race ? `Ends ${fmtDay(tpl.race_date!, { month: 'short', day: 'numeric' })}` : `${t.weeks} weeks`} · {t.blurb}</span>
    </button>
  )
  return (
    <section className="flex flex-col gap-2.5">
      <h3 className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Start from a template</h3>
      {tpl.mine && tpl.mine.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="px-1 text-[0.7059rem] font-medium text-(--text-secondary)">My templates</p>
          {tpl.mine.map((t) => (
            <div key={t.id} className="flex items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) pr-1">
              <button type="button" disabled={busy} onClick={() => onPick(t, {})} className="flex min-h-14 min-w-0 flex-1 flex-col justify-center px-3 py-2 text-left disabled:opacity-50">
                <span className="truncate text-[0.8235rem] font-medium text-(--text)">{t.label}</span>
                <span className="text-[0.6471rem] text-(--text-muted)">{t.blurb} · starts the week you pick</span>
              </button>
              <button type="button" aria-label={`Delete ${t.label}`} className="hit-44 rounded p-2 text-(--text-muted)"
                onClick={() => { setError(null); api.deleteMine(t.id).then((r) => onMine(r.mine), (e) => setError((e as Error).message)) }}><Trash2 className="size-4" /></button>
            </div>
          ))}
          {error && <p className="px-1 text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 px-1">
        <ChipRow>
          {(tpl.levels.length ? tpl.levels : ['beginner', 'intermediate'] as TemplateLevel[]).map((l) => (
            <Chip key={l} selected={level === l} onClick={() => setLevel(l)}>{l === 'beginner' ? 'Beginner' : 'Intermediate'}</Chip>
          ))}
        </ChipRow>
      </div>
      {tpl.race_date && (
        <label className="flex min-h-11 items-center gap-2.5 px-1 text-[0.7647rem] text-(--text-secondary)">
          <input type="checkbox" className="size-4 accent-(--accent)" checked={onRace} onChange={(e) => setOnRace(e.target.checked)} />
          <span>End on {who === 'coach' ? 'their' : 'your'} race day{tpl.race_title ? ` (${tpl.race_title}, ` : ' ('}{fmtDay(tpl.race_date, { month: 'short', day: 'numeric' })})</span>
        </label>
      )}
      <div className="grid grid-cols-2 gap-2">{featured.map((t) => tile(t, true))}</div>
      {rest.length > 0 && (
        <>
          <button type="button" onClick={() => setMore((x) => !x)} aria-expanded={more} className="flex min-h-11 items-center gap-1 self-start px-1 text-[0.7647rem] font-medium text-(--accent)">
            {more ? 'Fewer templates' : `${rest.length} more templates`} {more ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
          {more && <div className="grid grid-cols-2 gap-2">{rest.map((t) => tile(t, t.group !== 'general'))}</div>}
        </>
      )}
      <p className="px-1 text-[0.6471rem] leading-snug text-(--text-muted)">Built by Rabbit's plan builder for the weekly hours and training days in the profile. Tap one to preview it.</p>
    </section>
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

// --------------------------------------------------------- column mapping --
const FIELD_LABEL: Record<MapField, string> = {
  date: 'Date', week: 'Week number', weekday: 'Day of the week', sport: 'Sport', title: 'Workout',
  duration: 'Duration', distance: 'Distance', intensity: 'Intensity / zone / RPE', notes: 'Notes',
}
const FIELD_HINT: Partial<Record<MapField, string>> = {
  date: 'Or week number + day', duration: '45, 1:15, 1h 30m, 1.5 h', distance: 'km, mi, m or yd', title: 'Or sport',
}

function ColumnMapper({ info, aiLeft, busy, error, onBack, onUse, onAi }: {
  info: ColumnMapping; aiLeft: number; busy: boolean; error: string | null
  onBack: () => void; onUse: (m: MapChoice) => void; onAi: () => void
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
  const used = new Map<number, MapField>()
  for (const [f, j] of Object.entries(cols)) if (j != null) used.set(j, f as MapField)
  const shown = Array.from({ length: Math.min(info.columns, 8) }, (_, j) => j)
  const footer = (
    <>
      <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={onBack}>Back</Button>
      <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy} disabled={!hasWhen || !hasWhat}
        onClick={() => onUse({ header_row: info.header_row, cols })}>Use these columns</Button>
    </>
  )
  return (
    <Screen title="Match the columns" subtitle={info.name} onBack={onBack} onClose={onBack} footer={footer}>
      <p className="px-1 text-[0.7647rem] leading-snug text-(--text-muted)">Rabbit wasn't sure about this sheet, so it guessed what each column means. Fix anything that's off: it needs a date (or week + day) and what the workout is.</p>
      <Card>
        <p className="border-b border-(--border) px-4 py-2 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Your sheet: first 3 rows</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-max text-left text-[0.7059rem]">
            <thead>
              <tr className="border-b border-(--border)">
                {shown.map((j) => (
                  <th key={j} className={cn('px-3 py-1.5 font-medium', used.has(j) ? 'text-(--accent)' : 'text-(--text-muted)')}>
                    <span className="block max-w-[8rem] truncate">{name(j)}</span>
                    <span className="block text-[0.6471rem] font-normal">{used.has(j) ? FIELD_LABEL[used.get(j)!] : 'not used'}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {info.sample.slice(0, 3).map((r, i) => (
                <tr key={i} className="border-b border-(--border) last:border-0">
                  {shown.map((j) => <td key={j} className="px-3 py-1.5 text-(--text)"><span className="block max-w-[8rem] truncate">{r[j] ?? ''}</span></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
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
          <RabbitLogo size={16} current /> Let Rabbit read it instead
        </button>
      )}
    </Screen>
  )
}
