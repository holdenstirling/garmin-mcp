// The monthly recap share image, drawn on a <canvas> (no dependencies): 1080x1350 PNG in the
// brand colors with the rabbit mark. Only the recap's totals go on it: no names, places,
// heart rate or other health data.
import { PATH, VIEWBOX } from '@/components/RabbitLogo'
import { fmtDuration } from '@/lib/format'
import { sportName, type MonthRecap } from '@/lib/reward'

export const CARD_W = 1080
export const CARD_H = 1350
const BG = '#1a3a2a'      // --brand (light theme)
const INK = '#f5f0e8'     // --bg (light theme): cream
const SOFT = '#a8d5b5'    // --brand in dark theme: soft green
const MUTED = 'rgba(245, 240, 232, 0.72)'
const SERIF = "'DM Serif Display', Georgia, serif"
const MONO = "'DM Mono', ui-monospace, monospace"
const SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

const WORD: Record<string, string> = { run: 'run', bike: 'ride', swim: 'swim', hike: 'hike', strength: 'session', ski: 'ski', paddle: 'paddle', climb: 'climb', brick: 'brick' }

export function hoursLabel(h: number): string {
  return h >= 10 ? `${Math.round(h)}` : `${Math.round(h * 10) / 10}`
}

/** The six tiles, also used for the image's alt text. */
export function tiles(r: MonthRecap): [string, string][] {
  return [
    ['Hours', hoursLabel(r.hours)],
    ['Sessions', String(r.sessions)],
    ['Longest', r.longest ? `${fmtDuration(r.longest.minutes)} ${WORD[r.longest.sport] ?? 'session'}` : '–'],
    ['Best streak', r.best_streak ? `${r.best_streak} day${r.best_streak === 1 ? '' : 's'}` : '–'],
    ['Top sport', r.top_sport ? sportName(r.top_sport.sport) : '–'],
    ['Top club', r.top_club ?? '–'],
  ]
}

export function fit(ctx: CanvasRenderingContext2D, text: string, max: number, size: number, family: string, weight = ''): string {
  let s = size
  ctx.font = `${weight} ${s}px ${family}`.trim()
  while (ctx.measureText(text).width > max && s > size * 0.55) {
    s -= 2
    ctx.font = `${weight} ${s}px ${family}`.trim()
  }
  if (ctx.measureText(text).width <= max) return text
  let t = text
  while (t.length > 1 && ctx.measureText(`${t}…`).width > max) t = t.slice(0, -1)
  return `${t.trimEnd()}…`
}

export function rabbit(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, color: string) {
  const [vx, vy, vw] = VIEWBOX.split(' ').map(Number)
  ctx.save()
  ctx.translate(x, y)
  ctx.scale(size / vw, size / vw)
  ctx.translate(-vx, -vy)
  ctx.fillStyle = color
  ctx.fill(new Path2D(PATH))
  ctx.restore()
}

export function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

/** Draws the card; waits for the brand fonts so the first render isn't in a fallback face. */
export async function drawMonthCard(canvas: HTMLCanvasElement, r: MonthRecap): Promise<void> {
  try {
    await Promise.all([document.fonts.load(`120px ${SERIF}`), document.fonts.load(`40px ${MONO}`)])
  } catch { /* fallback fonts still read fine */ }
  canvas.width = CARD_W
  canvas.height = CARD_H
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const pad = 88
  ctx.fillStyle = BG
  ctx.fillRect(0, 0, CARD_W, CARD_H)
  // A big, quiet rabbit in the corner (decoration), and the small mark + name on top.
  ctx.globalAlpha = 0.07
  rabbit(ctx, CARD_W - 560, CARD_H - 640, 620, INK)
  ctx.globalAlpha = 1
  rabbit(ctx, pad, pad - 6, 64, INK)
  ctx.fillStyle = INK
  ctx.textBaseline = 'alphabetic'
  ctx.font = `44px ${SERIF}`
  ctx.fillText('rabbt', pad + 80, pad + 44)

  ctx.fillStyle = SOFT
  ctx.font = `500 30px ${MONO}`
  ctx.fillText(`${r.label.toUpperCase()} ${r.year}${r.partial ? ' · SO FAR' : ''}`, pad, 290)
  ctx.fillStyle = INK
  const title = fit(ctx, `Your ${r.label}`, CARD_W - pad * 2, 132, SERIF)
  ctx.fillText(title, pad, 420)

  // Tiles: 2 columns x 3 rows.
  const gap = 28, tw = (CARD_W - pad * 2 - gap) / 2, th = 150, top = 486
  tiles(r).forEach(([label, value], i) => {
    const x = pad + (i % 2) * (tw + gap), y = top + Math.floor(i / 2) * (th + gap)
    ctx.fillStyle = 'rgba(245, 240, 232, 0.08)'
    roundRect(ctx, x, y, tw, th, 28)
    ctx.fill()
    ctx.fillStyle = MUTED
    ctx.font = `500 24px ${MONO}`
    ctx.fillText(label.toUpperCase(), x + 32, y + 50)
    ctx.fillStyle = INK
    const big = i < 2 ? 72 : 52
    ctx.fillText(fit(ctx, value, tw - 64, big, i < 2 ? MONO : SANS, i < 2 ? '500' : '600'), x + 32, y + (i < 2 ? 124 : 116))
  })

  // Hours per week.
  const chartTop = top + 3 * (th + gap) + 30, chartH = 150
  ctx.fillStyle = MUTED
  ctx.font = `500 24px ${MONO}`
  ctx.fillText('HOURS PER WEEK', pad, chartTop)
  const weeks = r.weeks.length ? r.weeks : [{ start: '', hours: 0 }]
  const max = Math.max(1, ...weeks.map((w) => w.hours))
  const bw = (CARD_W - pad * 2 - (weeks.length - 1) * 20) / weeks.length
  weeks.forEach((w, i) => {
    const h = Math.max(6, (w.hours / max) * chartH)
    const x = pad + i * (bw + 20), y = chartTop + 50 + chartH - h
    ctx.fillStyle = w.hours ? SOFT : 'rgba(168, 213, 181, 0.25)'
    roundRect(ctx, x, y, bw, h, 12)
    ctx.fill()
    ctx.fillStyle = MUTED
    ctx.font = `500 22px ${MONO}`
    const lbl = w.hours ? hoursLabel(w.hours) : ''
    ctx.fillText(lbl, x + (bw - ctx.measureText(lbl).width) / 2, y - 12)
  })

  ctx.fillStyle = MUTED
  ctx.font = `26px ${SANS}`
  ctx.fillText('Trained with rabbt', pad, CARD_H - 64)
}

export function cardBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Couldn't make the image."))), 'image/png'))
}

/** navigator.share with the PNG where the browser supports files, else a download. */
export function shareCard(canvas: HTMLCanvasElement, r: MonthRecap): Promise<'shared' | 'downloaded' | 'cancelled'> {
  return shareImage(canvas, `rabbt-${r.label.toLowerCase()}-${r.year}.png`, `My ${r.label} on rabbt`)
}

/** Any card canvas: the system share sheet with the PNG where supported, else a download. */
export async function shareImage(canvas: HTMLCanvasElement, name: string, title: string): Promise<'shared' | 'downloaded' | 'cancelled'> {
  const blob = await cardBlob(canvas)
  const file = new File([blob], name, { type: 'image/png' })
  const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean }
  if (nav.share && nav.canShare?.({ files: [file] })) {
    try {
      await nav.share({ files: [file], title })
      return 'shared'
    } catch (e) {
      if ((e as DOMException)?.name === 'AbortError') return 'cancelled'
      // fall through to a download
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 2000)
  return 'downloaded'
}
