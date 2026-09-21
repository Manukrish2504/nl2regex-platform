import { useState, type ReactNode } from "react";
import { ChevronDown, Menu, Plug, Plus, Search, Unplug, X } from "lucide-react";

import { Diamond } from "@/components/diamond";
import { Button } from "@/components/ui/button";
import { useConfig } from "@/features/config/api";
import { useConnection, useDisconnect } from "@/features/connection/api";
import { RecentJobs } from "@/features/jobs/recent-jobs";
import { cn } from "@/lib/utils";

interface AppShellProps {
  title: ReactNode;
  onNewTransformation: () => void;
  onConnect: () => void;
  /** The results panel, docked to the right of the conversation. */
  panel?: ReactNode;
  children: ReactNode;
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
  const [drawerOpen, setDrawerOpen] = useState(false);

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
          "absolute inset-y-0 left-0 z-40 w-[82%] max-w-[300px] transition-transform duration-200 ease-out lg:static lg:z-0 lg:w-[262px] lg:translate-x-0",
          drawerOpen
            ? "translate-x-0 shadow-2xl shadow-black/60"
            : "-translate-x-full",
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
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            {title}
          </div>
          <div className="hidden lg:block">
            <ModelPill />
          </div>
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
  );
}

function Sidebar({
  onNewTransformation,
  onConnect,
  onClose,
}: {
  onNewTransformation: () => void;
  onConnect: () => void;
  onClose: () => void;
}) {
  const { data: connection } = useConnection();
  const { disconnect, pending } = useDisconnect();

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

      <div className="flex items-center gap-2.5 px-3.5 py-3 lg:pt-4 lg:pb-2.5">
        <span className="flex size-[26px] shrink-0 items-center justify-center rounded-lg bg-linear-150 from-primary/70 to-primary/25">
          <span className="size-[9px] rotate-45 rounded-[2px] bg-[#05100e]" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="text-[14.5px] leading-tight font-semibold tracking-tight">
            nl2regex
          </span>
          <span className="truncate text-[11px] text-dim">
            {connection ? connection.bucket : "No bucket connected"}
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
          {connection ? (
            <Search className="size-3.5" />
          ) : (
            <Plug className="size-3.5" />
          )}
          {connection ? "Browse the bucket" : "Connect an S3 bucket"}
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
        <div className="flex items-center gap-2.5 border-t border-sidebar-border px-3.5 py-3">
          <span className="flex size-[26px] shrink-0 items-center justify-center rounded-full bg-[#0e1312] text-[10px] font-medium text-dim inset-ring inset-ring-[#1b2422]">
            S3
          </span>
          <div className="min-w-0 flex-1">
            <p
              className="truncate text-[13px] leading-tight"
              title={connection.bucket}
            >
              {connection.bucket}
            </p>
            <p className="text-[11px] text-dim">
              {connection.region} · read-only
            </p>
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
  );
}

/** Which model writes the patterns, in the top right, as the design has it. */
function ModelPill() {
  const { data: config } = useConfig();
  const available = config?.describe_available ?? false;

  return (
    <span
      className="flex shrink-0 items-center gap-2 rounded-full bg-[#0d1211] px-3 py-1.5 font-mono text-[11px] text-[#aab6b2] inset-ring inset-ring-[#1b2422]"
      title={
        available
          ? "The model that turns plain English into a pattern, and finds personal data"
          : "No API key on this server, so patterns must be typed"
      }
    >
      <Diamond
        className={available ? "text-primary" : "text-dim"}
        filled={available}
      />
      {config?.model ?? "regex only"}
    </span>
  );
}
