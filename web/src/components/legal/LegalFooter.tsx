// "Privacy · Terms · Health data · Data & security" under public screens (sign-in, join). Plain links to the
// server-rendered pages (legal.py), which work signed out.
export function LegalFooter({ className }: { className?: string }) {
  const links = [['/app/privacy', 'Privacy'], ['/app/terms', 'Terms'], ['/app/health-data', 'Health data'], ['/app/security', 'Data & security']] as const
  return (
    <nav aria-label="Policies" className={className ?? 'flex flex-wrap items-center justify-center gap-x-1 text-small text-(--text-muted)'}>
      {links.map(([href, label], i) => (
        <span key={href} className="flex items-center gap-1">
          {i > 0 && <span aria-hidden>·</span>}
          <a href={href} className="hit-44 underline">{label}</a>
        </span>
      ))}
    </nav>
  )
}
