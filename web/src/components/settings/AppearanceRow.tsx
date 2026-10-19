// Me > Look and feel: System / Light / Dark (lib/theme) and "Take the tour" again.
import { Compass, Monitor, Moon, Sun } from 'lucide-react'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { THEME_LABEL, setTheme, useTheme, type Theme } from '@/lib/theme'
import { startTour } from '@/lib/tour'
import { haptic } from '@/lib/haptics'
import { cn } from '@/lib/utils'

const OPTIONS: { id: Theme; icon: typeof Sun }[] = [
  { id: 'system', icon: Monitor }, { id: 'light', icon: Sun }, { id: 'dark', icon: Moon },
]

export function AppearanceGroup() {
  const theme = useTheme()
  return (
    <Group label="Look and feel">
      <div className="flex flex-col gap-2.5 px-4 py-3">
        <span id="appearance-label" className="text-[0.8235rem] text-(--text)">Appearance</span>
        <div role="radiogroup" aria-labelledby="appearance-label" className="grid grid-cols-3 gap-1 rounded-xl bg-(--bg-inset) p-1">
          {OPTIONS.map(({ id, icon: I }) => (
            <button key={id} type="button" role="radio" aria-checked={theme === id}
              onClick={() => { haptic(); setTheme(id) }}
              className={cn('flex min-h-11 items-center justify-center gap-1.5 rounded-lg text-[0.7647rem] font-medium transition-colors',
                theme === id ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-secondary)')}>
              <I className="size-4" aria-hidden />{THEME_LABEL[id]}
            </button>
          ))}
        </div>
      </div>
      <Row icon={<Icon><Compass /></Icon>} title="Take the tour" subtitle="A one-minute look around rabbt" onClick={startTour} />
    </Group>
  )
}
