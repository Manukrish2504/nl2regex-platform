# Frontend

```
src/features/<feature>/   api.ts (queries and calls) + its screens
src/components/ui/        shadcn primitives, unmodified where possible
src/components/           app shell, shared presentational pieces
src/lib/                  api.ts (typed ApiError), router.ts, utils.ts
```

- **A feature owns its API calls.** No shared "services" module.
- **Server state lives in TanStack Query.** A 401 from any request flips the app to
  "not connected" in one place (the `QueryCache` `onError` in `main.tsx`).
- **Polling stops itself**: `refetchInterval` returns `false` once the job is
  finished.
- **No secret in React state.** The connect form is uncontrolled, read once with
  `FormData`, and submitted with a plain async function: a TanStack mutation keeps
  its variables in cache for minutes.
- **Say what will be sent before it is sent.** Every mode that calls the language
  model states what leaves the browser, with a real example where possible.
- **Routing is the History API.** Two routes do not need a library.
- Tailwind 4 with the tokens in `index.css`. Dark only, one accent colour.
