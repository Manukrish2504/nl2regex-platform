import type { ReactNode } from 'react'
import { Regex } from 'lucide-react'

import { ConnectionPill } from '@/features/connection/connection-pill'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-svh">
      <div aria-hidden className="glow pointer-events-none fixed inset-0" />

      <header className="relative z-10 flex h-16 items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary/15 text-primary ring-1 ring-primary/30">
            <Regex className="size-4.5" />
          </span>
          <span className="font-medium tracking-tight">nl2regex</span>
        </div>
        <ConnectionPill />
      </header>

      <main className="relative z-10 mx-auto flex w-full max-w-3xl flex-col items-center px-4 pt-[14vh] pb-16">
        {children}
      </main>
    </div>
  )
}
