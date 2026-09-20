import type { ReactNode } from 'react'
import { Plus, Regex } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ConnectionPanel } from '@/features/connection/connection-panel'
import { ConnectionPill } from '@/features/connection/connection-pill'

interface AppShellProps {
  onNewTransformation: () => void
  children: ReactNode
}

export function AppShell({ onNewTransformation, children }: AppShellProps) {
  return (
    <div className="relative flex min-h-svh">
      <div aria-hidden className="glow pointer-events-none fixed inset-0" />

      {/* Wide screens get the sidebar. Narrow ones get a one-line header instead. */}
      <aside className="sticky top-0 z-10 hidden h-svh w-64 shrink-0 flex-col gap-4 border-r border-sidebar-border bg-sidebar/70 p-3 backdrop-blur-md md:flex">
        <Brand className="px-2 pt-1" />

        <Button variant="outline" className="justify-start" onClick={onNewTransformation}>
          <Plus />
          New transformation
        </Button>

        <nav aria-label="Recent transformations" className="flex min-h-0 flex-1 flex-col gap-1">
          <h2 className="px-2 text-xs font-medium text-muted-foreground">Recent</h2>
          <p className="px-2 text-sm text-muted-foreground/70">Your transformations will appear here.</p>
        </nav>

        <div className="border-t border-sidebar-border pt-3">
          <ConnectionPanel />
        </div>
      </aside>

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-3 px-4 md:hidden">
          <Brand />
          <ConnectionPill />
        </header>

        <main className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 pt-[10vh] pb-16 md:pt-[16vh]">
          {children}
        </main>
      </div>
    </div>
  )
}

function Brand({ className }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className ?? ''}`}>
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary/15 text-primary ring-1 ring-primary/30">
        <Regex className="size-4.5" />
      </span>
      <span className="font-medium tracking-tight">nl2regex</span>
    </div>
  )
}
