import { useState } from 'react'

import { AppShell } from '@/components/app-shell'
import { Composer } from '@/features/composer/composer'

export default function App() {
  // A new key remounts the composer, which is the simplest way to clear everything in it.
  const [composerKey, setComposerKey] = useState(0)

  return (
    <AppShell onNewTransformation={() => setComposerKey((key) => key + 1)}>
      <Composer key={composerKey} />
    </AppShell>
  )
}
