// The celebration share image (race finish, block complete, personal record): 1080x1350 PNG in
// the brand colors, drawn on a <canvas> like the month card. Only what the athlete sees on the
// celebration goes on it (title, race or block name, 2-3 stats): no places, heart rate or health data.
import { CARD_H, CARD_W, fit, rabbit, roundRect } from './monthCard'

const BG = '#1a3a2a', INK = '#f5f0e8', SOFT = '#a8d5b5', MUTED = 'rgba(245, 240, 232, 0.72)'
const SERIF = "'DM Serif Display', Georgia, serif"
const MONO = "'DM Mono', ui-monospace, monospace"
const SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

export type CardInput = { eyebrow: string; title: string; subtitle: string; stats: { label: string; value: string }[] }

export async function drawCelebrationCard(canvas: HTMLCanvasElement, c: CardInput): Promise<void> {
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
  // Confetti-like carrot dots in a fixed pattern (same image every time).
  for (let i = 0; i < 26; i++) {
    const x = (i * 397) % CARD_W, y = 120 + ((i * 211) % 520)
    ctx.globalAlpha = 0.12 + (i % 4) * 0.05
    ctx.fillStyle = i % 3 ? SOFT : '#e8955a'
    ctx.save(); ctx.translate(x, y); ctx.rotate((i * 37 * Math.PI) / 180)
    roundRect(ctx, -6, -18, 12, 36, 6); ctx.fill(); ctx.restore()
  }
  ctx.globalAlpha = 0.07
  rabbit(ctx, CARD_W - 560, CARD_H - 640, 620, INK)
  ctx.globalAlpha = 1
  rabbit(ctx, pad, pad - 6, 64, INK)
  ctx.fillStyle = INK
  ctx.textBaseline = 'alphabetic'
  ctx.font = `44px ${SERIF}`
  ctx.fillText('Rabbit', pad + 80, pad + 44)

  ctx.fillStyle = SOFT
  ctx.font = `500 30px ${MONO}`
  ctx.fillText(fit(ctx, c.eyebrow.toUpperCase(), CARD_W - pad * 2, 30, MONO, '500'), pad, 330)
  ctx.fillStyle = INK
  ctx.fillText(fit(ctx, c.title, CARD_W - pad * 2, 132, SERIF), pad, 470)
  ctx.fillStyle = MUTED
  ctx.fillText(fit(ctx, c.subtitle, CARD_W - pad * 2, 48, SANS, '600'), pad, 550)

  const stats = c.stats.slice(0, 3)
  const gap = 28, th = 170, top = 640
  stats.forEach((s, i) => {
    const y = top + i * (th + gap)
    ctx.fillStyle = 'rgba(245, 240, 232, 0.08)'
    roundRect(ctx, pad, y, CARD_W - pad * 2, th, 28)
    ctx.fill()
    ctx.fillStyle = MUTED
    ctx.font = `500 26px ${MONO}`
    ctx.fillText(s.label.toUpperCase(), pad + 36, y + 56)
    ctx.fillStyle = INK
    ctx.fillText(fit(ctx, s.value, CARD_W - pad * 2 - 72, 76, MONO, '500'), pad + 36, y + 136)
  })

  ctx.fillStyle = MUTED
  ctx.font = `26px ${SANS}`
  ctx.fillText('Trained with Rabbit', pad, CARD_H - 64)
}
