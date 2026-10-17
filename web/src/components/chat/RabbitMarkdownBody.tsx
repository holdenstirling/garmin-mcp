// The heavy half of RabbitMarkdown (lazy-loaded by RabbitText.tsx). Safe by construction:
// no rehype-raw, so no raw HTML; links limited to http(s), mailto and in-app paths.
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

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


export default function RabbitMarkdownBody({ text }: { text: string }) {
  return <Markdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>{text}</Markdown>
}
