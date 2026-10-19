// A policy body from the server (legal.body_html: static, trusted HTML written in legal.py,
// never user content), styled to match the app.
export function LegalDocBody({ html }: { html: string }) {
  return (
    <div className="legal-doc text-body-lg leading-relaxed text-(--text)
      [&_h2]:mt-5 [&_h2]:mb-1.5 [&_h2]:text-lead [&_h2]:font-semibold [&_h2]:text-(--brand)
      [&_p]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-1.5 [&_a]:text-(--accent) [&_a]:underline
      [&_.box]:my-3 [&_.box]:rounded-xl [&_.box]:border [&_.box]:border-(--border) [&_.box]:bg-(--bg-inset) [&_.box]:p-3
      [&_code]:font-mono [&_code]:text-body"
      dangerouslySetInnerHTML={{ __html: html }} />
  )
}
