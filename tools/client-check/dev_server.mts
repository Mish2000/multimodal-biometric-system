// The renderer's development server as `electron-vite dev` serves it (root src/renderer, React's plugin
// with its Fast Refresh preamble), without starting Electron: node dev_server.mts CLIENT_DIR PORT
// Node.js runs this file as it is and removes the types when it loads it; the client's `npm run typecheck`
// checks them (tsconfig.json, beside this file).
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const [client, port] = process.argv.slice(2)
if (!client || !port) throw new Error('node dev_server.mts CLIENT_DIR PORT')
// The client's own packages, by their files: this folder has no packages of its own.
const load = <T,>(file: string): Promise<T> => import(pathToFileURL(path.join(client, 'node_modules', file)).href)
const { createServer } = await load<typeof import('vite')>('vite/dist/node/index.js')
const { default: react } = await load<typeof import('@vitejs/plugin-react')>('@vitejs/plugin-react/dist/index.js')
const server = await createServer({
  configFile: false,
  root: path.join(client, 'src/renderer'),
  plugins: [react()],
  clearScreen: false,
  server: { host: '127.0.0.1', port: Number(port), strictPort: true },
})
await server.listen()
console.log('ready', server.resolvedUrls?.local.join(' '))
