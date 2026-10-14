// Profile photo: resized in the browser to a 256x256 JPEG (center crop), uploaded as raw
// bytes, served back from /app/api/profile/photo (owner) or the coach route (linked coaches).
import { AuthError, sendJSON } from '@/lib/api'

const SIZE = 256
const MAX_BYTES = 300 * 1024

/** The photo URL for a version, or null when there's no uploaded photo. */
export function photoUrl(version: number | null | undefined, athleteId?: string): string | null {
  if (!version) return null
  const base = athleteId ? `/app/api/coach/athletes/${encodeURIComponent(athleteId)}/photo` : '/app/api/profile/photo'
  return `${base}?v=${version}`
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => { URL.revokeObjectURL(url); resolve(img) }
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file isn't a photo we can read.")) }
    img.src = url
  })
}

function toBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
}

/** Center-crop to a square and scale to 256x256 JPEG, stepping quality down to fit 300 KB. */
export async function resizePhoto(file: File): Promise<Blob> {
  const img = await loadImage(file)
  const side = Math.min(img.naturalWidth, img.naturalHeight)
  if (!side) throw new Error("That file isn't a photo we can read.")
  const canvas = document.createElement('canvas')
  canvas.width = SIZE; canvas.height = SIZE
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error("This browser can't resize photos.")
  ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, SIZE, SIZE)
  for (const q of [0.88, 0.75, 0.6]) {
    const blob = await toBlob(canvas, q)
    if (blob && blob.size <= MAX_BYTES) return blob
  }
  throw new Error('That photo is too large even after resizing.')
}

export async function uploadPhoto(blob: Blob): Promise<number> {
  const r = await fetch('/app/api/profile/photo', {
    method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'image/jpeg' }, body: blob,
  })
  if (r.status === 401) throw new AuthError('not signed in')
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.error ?? `HTTP ${r.status}`)
  return data.photo as number
}

export const deletePhoto = () => sendJSON<{ ok: boolean }>('DELETE', '/api/profile/photo')
