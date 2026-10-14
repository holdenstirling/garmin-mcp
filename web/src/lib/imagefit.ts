// Photos for "Add a plan": iPhone HEIC photos and big camera shots become a JPEG the server
// accepts (photos max 5 MB), in the browser, before upload. Uses the browser's own decoder
// (createImageBitmap), so HEIC works where the browser can show it (Safari); elsewhere the
// file goes up as it is and the server explains what to do.
const HEIC = /\.(heic|heif)$/i
const MAX_BYTES = 4.5 * 1024 * 1024
const MAX_SIDE = 2400

const isHeic = (f: File) => /image\/hei[cf]/i.test(f.type) || HEIC.test(f.name)

async function toJpeg(f: File): Promise<Blob | null> {
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return null
  try {
    const bmp = await createImageBitmap(f)
    const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bmp.width * scale)
    canvas.height = Math.round(bmp.height * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height)
    bmp.close?.()
    return await new Promise<Blob | null>((res) => canvas.toBlob((b) => res(b), 'image/jpeg', 0.85))
  } catch {
    return null
  }
}

/** Files ready to upload, with their names (a converted photo gets a .jpg name). */
export async function fitForUpload(files: File[]): Promise<{ files: Blob[]; names: string[] }> {
  const out: Blob[] = []
  const names: string[] = []
  for (const [i, f] of files.entries()) {
    const name = f.name || `image-${i + 1}.png`
    const photo = f.type.startsWith('image/') || isHeic(f)
    if (photo && (isHeic(f) || f.size > MAX_BYTES)) {
      const jpg = await toJpeg(f)
      if (jpg && jpg.size <= MAX_BYTES) {
        out.push(jpg)
        names.push(name.replace(/\.[a-z0-9]+$/i, '') + '.jpg')
        continue
      }
    }
    out.push(f)
    names.push(name)
  }
  return { files: out, names }
}
