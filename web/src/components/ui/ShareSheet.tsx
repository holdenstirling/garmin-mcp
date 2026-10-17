// Share anything by text: one button + sheet used by the workout page, recorded workouts,
// events, clubs and DM cards. Opening the sheet makes a public read-only link (lib/sharelinks),
// pre-fills a friendly message (editable), then: the phone's share menu (Messages first on iOS),
// a plain "Text message" (sms:), "Copy link", "Send in Rabbit" (direct messages) and an image
// card. No heart rate or location is shared unless the person turns heart rate on.
import { useEffect, useRef, useState } from 'react'
import { Check, Copy, Image as ImageIcon, Link2, MessageCircle, MessageSquareText, Share2, Smartphone } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { RabbitLoader } from '@/components/RabbitLoader'
import { areaCls } from '@/components/plan/ui'
import { CARD_W, fit, rabbit, roundRect, shareImage } from '@/components/reward/monthCard'
import {
  SHARE_KIND_LABEL, canNativeShare, createShareLink, nativeShare, smsHref, type ShareLink, type ShareTarget,
} from '@/lib/sharelinks'
import { cn } from '@/lib/utils'

const IMG_H = 1080
const BG = '#1a3a2a'
const INK = '#f5f0e8'
const SOFT = '#a8d5b5'
const SERIF = "'DM Serif Display', Georgia, serif"
const SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

function wrap(ctx: CanvasRenderingContext2D, text: string, max: number, lines: number): string[] {
  const words = text.split(/\s+/)
  const out: string[] = []
  let cur = ''
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w
    if (ctx.measureText(next).width > max && cur) { out.push(cur); cur = w } else cur = next
    if (out.length === lines) break
  }
  if (out.length < lines && cur) out.push(cur)
  return out.slice(0, lines)
}

async function drawShareCard(canvas: HTMLCanvasElement, kicker: string, title: string, body: string): Promise<void> {
  try { await document.fonts.load(`80px ${SERIF}`) } catch { /* fallback fonts */ }
  canvas.width = CARD_W
  canvas.height = IMG_H
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const pad = 88
  ctx.fillStyle = BG
  ctx.fillRect(0, 0, CARD_W, IMG_H)
  ctx.globalAlpha = 0.07
  rabbit(ctx, CARD_W - 520, IMG_H - 560, 560, INK)
  ctx.globalAlpha = 1
  rabbit(ctx, pad, pad - 6, 60, INK)
  ctx.fillStyle = INK
  ctx.font = `42px ${SERIF}`
  ctx.fillText('Rabbit', pad + 76, pad + 42)
  ctx.fillStyle = SOFT
  ctx.font = `600 30px ${SANS}`
  ctx.fillText(kicker.toUpperCase(), pad, 300)
  ctx.fillStyle = INK
  ctx.fillText(fit(ctx, title, CARD_W - pad * 2, 96, SERIF), pad, 410)
  ctx.font = `40px ${SANS}`
  ctx.fillStyle = 'rgba(245, 240, 232, 0.86)'
  wrap(ctx, body, CARD_W - pad * 2, 5).forEach((ln, i) => ctx.fillText(ln, pad, 510 + i * 58))
  roundRect(ctx, pad, IMG_H - pad - 80, 330, 80, 40)
  ctx.fillStyle = SOFT
  ctx.fill()
  ctx.fillStyle = BG
  ctx.font = `600 32px ${SANS}`
  ctx.fillText('Join me on Rabbit', pad + 30, IMG_H - pad - 28)
}

export function ShareSheet({ target, hrOption, onSendInRabbit, onClose }: {
  target: ShareTarget
  /** offer "Include heart rate" (your own Garmin workouts only) */
  hrOption?: boolean
  /** "Send in Rabbit": the existing direct-message flow */
  onSendInRabbit?: () => void
  onClose: () => void
}) {
  const [hr, setHr] = useState(false)
  const [link, setLink] = useState<ShareLink | null>(null)
  const [text, setText] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState<'image' | null>(null)
  const edited = useRef(false)
  const canvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    let live = true
    setErr(null)
    createShareLink(target, hrOption ? { include_hr: hr } : {}).then((l) => {
      if (!live) return
      setLink(l)
      if (!edited.current) setText(l.text)
    }, (e: Error) => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [target.kind, target.ref, hr]) // eslint-disable-line react-hooks/exhaustive-deps

  const native = canNativeShare()
  async function share() {
    if (!link) return
    const r = await nativeShare(link.title, text, link.url)
    if (r === 'shared') onClose()
  }
  async function copy() {
    if (!link) return
    try {
      await navigator.clipboard.writeText(`${text} ${link.url}`.trim())
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch { setErr("Couldn't copy here. Press and hold the link to copy it.") }
  }
  async function image() {
    if (!link || !canvas.current) return
    setBusy('image')
    try {
      await drawShareCard(canvas.current, SHARE_KIND_LABEL[target.kind], link.title, text)
      await shareImage(canvas.current, 'rabbit-share.png', link.title)
    } finally { setBusy(null) }
  }

  const row = 'flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-left text-[0.8824rem] text-(--text) active:bg-(--bg-inset)'
  return (
    <Sheet title={`Share ${target.label ? `“${target.label}”` : SHARE_KIND_LABEL[target.kind].toLowerCase()}`} onClose={onClose} portal
      footer={
        <div className="flex gap-2 border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          {native ? (
            <Button variant="primary" className="h-12 flex-1 gap-2 text-[0.8824rem]" disabled={!link} onClick={() => void share()}>
              <Share2 className="size-4" aria-hidden /> Share…
            </Button>
          ) : (
            <a href={link ? smsHref(text, link.url) : undefined} aria-disabled={!link}
              className={cn('flex h-12 flex-1 items-center justify-center gap-2 rounded-md bg-(--accent) text-[0.8824rem] font-semibold text-(--on-fill)', !link && 'pointer-events-none opacity-50')}>
              <MessageSquareText className="size-4" aria-hidden /> Text message
            </a>
          )}
        </div>
      }>
      <div className="flex flex-col gap-4 p-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-[0.7059rem] font-semibold uppercase tracking-widest text-(--text-muted)">Message</span>
          <textarea className={areaCls} rows={3} maxLength={300} value={text}
            onChange={(e) => { edited.current = true; setText(e.target.value) }} aria-label="Message to send with the link" />
        </label>

        <div className="flex min-h-11 items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 text-[0.7647rem] text-(--text-secondary)" aria-live="polite">
          <Link2 className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
          {err ? <span className="text-(--danger)">{err}</span>
            : link ? <span className="min-w-0 flex-1 truncate font-mono tabular-nums">{link.url.replace(/^https?:\/\//, '')}</span>
            : <RabbitLoader inline label="Making a link" />}
        </div>

        {hrOption && (
          <label className="flex min-h-11 items-center justify-between gap-3 text-[0.8235rem] text-(--text)">
            <span>Include heart rate<span className="block text-[0.7059rem] text-(--text-muted)">Off: friends see distance, time and pace only. Never your location.</span></span>
            <input type="checkbox" className="size-5 accent-(--accent)" checked={hr} onChange={(e) => { setLink(null); setHr(e.target.checked) }} />
          </label>
        )}

        <div className="flex flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) p-1">
          {native && (
            <a href={link ? smsHref(text, link.url) : undefined} className={cn(row, !link && 'pointer-events-none opacity-50')}>
              <Smartphone className="size-4 text-(--accent)" aria-hidden /> Text message
            </a>
          )}
          <button type="button" className={row} disabled={!link} onClick={() => void copy()}>
            {copied ? <Check className="size-4 text-(--accent)" aria-hidden /> : <Copy className="size-4 text-(--accent)" aria-hidden />}
            {copied ? 'Copied' : 'Copy link'}
          </button>
          {onSendInRabbit && (
            <button type="button" className={row} onClick={() => { onClose(); onSendInRabbit() }}>
              <MessageCircle className="size-4 text-(--accent)" aria-hidden /> Send in Rabbit
            </button>
          )}
          {target.kind !== 'invite' && (
            <button type="button" className={row} disabled={!link || busy === 'image'} onClick={() => void image()}>
              <ImageIcon className="size-4 text-(--accent)" aria-hidden /> {busy === 'image' ? 'Making the image…' : 'Share an image'}
            </button>
          )}
        </div>
        <p className="px-1 text-[0.7059rem] leading-snug text-(--text-muted)">
          Anyone with the link can see it, no app needed. Turn links off anytime in Me › Settings › Shared links.
        </p>
        <canvas ref={canvas} className="hidden" aria-hidden />
      </div>
    </Sheet>
  )
}

/** The footer/card button: opens the share sheet. */
export function ShareButton({ target, hrOption, onSendInRabbit, label = 'Share', iconOnly, className }: {
  target: ShareTarget; hrOption?: boolean; onSendInRabbit?: () => void; label?: string; iconOnly?: boolean; className?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="default" size={iconOnly ? 'icon' : undefined}
        className={cn(iconOnly ? 'size-11 shrink-0' : 'h-11 gap-1.5 text-[0.8235rem]', className)}
        aria-label={iconOnly ? `${label}: text, copy a link or send in Rabbit` : undefined} onClick={() => setOpen(true)}>
        <Share2 className="size-4" aria-hidden />{!iconOnly && ` ${label}`}
      </Button>
      {open && <ShareSheet target={target} hrOption={hrOption} onSendInRabbit={onSendInRabbit} onClose={() => setOpen(false)} />}
    </>
  )
}
