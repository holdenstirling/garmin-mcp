// "Turn your plan into full workouts": reads the race's plan file (lib/planconvert), then the
// usual import review (PlanReview: what changes, week by week) before anything is replaced.
import { useCallback, useEffect, useState } from 'react'
import { Screen } from '@/components/plan/ui'
import { RabbitLoader } from '@/components/RabbitLoader'
import { ErrorState } from '@/components/ui/ErrorState'
import { Button } from '@/components/ui/button'
import { PlanReview } from '@/components/plan/PlanReview'
import { importApi, type Preview } from '@/lib/planimport'
import { importFromGoal } from '@/lib/planconvert'

const READING = ['Reading your plan file…', 'Finding every workout…', 'Working out zones and paces…', 'Lining up the weeks…']
const api = importApi('/api')

export function ConvertPlanScreen({ onClose, onApplied, onImportOther }: {
  onClose: () => void
  onApplied: () => void
  /** the file couldn't be read: open the regular import to drop a file */
  onImportOther: () => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(() => {
    setError(null)
    importFromGoal().then((r) => setPreview(r.preview), (e: Error) => setError(e.message))
  }, [])
  useEffect(() => { run() }, [run])

  if (preview) {
    return <PlanReview api={api} initial={preview} who="athlete" athleteName="" onClose={onClose} onApplied={onApplied} />
  }
  return (
    <Screen title="Full workouts" subtitle="From your plan file" onClose={onClose}>
      {error ? (
        <div className="flex flex-col gap-3">
          <ErrorState message={error} onRetry={run} />
          <Button variant="default" className="h-11" onClick={onImportOther}>Import a different file</Button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <RabbitLoader size={64} cycle={READING} />
          <p className="max-w-xs text-[0.8235rem] leading-snug text-(--text-secondary)">
            rabbt turns each day of your plan into a full workout with zones, pace and cadence. You'll check it before anything changes.
          </p>
        </div>
      )}
    </Screen>
  )
}
