import { Unplug } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useConnection, useDisconnect } from './api'

/** The connection in one line, for the small-screen header. Renders nothing when not connected. */
export function ConnectionPill() {
  const { data: connection } = useConnection()
  const { disconnect, pending } = useDisconnect()

  if (!connection) return null

  return (
    <div className="flex min-w-0 items-center gap-1 rounded-full border border-border bg-card/70 py-1 pr-1 pl-3 text-sm backdrop-blur">
      <span className="size-2 shrink-0 rounded-full bg-primary" aria-hidden />
      <span className="truncate font-medium" title={connection.bucket}>
        {connection.bucket}
      </span>
      <Button
        variant="ghost"
        size="icon-sm"
        className="shrink-0 rounded-full"
        onClick={disconnect}
        disabled={pending}
        aria-label="Disconnect"
      >
        <Unplug />
      </Button>
    </div>
  )
}
