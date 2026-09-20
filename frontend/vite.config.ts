import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const target = (name: string, port: number) =>
  process.env.CI || !process.env.API_PROXY_TARGET ? `http://localhost:${port}` : `http://${name}:${port}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // One origin for everything, as in production: no CORS to configure, cookies just work,
    // and no service but this one needs a port published on the host.
    proxy: {
      '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
      '/flower': target('flower', 5555),
      // The cluster and the running job's own UI, for looking at what Spark is doing.
      '/spark-job': { target: target('worker-jobs', 4040), rewrite: (path) => path.replace(/^\/spark-job/, '') },
      '/spark': { target: target('spark-master', 8080), rewrite: (path) => path.replace(/^\/spark/, '') },
    },
  },
})
