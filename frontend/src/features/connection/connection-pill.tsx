import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Unplug } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { connectionKey, disconnect, useConnection } from './api'

/** Shows which bucket is connected, with the way out. Renders nothing when not connected. */
export function ConnectionPill() {
  const queryClient = useQueryClient()
  const { data: connection } = useConnection()
  const [pending, setPending] = useState(false)

  if (!connection) return null

  async function handleDisconnect() {
    setPending(true)
    // Whatever the server says, this browser is done with the connection.
    await disconnect().catch(() => undefined)
    queryClient.setQueryData(connectionKey, null)
    queryClient.removeQueries({ queryKey: ['files'] })
    setPending(false)
  }

  return (
    <div className="flex items-center gap-1 rounded-full border border-border bg-card/70 py-1 pr-1 pl-3 text-sm backdrop-blur">
      <span className="size-2 rounded-full bg-primary" aria-hidden />
      <span className="max-w-48 truncate font-medium" title={connection.bucket}>
        {connection.bucket}
      </span>
      <span className="text-muted-foreground">{connection.region}</span>
      <Button
        variant="ghost"
        size="sm"
        className="rounded-full"
        onClick={handleDisconnect}
        disabled={pending}
      >
        <Unplug />
        Disconnect
      </Button>
    </div>
  )
}
