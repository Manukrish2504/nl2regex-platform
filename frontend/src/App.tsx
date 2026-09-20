import { useState } from 'react'

import { AppShell } from '@/components/app-shell'
import { Composer } from '@/features/composer/composer'
import { JobPage } from '@/features/jobs/job-page'
import { matchJobPath, navigate, usePath } from '@/lib/router'

export default function App() {
  const jobId = matchJobPath(usePath())
  // A new key remounts the composer, which is the simplest way to clear everything in it.
  const [composerKey, setComposerKey] = useState(0)

  function startNew() {
    setComposerKey((key) => key + 1)
    navigate('/')
  }

  return (
    <AppShell onNewTransformation={startNew}>
      {jobId ? (
        <div className="w-full pt-10">
          <JobPage key={jobId} jobId={jobId} />
        </div>
      ) : (
        <div className="w-full max-w-3xl pt-[8vh] md:pt-[12vh]">
          <Composer key={composerKey} />
        </div>
      )}
    </AppShell>
  )
}
