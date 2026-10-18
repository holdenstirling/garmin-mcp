// A QR code drawn as SVG (lib/qr). Dark modules on white with a quiet zone, so it scans in
// dark mode too.
import { useMemo } from 'react'
import { qrMatrix } from '@/lib/qr'

export function QrCode({ text, size = 200, label }: { text: string; size?: number; label: string }) {
  const m = useMemo(() => qrMatrix(text), [text])
  if (!m) return null
  const n = m.length
  const q = 4
  const path: string[] = []
  m.forEach((row, r) => row.forEach((on, c) => { if (on) path.push(`M${c + q} ${r + q}h1v1h-1z`) }))
  return (
    <svg role="img" aria-label={label} width={size} height={size} viewBox={`0 0 ${n + 2 * q} ${n + 2 * q}`}
      shapeRendering="crispEdges" className="rounded-xl bg-white">
      <rect width="100%" height="100%" fill="#fff" />
      <path d={path.join('')} fill="#111" />
    </svg>
  )
}
