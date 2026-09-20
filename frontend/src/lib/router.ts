import { useSyncExternalStore } from 'react'

// The app has two routes, "/" and "/jobs/:id", so the browser's History API is all the router
// it needs. ponytail: reach for a routing library if routes ever nest or need loaders.

function subscribe(onChange: () => void) {
  window.addEventListener('popstate', onChange)
  return () => window.removeEventListener('popstate', onChange)
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname)
}

export function navigate(to: string) {
  if (to === window.location.pathname) return
  window.history.pushState(null, '', to)
  // pushState does not fire popstate by itself, and that event is what usePath listens to.
  window.dispatchEvent(new PopStateEvent('popstate'))
}

/** The job ID when the path is /jobs/:id, otherwise null. */
export function matchJobPath(path: string): string | null {
  return /^\/jobs\/([0-9a-f-]{36})\/?$/.exec(path)?.[1] ?? null
}
