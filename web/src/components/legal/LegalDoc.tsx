// A policy body from the server (legal.body_html: static, trusted HTML written in legal.py,
// never user content), styled to match the app.
export function LegalDocBody({ html }: { html: string }) {
  return (
    <div className="legal-doc max-w-[65ch] text-body-lg leading-relaxed text-(--text)
      [&_h2]:mt-7 [&_h2]:mb-2 [&_h2]:text-title-sm [&_h2]:font-semibold [&_h2]:leading-snug [&_h2]:text-(--text)
      [&_h3]:mt-5 [&_h3]:mb-1.5 [&_h3]:text-lead [&_h3]:font-semibold
      [&_p]:my-3 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-2 [&_a]:text-(--accent) [&_a]:underline
      [&_.box]:my-4 [&_.box]:rounded-xl [&_.box]:border [&_.box]:border-(--border) [&_.box]:bg-(--bg-inset) [&_.box]:p-4
      [&_code]:font-mono [&_code]:text-body"
      dangerouslySetInnerHTML={{ __html: html }} />
  )
}
