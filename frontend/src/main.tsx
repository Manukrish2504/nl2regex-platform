import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'

import './index.css'
import App from './App.tsx'
import { connectionKey } from '@/features/connection/api'
import { ApiError } from '@/lib/api'
import { applyStoredTheme } from '@/lib/theme'

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    // A 401 from any request means the server has forgotten the connection (it expired).
    // Reflect that at once, so the app returns to "not connected" wherever the user is.
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) {
        queryClient.setQueryData(connectionKey, null)
      }
    },
  }),
  defaultOptions: {
    queries: {
      // Retry only what might succeed next time: server errors and network failures.
      retry: (failureCount, error) =>
        failureCount < 2 && error instanceof ApiError && (error.status === 0 || error.status >= 500),
      refetchOnWindowFocus: false,
    },
  },
})

applyStoredTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
