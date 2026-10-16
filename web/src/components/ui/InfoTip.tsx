// Small (i) button that explains a term in plain language. 44px hit area, closes on outside tap or Escape.
import { useEffect, useId, useRef, useState } from 'react'
import { Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { GLOSSARY, type Term } from '@/lib/glossary'

export function InfoTip({ term, text, label, className, align = 'center' }: {
  /** glossary term, or pass ``text`` (and ``label``) directly */
  term?: Term; text?: string; label?: string; className?: string
  align?: 'start' | 'center' | 'end'
}) {
  const g = term ? GLOSSARY[term] : null
  const body = text ?? g?.text ?? ''
  const name = label ?? g?.title ?? 'this'
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey, true)
    return () => { document.removeEventListener('pointerdown', onDown); document.removeEventListener('keydown', onKey, true) }
  }, [open])
  return (
    <span ref={ref} className={cn('relative inline-flex align-middle', className)}>
      <button type="button" aria-expanded={open} aria-controls={id} aria-label={`What is ${name}?`}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
        className="hit-44 inline-flex size-4 items-center justify-center rounded-full text-(--text-muted) hover:text-(--text) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-(--accent)">
        <Info className="size-3.5" aria-hidden />
      </button>
      {open && (
        <span id={id} role="tooltip"
          className={cn('absolute top-full z-(--z-popover) mt-1.5 w-56 rounded-lg border border-(--border-strong) bg-(--bg-surface) px-3 py-2 text-left text-[0.7059rem] font-normal normal-case leading-snug tracking-normal text-(--text) shadow-lg',
            align === 'start' ? 'left-0' : align === 'end' ? 'right-0' : 'left-1/2 -translate-x-1/2')}>
          {g && !text && <span className="mb-0.5 block font-semibold">{g.title}</span>}
          {body}
        </span>
      )}
    </span>
  )
}
