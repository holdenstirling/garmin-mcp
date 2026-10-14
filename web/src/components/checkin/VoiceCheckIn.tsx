// Voice check-in: tap the mic, say how it felt ("felt heavy, left calf a bit tight, slept
// badly, legs 6 out of 10"), check the transcript, and Rabbit turns it into a structured
// check-in (server: checkins.py) that the Today card and plan adjustments use.
//
// States: idle -> listening -> review -> saving -> done. Speech uses the Web Speech API
// (SpeechRecognition / webkitSpeechRecognition) with interim results; it stops on a tap or
// after ~4 s of silence. Without speech support (or with the mic denied) it's a textarea.
// Quick chips work everywhere for when talking isn't an option.
//
// Exported for other screens (the post-workout card opens it with a session/activity id).
import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, Keyboard, Mic, Pencil, X } from 'lucide-react'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Chip, ChipRow } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { hapticTap } from '@/lib/haptics'
import { celebrate } from '@/components/fx/motion'
import { DENIED_ERRORS, speechCtor, type SpeechRecognizer, type SpeechResultEvent } from '@/lib/speech'
import {
  AREA_LABEL, checkinChips, createCheckin, sorenessLabel, updateCheckin,
  type Area, type Checkin, type CheckinEdit, type Side, type Sleep,
} from '@/lib/checkins'

const SILENCE_MS = 4000
const FIRST_WORDS_MS = 7000
const TEXT_MAX = 1000
const FACES: [number, string, string][] = [[1, '😫', 'Awful'], [2, '🙁', 'Rough'], [3, '😐', 'OK'], [4, '🙂', 'Good'], [5, '😄', 'Great']]
const PHRASES = ['Legs heavy', 'Felt great', 'Slept badly'] as const
const HURT_AREAS: Area[] = ['calf', 'shin', 'achilles', 'knee', 'hamstring', 'quad', 'hip', 'glute', 'lower_back', 'foot', 'ankle', 'it_band', 'shoulder', 'other']

type Phase = 'idle' | 'listening' | 'review' | 'saving' | 'done'

export type VoiceCheckInProps = {
  open: boolean
  onClose: () => void
  /** plan session this is about (optional) */
  sessionId?: string
  /** Garmin activity this is about (optional) */
  activityId?: string | number
  /** sheet title; defaults to "How did it feel?" */
  title?: string
  /** after a save (and after an edit): the stored check-in and the XP it earned (0 or 10) */
  onSaved?: (c: Checkin, xp: number) => void
}

export function VoiceCheckIn(props: VoiceCheckInProps) {
  // Portal: it may open from inside another sheet, whose transform would trap a fixed overlay.
  return props.open ? createPortal(<VoiceSheet {...props} />, document.body) : null
}

// React events bubble through portals; keep this sheet's drags away from a parent sheet's.
const own = (e: SyntheticEvent) => e.stopPropagation()

function VoiceSheet({ onClose, sessionId, activityId, title, onSaved }: VoiceCheckInProps) {
  const [closing, setClosing] = useState(false)
  const drag = useSheetDrag(onClose)
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  const supported = speechCtor() !== null
  const [phase, setPhase] = useState<Phase>('idle')
  const [typing, setTyping] = useState(!supported)
  const [text, setText] = useState('')
  const [interim, setInterim] = useState('')
  const [feel, setFeel] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(supported ? null : "Voice isn't available in this browser. Type it instead.")
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<{ c: Checkin; xp: number } | null>(null)

  // ----------------------------------------------------------- speech ---
  const rec = useRef<SpeechRecognizer | null>(null)
  const finalText = useRef('')
  const interimRef = useRef('')
  const silence = useRef<number | null>(null)
  const phaseRef = useRef<Phase>('idle')
  useEffect(() => { phaseRef.current = phase }, [phase])

  const clearSilence = () => { if (silence.current !== null) { window.clearTimeout(silence.current); silence.current = null } }
  const stop = useCallback(() => {
    clearSilence()
    try { rec.current?.stop() } catch { /* already stopped */ }
  }, [])
  const armSilence = useCallback((ms: number) => {
    clearSilence()
    silence.current = window.setTimeout(stop, ms)
  }, [stop])

  useEffect(() => () => { clearSilence(); try { rec.current?.abort() } catch { /* gone */ } }, [])

  const listen = () => {
    const Ctor = speechCtor()
    if (!Ctor) { setTyping(true); setPhase('review'); return }
    setError(null); setNotice(null)
    const r = new Ctor()
    r.lang = navigator.language || 'en-US'
    r.interimResults = true
    r.maxAlternatives = 1
    try { r.continuous = true } catch { /* some engines only do one phrase */ }
    const base = text.trim() ? `${text.trim()} ` : ''
    finalText.current = ''
    r.onresult = (e: SpeechResultEvent) => {
      let live = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        const said = res?.[0]?.transcript ?? ''
        if (res?.isFinal) finalText.current += said.endsWith(' ') ? said : `${said} `
        else live += said
      }
      setText((base + finalText.current).slice(0, TEXT_MAX))
      interimRef.current = live
      setInterim(live)
      armSilence(SILENCE_MS)
    }
    r.onerror = (e) => {
      if (DENIED_ERRORS.has(e.error)) {
        setTyping(true)
        setNotice(e.error === 'not-allowed' || e.error === 'service-not-allowed'
          ? 'Microphone access is off. Type it instead, or allow the mic in your browser settings.'
          : "Voice isn't working here. Type it instead.")
      } else if (e.error !== 'no-speech' && e.error !== 'aborted') {
        setNotice("Didn't catch that. Try again or type it.")
      }
    }
    r.onend = () => {
      clearSilence()
      rec.current = null
      const live = interimRef.current.trim()
      interimRef.current = ''
      setInterim('')
      if (live) setText((t) => `${t.trim()} ${live}`.trim().slice(0, TEXT_MAX))
      if (phaseRef.current === 'listening') setPhase('review')
    }
    rec.current = r
    try {
      r.start()
      hapticTap()
      setPhase('listening')
      armSilence(FIRST_WORDS_MS)
    } catch {
      rec.current = null
      setTyping(true); setPhase('review')
      setNotice("Couldn't start the microphone. Type it instead.")
    }
  }

  // ------------------------------------------------------------ chips ---
  const addPhrase = (p: string) => {
    if (phase === 'listening') stop()
    setText((t) => {
      const cur = t.trim()
      if (cur.toLowerCase().includes(p.toLowerCase())) return t
      return (cur ? `${cur.replace(/[.,;]$/, '')}, ${p.toLowerCase()}` : p).slice(0, TEXT_MAX)
    })
    if (phase === 'idle') { setTyping(true); setPhase('review') }
  }

  // ------------------------------------------------------------- save ---
  const canSave = text.trim().length > 0 || feel !== null
  async function save() {
    if (!canSave) return
    setPhase('saving'); setError(null)
    try {
      const r = await createCheckin({
        text: text.trim(), ...(feel !== null ? { feel } : {}),
        ...(sessionId ? { session_id: sessionId } : {}), ...(activityId != null ? { activity_id: activityId } : {}),
      })
      setSaved({ c: r.checkin, xp: r.xp })
      setPhase('done')
      onSaved?.(r.checkin, r.xp)
    } catch (e) {
      setError((e as Error).message)
      setPhase('review')
    }
  }

  const heading = title ?? 'How did it feel?'
  return (
    <div className={`modal-overlay ${closing ? 'modal-overlay--exit' : ''}`}
      onClick={(e) => { e.stopPropagation(); close() }}
      onTouchStart={own} onTouchMove={own} onTouchEnd={own} onTouchCancel={own} onKeyDown={own}>
      <div className={`modal ${closing ? 'modal--exit' : ''}`} onClick={(e) => e.stopPropagation()} {...drag}
        aria-label={heading}>
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 className="modal-title">{heading}</h2>
          <button className="modal-close" aria-label="Close" onClick={close}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {phase === 'done' && saved ? (
            <Result saved={saved} onDone={close}
              onEdited={(c) => { setSaved((s) => s && { ...s, c }); onSaved?.(c, 0) }} />
          ) : phase === 'saving' ? (
            <RabbitLoader className="py-10" label="Making sense of it…" />
          ) : (
            <>
              {!typing && (
                <MicStage listening={phase === 'listening'} transcript={text} interim={interim}
                  onTap={() => (phase === 'listening' ? stop() : listen())} />
              )}
              {notice && <p className="px-1 text-center text-[0.7059rem] text-(--warning-text)" role="status">{notice}</p>}

              {(typing || phase === 'review') && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="checkin-text" className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                    {typing && phase !== 'review' ? 'How did it go?' : 'What you said (edit if needed)'}
                  </label>
                  <textarea id="checkin-text" rows={3} maxLength={TEXT_MAX} value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="e.g. felt heavy, left calf a bit tight, slept badly, legs 6 out of 10"
                    className="w-full resize-none rounded-xl border border-(--border-strong) bg-(--bg-surface) px-3 py-2.5 text-[0.8824rem] leading-snug text-(--text) placeholder:text-(--text-muted)/70 focus:border-(--accent) focus:outline-none" />
                </div>
              )}

              <QuickChips feel={feel} onFeel={(v) => setFeel((f) => (f === v ? null : v))} onPhrase={addPhrase} />

              {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}

              <div className="flex flex-wrap items-center gap-2">
                {supported && typing && (
                  <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={() => { setTyping(false); listen() }}>
                    <Mic className="size-4" /> Talk
                  </Button>
                )}
                {supported && !typing && phase === 'idle' && (
                  <Button variant="ghost" className="h-11 gap-1.5 px-3 text-[0.7647rem]" onClick={() => setTyping(true)}>
                    <Keyboard className="size-4" /> Type instead
                  </Button>
                )}
                {supported && !typing && phase === 'review' && (
                  <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={listen}>
                    <Mic className="size-4" /> Add more
                  </Button>
                )}
                <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" disabled={!canSave || phase === 'listening'}
                  onClick={() => void save()}>
                  Save check-in
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** The big round mic with a pulsing ring and a little animated "voice" while listening. */
function MicStage({ listening, transcript, interim, onTap }: {
  listening: boolean; transcript: string; interim: string; onTap: () => void
}) {
  const shown = `${transcript}${interim ? ` ${interim}` : ''}`.trim()
  return (
    <div className="flex flex-col items-center gap-3 pt-2">
      <button type="button" onClick={onTap} aria-pressed={listening}
        aria-label={listening ? 'Stop listening' : 'Start talking'}
        className={cn('voice-mic', listening && 'voice-mic--on')}>
        {listening && <span className="voice-mic__ring" aria-hidden="true" />}
        <Mic className="relative size-9" />
      </button>
      <div className="flex h-6 items-center gap-2">
        {listening ? (
          <>
            <span className="voice-wave" aria-hidden="true"><i /><i /><i /><i /><i /></span>
            <RabbitLoader inline label="Listening…" />
          </>
        ) : (
          <span className="text-[0.7647rem] text-(--text-muted)">Tap and tell Rabbit how it felt</span>
        )}
      </div>
      {listening && (
        <p className="min-h-[3.2em] w-full rounded-xl bg-(--bg-inset) px-3 py-2 text-center text-[0.8824rem] leading-snug text-(--text)" aria-live="polite">
          {shown || <span className="text-(--text-muted)">Legs, sleep, anything tight or sore…</span>}
        </p>
      )}
    </div>
  )
}

function QuickChips({ feel, onFeel, onPhrase }: {
  feel: number | null; onFeel: (v: number) => void; onPhrase: (p: string) => void
}) {
  const [hurt, setHurt] = useState(false)
  const [side, setSide] = useState<Side | null>(null)
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex justify-between gap-1" role="group" aria-label="Overall feel">
        {FACES.map(([v, face, label]) => (
          <button key={v} type="button" onClick={() => onFeel(v)} aria-pressed={feel === v} aria-label={`Feel ${v} of 5: ${label}`}
            className={cn('flex flex-1 flex-col items-center gap-0.5 rounded-xl border py-1.5 transition-colors',
              feel === v ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
            <span className="text-[1.35rem] leading-none" aria-hidden="true">{face}</span>
            <span className="text-[0.6471rem] text-(--text-muted)">{label}</span>
          </button>
        ))}
      </div>
      <ChipRow>
        {PHRASES.map((p) => <Chip key={p} onClick={() => onPhrase(p)}>{p}</Chip>)}
        <Chip selected={hurt} onClick={() => setHurt((h) => !h)}>Something hurts</Chip>
      </ChipRow>
      {hurt && (
        <div className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) p-3">
          <ChipRow>
            {(['left', 'right', 'both'] as Side[]).map((s) => (
              <Chip key={s} selected={side === s} onClick={() => setSide((x) => (x === s ? null : s))}>
                {s[0]!.toUpperCase() + s.slice(1)}
              </Chip>
            ))}
          </ChipRow>
          <ChipRow>
            {HURT_AREAS.map((a) => (
              <Chip key={a} onClick={() => {
                const name = a === 'other' ? 'something' : AREA_LABEL[a].toLowerCase()
                const where = a === 'other' ? 'something hurts' : side === 'both' ? `both ${name}s sore` : `${side ? `${side} ` : ''}${name} sore`
                onPhrase(where)
              }}>{AREA_LABEL[a]}</Chip>
            ))}
          </ChipRow>
        </div>
      )}
    </div>
  )
}

/** The saved check-in as friendly chips, with "Looks right" / "Edit". */
function Result({ saved, onDone, onEdited }: {
  saved: { c: Checkin; xp: number }; onDone: () => void; onEdited: (c: Checkin) => void
}) {
  const { c, xp } = saved
  const [editing, setEditing] = useState(false)
  // Saved: a small carrot burst from the check mark (once, when the result first shows).
  const mark = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const t = window.setTimeout(() => celebrate(mark.current, 'checkin'), 120)
    return () => window.clearTimeout(t)
  }, [])
  const chips = checkinChips(c)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <span ref={mark} className="celebrate flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent) text-white"><Check className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[0.9412rem] font-medium leading-snug text-(--text)">{c.summary || 'Checked in.'}</p>
          <p className="text-[0.7059rem] text-(--text-muted)">Saved. Rabbit will use it for your next days.</p>
        </div>
        {xp > 0 && <span className="fx-hop shrink-0 rounded-full bg-(--accent-subtle) px-2.5 py-1 font-mono text-[0.7059rem] font-semibold text-(--accent)">+{xp} XP</span>}
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((ch) => (
            <span key={ch.label} className={cn('rounded-full border px-2.5 py-1 text-[0.7059rem] font-medium',
              ch.warn ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)' : 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)')}>
              {ch.label}
            </span>
          ))}
        </div>
      )}
      {c.pain_flag && (
        <p className="rounded-xl border border-(--warning)/30 bg-(--warning-subtle) px-3 py-2.5 text-[0.7647rem] leading-snug text-(--text)" role="note">
          Rabbit will ease the next few days. If pain is sharp or getting worse, check with a physio or doctor.
        </p>
      )}
      {editing ? (
        <EditCheckin c={c} onCancel={() => setEditing(false)} onSaved={(n) => { onEdited(n); setEditing(false) }} />
      ) : (
        <div className="flex gap-2">
          <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={() => setEditing(true)}>
            <Pencil className="size-4" /> Edit
          </Button>
          <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" onClick={onDone}>Looks right</Button>
        </div>
      )}
    </div>
  )
}

/** The athlete corrects what Rabbit understood. */
export function EditCheckin({ c, onCancel, onSaved }: { c: Checkin; onCancel: () => void; onSaved: (c: Checkin) => void }) {
  const [d, setD] = useState<Required<Pick<CheckinEdit, 'feel' | 'rpe' | 'sleep' | 'soreness' | 'pain_flag'>>>({
    feel: c.feel, rpe: c.rpe, sleep: c.sleep, soreness: c.soreness, pain_flag: c.pain_flag,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function save() {
    setBusy(true); setError(null)
    try { onSaved((await updateCheckin(c.id, d)).checkin) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const label = 'font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)'
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-3">
      <span className={label}>Feel</span>
      <ChipRow>
        {FACES.map(([v, face]) => (
          <Chip key={v} selected={d.feel === v} onClick={() => setD((x) => ({ ...x, feel: x.feel === v ? null : v }))}>{face} {v}</Chip>
        ))}
      </ChipRow>
      <span className={label}>Effort (RPE)</span>
      <ChipRow>
        {Array.from({ length: 10 }, (_, i) => i + 1).map((v) => (
          <Chip key={v} selected={d.rpe === v} onClick={() => setD((x) => ({ ...x, rpe: x.rpe === v ? null : v }))}>{v}</Chip>
        ))}
      </ChipRow>
      <span className={label}>Sleep</span>
      <ChipRow>
        {(['poor', 'ok', 'good'] as Sleep[]).map((v) => (
          <Chip key={v} selected={d.sleep === v} onClick={() => setD((x) => ({ ...x, sleep: x.sleep === v ? null : v }))}>{v}</Chip>
        ))}
      </ChipRow>
      {d.soreness.length > 0 && <>
        <span className={label}>Sore spots (tap to remove)</span>
        <ChipRow>
          {d.soreness.map((s, i) => (
            <Chip key={`${s.area}-${s.side}`} selected onClick={() => setD((x) => ({ ...x, soreness: x.soreness.filter((_, j) => j !== i) }))}>
              {sorenessLabel(s)} <X className="ml-1 inline size-3" />
            </Chip>
          ))}
        </ChipRow>
      </>}
      <label className="flex items-center gap-2 text-[0.7647rem] text-(--text)">
        <input type="checkbox" checked={d.pain_flag} onChange={(e) => setD((x) => ({ ...x, pain_flag: e.target.checked }))} />
        Real pain (sharp, getting worse, or limping)
      </label>
      {error && <p className="text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
      <div className="flex gap-2">
        <Button variant="ghost" className="h-10 px-3 text-[0.7647rem]" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" className="h-10 flex-1 text-[0.7647rem]" loading={busy} onClick={() => void save()}>Save changes</Button>
      </div>
    </div>
  )
}

/** Compact chips for a check-in (SessionSheet, lists). */
export function CheckinChips({ c, className }: { c: Checkin; className?: string }) {
  const chips = checkinChips(c)
  if (!chips.length) return <p className={cn('text-[0.7647rem] text-(--text-secondary)', className)}>{c.summary}</p>
  return (
    <div className={cn('flex flex-wrap gap-1.5', className)}>
      {chips.map((ch) => (
        <span key={ch.label} className={cn('rounded-full border px-2 py-0.5 text-[0.6471rem] font-medium',
          ch.warn ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)' : 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)')}>
          {ch.label}
        </span>
      ))}
    </div>
  )
}
