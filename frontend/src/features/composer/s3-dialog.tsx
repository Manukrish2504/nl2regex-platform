import { useEffect, useRef, useState } from 'react'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConnectForm } from '@/features/connection/connect-form'
import { useConnection } from '@/features/connection/api'
import { FileBrowser } from '@/features/files/file-browser'
import type { S3File } from '@/features/files/api'

interface S3DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (file: S3File) => void
}

/** One dialog for the whole S3 step: the connect form until connected, then the file browser. */
export function S3Dialog({ open, onOpenChange, onSelect }: S3DialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">{open && <S3DialogBody onSelect={onSelect} />}</DialogContent>
    </Dialog>
  )
}

function S3DialogBody({ onSelect }: { onSelect: (file: S3File) => void }) {
  const { data: connection } = useConnection()

  // While this dialog is open the Disconnect button is unreachable, so a connection that
  // disappears here can only have expired on the server.
  const wasConnected = useRef(Boolean(connection))
  const [expired, setExpired] = useState(false)
  useEffect(() => {
    if (wasConnected.current && !connection) setExpired(true)
    wasConnected.current = Boolean(connection)
  }, [connection])

  if (!connection) {
    return (
      <>
        <DialogHeader>
          <DialogTitle>Connect your S3 bucket</DialogTitle>
          <DialogDescription>
            Use an access key that can read the bucket. It works with a bucket in any region.
          </DialogDescription>
        </DialogHeader>
        <ConnectForm notice={expired ? 'Your connection expired. Connect again to continue.' : undefined} />
      </>
    )
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Choose a file</DialogTitle>
        <DialogDescription>CSV and Excel (.xlsx) files can be processed.</DialogDescription>
      </DialogHeader>
      <FileBrowser bucket={connection.bucket} onSelect={onSelect} />
    </>
  )
}
