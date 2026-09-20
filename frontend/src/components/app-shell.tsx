import type { ReactNode } from 'react'
import { ChevronDown, Plug, Plus, Search, Unplug } from 'lucide-react'

import { Diamond } from '@/components/diamond'
import { Button } from '@/components/ui/button'
import { useConfig } from '@/features/config/api'
import { useConnection, useDisconnect } from '@/features/connection/api'
import { RecentJobs } from '@/features/jobs/recent-jobs'

interface AppShellProps {
  title: ReactNode
  onNewTransformation: () => void
  onConnect: () => void
  /** The results panel, docked to the right of the conversation. */
  panel?: ReactNode
  children: ReactNode
}

/**
 * The desktop-client frame: one window on a near-black page, a sidebar, a title bar, and the
 * work in the middle. On a narrow screen the frame drops away and the sidebar hides, so the
 * same components serve a phone.
 */
export function AppShell({ title, onNewTransformation, onConnect, panel, children }: AppShellProps) {
  return (
    <div className="relative flex min-h-svh items-start justify-center bg-background p-0 lg:items-center lg:p-7">
      <div
        aria-hidden
        className="glow pointer-events-none absolute top-[-18%] left-1/2 hidden h-[520px] w-[900px] -translate-x-1/2 rounded-[50%] lg:block"
      />

      <div className="relative flex min-h-svh w-full flex-col overflow-hidden bg-surface lg:h-[min(868px,calc(100svh-56px))] lg:min-h-[560px] lg:max-w-[1380px] lg:flex-row lg:rounded-[14px] lg:shadow-[0_0_0_1px_var(--surface-edge),0_40px_90px_-20px_rgba(0,0,0,0.9)]">
        <Sidebar onNewTransformation={onNewTransformation} onConnect={onConnect} />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-rule px-5">
            <div className="flex min-w-0 flex-1 items-center gap-2.5">{title}</div>
            <ModelPill />
          </header>

          <div className="flex min-h-0 flex-1">
            <div className="flex min-w-0 flex-1 flex-col">{children}</div>
            {panel}
          </div>
        </div>
      </div>
    </div>
  )
}

function Sidebar({
  onNewTransformation,
  onConnect,
}: {
  onNewTransformation: () => void
  onConnect: () => void
}) {
  const { data: connection } = useConnection()
  const { disconnect, pending } = useDisconnect()

  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-sidebar-border bg-sidebar lg:w-[262px] lg:border-r lg:border-b-0">
      {/* The window's own buttons. Decoration on the web, and the thing that makes it read as
          an application rather than a page. */}
      <div className="hidden items-center gap-2 px-4 pt-[15px] pb-1 lg:flex">
        {[0, 1, 2].map((dot) => (
          <span key={dot} className="size-[11px] rounded-full bg-[#2c3735]" />
        ))}
      </div>

      <div className="flex items-center gap-2.5 px-3.5 py-3 lg:pt-3 lg:pb-2.5">
        <span className="flex size-[26px] shrink-0 items-center justify-center rounded-lg bg-linear-150 from-primary/70 to-primary/25">
          <span className="size-[9px] rotate-45 rounded-[2px] bg-[#05100e]" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="text-[14.5px] leading-tight font-semibold tracking-tight">nl2regex</span>
          <span className="truncate text-[11px] text-dim">
            {connection ? connection.bucket : 'No bucket connected'}
          </span>
        </div>
        <ChevronDown className="ml-auto size-3.5 shrink-0 text-dim" />
      </div>

      <div className="flex flex-col gap-2 px-3 pb-2.5">
        <button
          type="button"
          onClick={onNewTransformation}
          className="tint flex items-center gap-2 rounded-[10px] px-3 py-2.5 text-left text-[13px] font-medium text-primary transition-colors hover:bg-primary/15"
        >
          <Plus className="size-3.5" />
          New transformation
        </button>
        <button
          type="button"
          onClick={onConnect}
          className="flex items-center gap-2 rounded-[10px] bg-[#0d1211] px-3 py-2 text-left text-[13px] text-dim inset-ring inset-ring-[#161e1c] transition-colors hover:text-foreground"
        >
          {connection ? <Search className="size-3.5" /> : <Plug className="size-3.5" />}
          {connection ? 'Browse the bucket' : 'Connect an S3 bucket'}
        </button>
      </div>

      <nav
        aria-label="Recent transformations"
        className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pt-1 pb-2.5"
      >
        <h2 className="eyebrow px-2 pt-2.5 pb-1.5 text-dim">Recent</h2>
        <RecentJobs />
      </nav>

      {connection && (
        <div className="hidden items-center gap-2.5 border-t border-sidebar-border px-3.5 py-3 lg:flex">
          <span className="flex size-[26px] shrink-0 items-center justify-center rounded-full bg-[#0e1312] text-[10px] font-medium text-dim inset-ring inset-ring-[#1b2422]">
            S3
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] leading-tight" title={connection.bucket}>
              {connection.bucket}
            </p>
            <p className="text-[11px] text-dim">{connection.region} · read-only</p>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={disconnect}
            disabled={pending}
            aria-label="Disconnect"
            title="Disconnect and forget the keys"
          >
            <Unplug className="size-3.5" />
          </Button>
        </div>
      )}
    </aside>
  )
}

/** Which model writes the patterns, in the top right, as the design has it. */
function ModelPill() {
  const { data: config } = useConfig()
  const available = config?.describe_available ?? false

  return (
    <span
      className="flex shrink-0 items-center gap-2 rounded-full bg-[#0d1211] px-3 py-1.5 font-mono text-[11px] text-[#aab6b2] inset-ring inset-ring-[#1b2422]"
      title={
        available
          ? 'The model that turns plain English into a pattern, and finds personal data'
          : 'No API key on this server, so patterns must be typed'
      }
    >
      <Diamond className={available ? 'text-primary' : 'text-dim'} filled={available} />
      {config?.model ?? 'regex only'}
    </span>
  )
}
