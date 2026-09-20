import { Unplug } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useConnection, useDisconnect } from './api'

/** The foot of the sidebar: which bucket is connected, and the way out. */
export function ConnectionPanel() {
  const { data: connection } = useConnection()
  const { disconnect, pending } = useDisconnect()

  if (!connection) {
    return <p className="px-2 py-1.5 text-sm text-muted-foreground">No bucket connected</p>
  }

  return (
    <div className="flex items-center gap-2 rounded-lg px-2 py-1.5">
      <span className="size-2 shrink-0 rounded-full bg-primary" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={connection.bucket}>
          {connection.bucket}
        </p>
        <p className="text-xs text-muted-foreground">{connection.region}</p>
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={disconnect}
        disabled={pending}
        aria-label="Disconnect"
        title="Disconnect"
      >
        <Unplug />
      </Button>
    </div>
  )
}
