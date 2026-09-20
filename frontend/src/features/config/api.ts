import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export type Config = { describe_available: boolean; model: string | null }

/** What this server can do. It has no language model unless it was started with an API key. */
export function useConfig() {
  return useQuery({
    queryKey: ['config'],
    queryFn: () => api<Config>('/config/'),
    staleTime: Infinity,
  })
}
