// The renderer's development server as `electron-vite dev` serves it (root src/renderer, React's plugin
// with its Fast Refresh preamble), without starting Electron: node dev_server.mjs CLIENT_DIR PORT
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const [client, port] = process.argv.slice(2)
const load = (file) => import(pathToFileURL(path.join(client, 'node_modules', file)).href)
const { createServer } = await load('vite/dist/node/index.js')
const { default: react } = await load('@vitejs/plugin-react/dist/index.js')
const server = await createServer({
  configFile: false,
  root: path.join(client, 'src/renderer'),
  plugins: [react()],
  clearScreen: false,
  server: { host: '127.0.0.1', port: Number(port), strictPort: true },
})
await server.listen()
console.log('ready', server.resolvedUrls.local.join(' '))
