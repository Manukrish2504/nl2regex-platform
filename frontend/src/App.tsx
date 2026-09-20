import { useEffect, useState } from 'react'

import { AppShell } from '@/components/app-shell'
import { Diamond } from '@/components/diamond'
import { Composer } from '@/features/composer/composer'
import { KIND_LABELS, useJob } from '@/features/jobs/api'
import { JobPage } from '@/features/jobs/job-page'
import { ResultsPanel } from '@/features/jobs/results-panel'
import { StatusBadge } from '@/features/jobs/status'
import { matchJobPath, navigate, usePath } from '@/lib/router'
import { fileName } from '@/lib/utils'

export default function App() {
  const jobId = matchJobPath(usePath())
  // A new key remounts the composer, which is the simplest way to clear everything in it.
  const [composerKey, setComposerKey] = useState(0)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)

  function startNew() {
    setComposerKey((key) => key + 1)
    setPanelOpen(false)
    navigate('/')
  }

  return jobId ? (
    <JobScreen
      key={jobId}
      jobId={jobId}
      panelOpen={panelOpen}
      onPanelOpenChange={setPanelOpen}
      onNewTransformation={startNew}
      onConnect={() => {
        navigate('/')
        setDialogOpen(true)
      }}
    />
  ) : (
    <AppShell
      title={<span className="text-[14.5px]">Home</span>}
      onNewTransformation={startNew}
      onConnect={() => setDialogOpen(true)}
    >
      <Composer key={composerKey} dialogOpen={dialogOpen} onDialogOpenChange={setDialogOpen} />
    </AppShell>
  )
}

interface JobScreenProps {
  jobId: string
  panelOpen: boolean
  onPanelOpenChange: (open: boolean) => void
  onNewTransformation: () => void
  onConnect: () => void
}

/** A job fills the window: its conversation, and its rows in the panel beside them. */
function JobScreen({ jobId, panelOpen, onPanelOpenChange, ...shell }: JobScreenProps) {
  const { data: job } = useJob(jobId)
  const open = panelOpen && job?.status === 'SUCCESS' && Boolean(job.rows_total)

  // The page's own title, so a job is findable in a browser's history.
  useEffect(() => {
    document.title = job ? `${fileName(job.file_key)} · nl2regex` : 'nl2regex'
    return () => {
      document.title = 'nl2regex'
    }
  }, [job])

  return (
    <AppShell
      {...shell}
      title={
        job ? (
          <>
            <span className="truncate text-[14.5px]" title={job.file_key}>
              {fileName(job.file_key)}
            </span>
            <span className="hidden shrink-0 items-center gap-1.5 text-[13px] text-dim sm:flex">
              <Diamond className="text-dim" filled={false} />
              {KIND_LABELS[job.kind]}
            </span>
            <StatusBadge status={job.status} />
          </>
        ) : (
          <span className="text-[14.5px] text-dim">Loading…</span>
        )
      }
      panel={open && job ? <ResultsPanel job={job} onClose={() => onPanelOpenChange(false)} /> : undefined}
    >
      <JobPage jobId={jobId} panelOpen={panelOpen} onPanelOpenChange={onPanelOpenChange} />
    </AppShell>
  )
}
