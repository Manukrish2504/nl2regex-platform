import { useInfiniteQuery, useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export type S3File = {
  key: string
  size: number
  last_modified: string
  /** null means the app cannot process this kind of file. */
  format: 'csv' | 'excel' | null
}

export type FileListing = {
  prefix: string
  folders: string[]
  files: S3File[]
  next_token: string | null
}

/** Pages of the folders and files directly under `prefix`. */
export function useFiles(prefix: string) {
  return useInfiniteQuery({
    queryKey: ['files', prefix],
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams({ prefix })
      if (pageParam) query.set('page_token', pageParam)
      return api<FileListing>(`/connection/files/?${query}`)
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_token,
  })
}

export type FilePreview =
  | { status: 'pending' }
  | { status: 'done'; columns: string[]; rows: (string | null)[][] }
  | { status: 'failed'; error: { code: string; message: string } }

/** Column names and first rows. A worker reads the file, so this polls until it has. */
export function usePreview(fileKey: string | null) {
  return useQuery({
    queryKey: ['preview', fileKey],
    queryFn: () => api<FilePreview>(`/connection/files/preview/?${new URLSearchParams({ key: fileKey! })}`),
    enabled: fileKey !== null,
    refetchInterval: (query) => (query.state.data?.status === 'pending' ? 800 : false),
    staleTime: Infinity,
  })
}
