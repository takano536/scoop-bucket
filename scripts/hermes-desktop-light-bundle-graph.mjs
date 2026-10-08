#!/usr/bin/env node
import { mkdir, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'

const [sourceArg, outputArg] = process.argv.slice(2)
if (!sourceArg || !outputArg) {
  throw new Error('usage: hermes-desktop-light-bundle-graph.mjs <source> <output>')
}

const source = path.resolve(sourceArg)
const output = path.resolve(outputArg)
const app = path.join(source, 'apps', 'desktop')
const renderer = path.join(output, 'renderer')
const main = path.join(output, 'main')
await rm(output, { recursive: true, force: true })
await mkdir(output, { recursive: true })

const appRequire = createRequire(path.join(app, 'package.json'))
const vite = await import(appRequire.resolve('vite'))
await vite.build({
  root: app,
  configFile: path.join(app, 'vite.config.ts'),
  configLoader: 'runner',
  build: {
    outDir: renderer,
    emptyOutDir: true,
    sourcemap: true,
  },
})

const esbuild = appRequire('esbuild')
const common = {
  absWorkingDir: app,
  bundle: true,
  platform: 'node',
  target: 'node20',
  external: ['electron', 'node-pty', 'get-windows', 'fs'],
  define: {
    'process.env.HERMES_DESKTOP_IS_PACKAGED': 'true',
    __HERMES_INSTALL_STAMP__: '{}',
    __HERMES_PRODUCT_IDENTITY__: '{}',
  },
  write: false,
  metafile: true,
  logLevel: 'warning',
}
const entries = [
  ['electron-main', path.join(app, 'electron', 'entry.ts'), 'esm'],
  ['electron-preload', path.join(app, 'electron', 'preload.ts'), 'cjs'],
  ['preview-guest-preload', path.join(app, 'electron', 'preview-guest-preload-entry.ts'), 'cjs'],
]
await mkdir(main, { recursive: true })
for (const [name, entryPoint, format] of entries) {
  const result = await esbuild.build({
    ...common,
    entryPoints: [entryPoint],
    format,
    outfile: path.join(main, `${name}.js`),
    ...(name === 'electron-main'
      ? { banner: { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" } }
      : {}),
  })
  await writeFile(path.join(main, `${name}.metafile.json`), JSON.stringify(result.metafile))
}

const manifest = {
  schema: 1,
  rendererMaps: renderer,
  mainMetafiles: main,
}
await writeFile(path.join(output, 'graph-emitter.json'), JSON.stringify(manifest))
