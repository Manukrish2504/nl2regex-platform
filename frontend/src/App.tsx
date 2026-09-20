import { useEffect, useState } from 'react'

type Health = Record<'database' | 'redis' | 'worker', boolean>

// Phase 0 placeholder: proves the browser -> API -> Postgres/Redis/Celery path works.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch('/api/health/')
      .then((res) => res.json())
      .then(setHealth)
      .catch(() => setError(true))
  }, [])

  return (
    <main>
      <h1>nl2regex platform</h1>
      {error && <p>API unreachable</p>}
      {!error && !health && <p>Checking services…</p>}
      {health && (
        <ul>
          {Object.entries(health).map(([service, ok]) => (
            <li key={service}>
              {ok ? '✅' : '❌'} {service}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
