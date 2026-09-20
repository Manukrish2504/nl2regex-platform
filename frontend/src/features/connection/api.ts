import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from '@/lib/api'

export type Connection = { bucket: string; region: string }

export type ConnectRequest = {
  access_key_id: string
  secret_access_key: string
  bucket: string
}

export const connectionKey = ['connection'] as const

/** The current S3 connection, or null when there is none. Not being connected is not an error. */
export function useConnection() {
  return useQuery({
    queryKey: connectionKey,
    queryFn: () =>
      api<Connection>('/connection/').catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }),
    staleTime: Infinity,
  })
}

// Deliberately plain functions, not useMutation: TanStack Query keeps a mutation's variables in
// its cache for minutes, and here the variables would include the AWS secret key.
export function connect(request: ConnectRequest) {
  return api<Connection>('/connection/', { method: 'POST', body: JSON.stringify(request) })
}

export function disconnect() {
  return api<void>('/connection/', { method: 'DELETE' })
}

/** Disconnect and forget everything fetched through the connection. */
export function useDisconnect() {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(false)

  async function run() {
    setPending(true)
    // Whatever the server says, this browser is done with the connection.
    await disconnect().catch(() => undefined)
    queryClient.setQueryData(connectionKey, null)
    queryClient.removeQueries({ queryKey: ['files'] })
    setPending(false)
  }

  return { disconnect: run, pending }
}
