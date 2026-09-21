import { useState, type ReactNode } from 'react'
import { ChevronUp, Menu, Monitor, Moon, Plug, Plus, Search, Sun, Unplug, X } from 'lucide-react'

import { useConnection, useDisconnect } from '@/features/connection/api'
import { RecentJobs } from '@/features/jobs/recent-jobs'
import { useTheme, type Theme } from '@/lib/theme'
import { cn } from '@/lib/utils'

interface AppShellProps {
  title: ReactNode
  onNewTransformation: () => void
  onConnect: () => void
  /** The results panel, docked to the right of the conversation. */
  panel?: ReactNode
  children: ReactNode
}

/**
 * The application fills the screen: a sidebar, a title bar, and the work in the middle. On a
 * narrow screen the sidebar becomes a drawer over the work, so the same components serve a phone.
 */
export function AppShell({
  title,
  onNewTransformation,
  onConnect,
  panel,
  children,
}: AppShellProps) {
  // On a phone the sidebar is a drawer over the work, as in a chat app. On a desktop it is
  // always there, and this state is never used.
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <div className="relative flex h-svh w-full overflow-hidden bg-surface">
      {/* The drawer's backdrop. Present only while it is open, and only on a phone. */}
      {drawerOpen && (
        <button
          type="button"
          aria-label="Close the menu"
          onClick={() => setDrawerOpen(false)}
          className="absolute inset-0 z-30 bg-black/60 backdrop-blur-[2px] lg:hidden"
        />
      )}

      {/* Anything tapped inside the drawer either navigates or acts, and then the drawer
            has done its job, so the whole of it closes on click. */}
      <div
        onClick={() => setDrawerOpen(false)}
        className={cn(
          'absolute inset-y-0 left-0 z-40 w-[82%] max-w-[300px] transition-transform duration-200 ease-out lg:static lg:z-0 lg:w-[262px] lg:translate-x-0',
          drawerOpen ? 'translate-x-0 shadow-2xl shadow-black/60' : '-translate-x-full',
        )}
      >
        <Sidebar
          onNewTransformation={onNewTransformation}
          onConnect={onConnect}
          onClose={() => setDrawerOpen(false)}
        />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[52px] shrink-0 items-center gap-2 border-b border-rule px-3 lg:gap-3 lg:px-5">
          <button
            type="button"
            aria-label="Open the menu"
            onClick={() => setDrawerOpen(true)}
            className="-ml-1 flex size-9 shrink-0 items-center justify-center rounded-[10px] text-dim transition-colors hover:text-foreground lg:hidden"
          >
            <Menu className="size-4.5" />
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2.5">{title}</div>
          <button
            type="button"
            aria-label="New transformation"
            onClick={onNewTransformation}
            className="-mr-1 flex size-9 shrink-0 items-center justify-center rounded-[10px] text-dim transition-colors hover:text-foreground lg:hidden"
          >
            <Plus className="size-4.5" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">{children}</div>
          {panel}
        </div>
      </div>
    </div>
  )
}

function Sidebar({
  onNewTransformation,
  onConnect,
  onClose,
}: {
  onNewTransformation: () => void
  onConnect: () => void
  onClose: () => void
}) {
  const { data: connection } = useConnection()

  return (
    <aside className="flex h-full w-full shrink-0 flex-col border-sidebar-border bg-sidebar lg:border-r">
      {/* A phone needs a way out of the drawer; a desktop sidebar is simply there. */}
      <div className="flex items-center px-4 pt-3 lg:hidden">
        <button
          type="button"
          aria-label="Close the menu"
          onClick={onClose}
          className="-ml-2 flex size-8 items-center justify-center rounded-[10px] text-dim"
        >
          <X className="size-4" />
        </button>
      </div>

      <Brand />

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
          className="flex items-center gap-2 rounded-[10px] bg-secondary px-3 py-2 text-left text-[13px] text-dim inset-ring inset-ring-border transition-colors hover:text-foreground"
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

      <WorkspaceMenu onConnect={onConnect} onClose={onClose} />
    </aside>
  )
}

/** The application's name, at the head of the sidebar. */
function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-3.5 pt-3 pb-3.5 lg:pt-4">
      <span className="flex size-[26px] shrink-0 items-center justify-center rounded-lg bg-linear-150 from-primary/70 to-primary/25">
        <span className="size-[9px] rotate-45 rounded-[2px] bg-primary-foreground" />
      </span>
      <span className="text-[14.5px] leading-tight font-semibold tracking-tight">nl2regex</span>
    </div>
  )
}

/**
 * The connection, at the foot of the sidebar, where an application puts the account: who you are
 * signed in as, and the two things you can do about it.
 */
function WorkspaceMenu({ onConnect, onClose }: { onConnect: () => void; onClose: () => void }) {
  const { data: connection } = useConnection()
  const { disconnect, pending } = useDisconnect()
  const [theme, setTheme] = useTheme()
  const [open, setOpen] = useState(false)

  const appearance: { value: Theme; label: string; icon: typeof Sun }[] = [
    { value: 'system', label: 'System', icon: Monitor },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'light', label: 'Light', icon: Sun },
  ]

  return (
    // The drawer closes on any click inside it, which would shut this menu as it opened, so
    // clicks stop here and the two items that act close the drawer themselves.
    <div
      onClick={(event) => event.stopPropagation()}
      className="relative shrink-0 border-t border-sidebar-border px-1.5 py-1.5"
    >
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 rounded-[10px] px-2 py-2 text-left transition-colors hover:bg-sidebar-accent"
      >
        <span className="flex size-[26px] shrink-0 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold text-dim uppercase inset-ring inset-ring-border">
          {connection ? connection.bucket.slice(0, 1) : <Plug className="size-3" />}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-[13px] leading-tight" title={connection?.bucket}>
            {connection ? connection.bucket : 'No bucket connected'}
          </span>
          {/* Disconnected, the line above says it and the button above that offers it. */}
          {connection && (
            <span className="block truncate text-[11px] text-dim">
              {connection.region} · read-only
            </span>
          )}
        </span>
        <ChevronUp
          className={cn(
            'ml-auto size-3.5 shrink-0 text-dim transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <>
          {/* A click anywhere else closes the menu. */}
          <button
            type="button"
            aria-label="Close the menu"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-40 cursor-default"
          />
          <div
            role="menu"
            className="absolute right-1.5 bottom-full left-1.5 z-50 mb-1 flex flex-col gap-1 rounded-[12px] bg-popover p-1.5 shadow-xl shadow-black/40 inset-ring inset-ring-input"
          >
            <p className="eyebrow px-2 pt-1.5 pb-1 text-dim">Appearance</p>
            <div className="flex gap-1">
              {appearance.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  role="menuitemradio"
                  aria-checked={theme === value}
                  onClick={() => setTheme(value)}
                  className={cn(
                    'flex flex-1 flex-col items-center gap-1 rounded-[9px] py-2 text-[11px] transition-colors',
                    theme === value ? 'tint text-primary' : 'text-dim hover:bg-sidebar-accent',
                  )}
                >
                  <Icon className="size-3.5" />
                  {label}
                </button>
              ))}
            </div>

            <div className="my-1 h-px bg-rule" />

            {connection ? (
              <button
                type="button"
                role="menuitem"
                disabled={pending}
                onClick={() => {
                  setOpen(false)
                  onClose()
                  disconnect()
                }}
                className="flex items-center gap-2 rounded-[9px] px-2 py-2 text-left text-[13px] transition-colors hover:bg-sidebar-accent disabled:opacity-50"
              >
                <Unplug className="size-3.5 text-dim" />
                Disconnect
              </button>
            ) : (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  onClose()
                  onConnect()
                }}
                className="flex items-center gap-2 rounded-[9px] px-2 py-2 text-left text-[13px] transition-colors hover:bg-sidebar-accent"
              >
                <Plug className="size-3.5 text-dim" />
                Connect an S3 bucket
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
