import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// FastAPI serves the built app straight out of ../static (see main.py's "/"
// route and the /static mount) — base must match that mount point so built
// asset URLs (/static/assets/...) resolve, but the dev server still serves
// from root so `npm run dev` works standalone.
const BACKEND_ROUTE_PREFIXES = [
  '/generate-stream',
  '/generate-from-file-stream',
  '/generate-epics',
  '/generate-stories',
  '/generate-tasks',
  '/generate-test-cases',
  '/clarify-chat',
  '/validate-brief',
  '/estimate-tokens',
  '/providers',
  '/health',
  '/brief-resources',
  '/history',
  '/generations',
  '/export-excel',
  '/epics',
  '/stories',
  '/tasks',
  '/dashboard',
  '/projects',
  '/redmine',
  '/hierarchy',
  '/push-to-redmine',
  '/assistant',
  '/jobs',
  '/bitbucket',
  '/push-to-bitbucket',
  '/webhooks',
  '/integrations',
  '/generation-summaries',
]

export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/' : '/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      BACKEND_ROUTE_PREFIXES.map((prefix) => [
        prefix,
        { target: 'http://127.0.0.1:8000', changeOrigin: true },
      ]),
    ),
  },
}))
