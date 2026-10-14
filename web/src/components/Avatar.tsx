import { useState } from 'react'

/** The uploaded profile photo (``photo`` URL), else the Google profile photo, else an
 * initial (like Dolly's header avatar). */
export function Avatar({ name, picture, photo, size = 28 }: { name: string; picture: string; photo?: string | null; size?: number }) {
  const [broken, setBroken] = useState<string[]>([])
  const initial = (name || '?').trim().charAt(0).toUpperCase()
  const src = [photo, picture].find((u): u is string => !!u && !broken.includes(u))
  if (src) {
    return (
      <img key={src} src={src} alt={name} width={size} height={size} referrerPolicy="no-referrer"
        onError={() => setBroken((b) => [...b, src])} className="rounded-full border border-(--border) object-cover"
        style={{ width: size, height: size }} />
    )
  }
  return (
    <span aria-label={name} style={{ width: size, height: size }}
      className="flex items-center justify-center rounded-full bg-(--accent-subtle) text-xs font-medium text-(--accent)">
      {initial}
    </span>
  )
}
