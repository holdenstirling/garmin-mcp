// How Rabbit's words look everywhere: chat replies (full markdown) and short Rabbit lines in cards
// (only **bold**). Safe by construction: react-markdown without rehype-raw renders no raw HTML,
// and the inline form builds React text nodes, never HTML. Links open in a new tab.
import { useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import '@/styles/rabbit-md.css'

const REMARK_PLUGINS = [remarkGfm]
const SAFE_URL = /^(https?:|mailto:|\/app\/)/i
type Kids = { children?: React.ReactNode }
const COMPONENTS = {
  a: ({ href, children }: Kids & { href?: string }) => SAFE_URL.test(href ?? '')
    ? <a href={href} target={href?.startsWith('/app/') ? undefined : '_blank'} rel="noopener noreferrer">{children}</a>
    : <span>{children}</span>,
  table: ({ children }: Kids) => <div className="md-table"><table>{children}</table></div>,
  img: () => null, // model output never embeds images
}

/** Fold replies longer than this (characters) behind "Show more" once they're finished. */
export const FOLD_AT = 1400

export function RabbitMarkdown({ text, foldable = false, className }: {
  text: string
  /** fold very long replies (only for finished messages, so streaming text never jumps) */
  foldable?: boolean
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const fold = foldable && !open && text.length > FOLD_AT
  return (
    <>
      <div className={cn('rabbit-md', fold && 'rabbit-md--folded', className)}>
        <Markdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>{text}</Markdown>
      </div>
      {foldable && text.length > FOLD_AT && (
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
          className="hit-44 mt-1 text-[0.7647rem] font-medium text-(--accent)">
          {open ? 'Show less' : 'Show more'}
        </button>
      )}
    </>
  )
}

/** One short Rabbit line with **bold** support and nothing else (no links, no HTML). */
export function RabbitInline({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/(\*\*[^*\n]+\*\*)/g)
  return (
    <span className={cn('rabbit-inline', className)}>
      {parts.map((p, i) => p.startsWith('**') && p.endsWith('**') && p.length > 4
        ? <strong key={i}>{p.slice(2, -2)}</strong>
        : p ? <span key={i}>{p}</span> : null)}
    </span>
  )
}
