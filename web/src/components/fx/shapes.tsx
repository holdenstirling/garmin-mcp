// Small original shapes for the motion kit: carrot, sparkle, hop print, dust puff.
// Plain SVG, decorative only.

export function Carrot({ size = 14, className, style }: { size?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={className} style={style}>
      <path d="M12.5 6.5c-1.2-2-0.6-4 0.4-5.2 0.6 1.3 1.6 2.4 2.9 2.9-0.6 1.1-1.8 2.1-3.3 2.3z" fill="var(--fx-leaf)" />
      <path d="M13 6.2c1.6-1.5 3.8-1.8 5.5-0.9-0.9 1.4-2.7 2.3-4.6 2.2z" fill="var(--fx-leaf)" />
      <path d="M8.2 8.6c1.9-1.9 4.9-2 6.9-0.1 2 1.9 2 5 0.2 6.9L5 22.4c-0.8 0.6-1.9-0.4-1.3-1.2z" fill="var(--fx-carrot)" />
      <path d="M8 12.5l2 1M6.4 15.7l1.8 0.9M10.4 10.3l1.7 0.9" stroke="rgba(0,0,0,0.18)" strokeWidth="1" strokeLinecap="round" />
    </svg>
  )
}

export function Sparkle({ size = 10, className, style }: { size?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={className} style={style}>
      <path d="M12 0c0.9 6.3 5.7 11.1 12 12-6.3 0.9-11.1 5.7-12 12-0.9-6.3-5.7-11.1-12-12C6.3 11.1 11.1 6.3 12 0z" fill="currentColor" />
    </svg>
  )
}

/** A rabbit hop print: one long hind-foot oval with two small toe dots ahead of it. */
export function HopPrint({ size = 10, className, style }: { size?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true" className={className} style={style}>
      <ellipse cx="7" cy="10" rx="5.5" ry="2.6" fill="currentColor" />
      <circle cx="15" cy="7.2" r="1.7" fill="currentColor" />
      <circle cx="15.4" cy="12.6" r="1.7" fill="currentColor" />
    </svg>
  )
}

export function Puff({ size = 12, className, style }: { size?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true" className={className} style={style}>
      <circle cx="7" cy="11" r="5" fill="currentColor" />
      <circle cx="12.5" cy="8.5" r="5.5" fill="currentColor" />
      <circle cx="13.5" cy="13" r="4" fill="currentColor" />
    </svg>
  )
}
