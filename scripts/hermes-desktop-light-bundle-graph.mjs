#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import { readFile, mkdir, readdir, rm, writeFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const [sourceArg, outputArg, packArg] = process.argv.slice(2)
if (!sourceArg || !outputArg || !packArg) {
  throw new Error('usage: hermes-desktop-light-bundle-graph.mjs <source> <output> <win-unpacked>')
}

const source = path.resolve(sourceArg)
const output = path.resolve(outputArg)
const pack = path.resolve(packArg)
const app = path.join(source, 'apps', 'desktop')
process.chdir(app)
const renderer = path.join(output, 'renderer')
const main = path.join(output, 'main')
await rm(output, { recursive: true, force: true })
await mkdir(output, { recursive: true })

const appRequire = createRequire(path.join(app, 'package.json'))
const vite = await import(pathToFileURL(appRequire.resolve('vite')).href)
await vite.build({
  root: app,
  publicDir: path.join(app, 'public'),
  cacheDir: path.join(output, 'vite-cache'),
  configLoader: 'runner',
  build: {
    outDir: renderer,
    emptyOutDir: true,
    sourcemap: true,
  },
})

const stampPath = path.join(pack, 'resources', 'install-stamp.json')
const stampRaw = await readFile(stampPath, 'utf8')
const stamp = JSON.parse(stampRaw)
const variant = stamp.updateMechanism === 'microsoft-store' ? 'store'
  : stamp.payload === 'bootstrap' ? '' : stamp.payload
if (!['', 'bundled', 'light', 'store'].includes(variant)) {
  throw new Error(`Invalid desktop stamp payload: ${stamp.payload}`)
}
const identity = execFileSync(process.execPath, ['-e', 'console.log(JSON.stringify(require(process.argv[1])))',
  path.join(app, 'product-identity.cjs')], {
  env: {
    ...process.env,
    HERMES_DESKTOP_VARIANT: variant,
    HERMES_PAYLOAD_TAG: stamp.tag || '',
    HERMES_BUILD_COMMIT: stamp.source === 'commit-build' ? (stamp.commit || '') : '',
  },
  encoding: 'utf8',
}).trim()

const bundleEnv = await import(pathToFileURL(path.join(app, 'scripts', 'bundle-env.mjs')).href)
const envBanner = bundleEnv.environmentDefaultsBanner(process.env.HERMES_BUNDLE_ENV_JSON || '{}')
const esbuild = appRequire('esbuild')
const common = {
  absWorkingDir: app,
  bundle: true,
  platform: 'node',
  target: 'node20',
  external: ['electron', 'node-pty', 'get-windows', 'fs'],
  define: {
    'process.env.HERMES_DESKTOP_IS_PACKAGED': JSON.stringify(true),
    __HERMES_INSTALL_STAMP__: stampRaw,
    __HERMES_PRODUCT_IDENTITY__: identity,
  },
  metafile: true,
  logLevel: 'warning',
}
const entries = [
  ['electron-main', path.join(app, 'electron', 'entry.ts'), 'esm', '.mjs'],
  ['electron-preload', path.join(app, 'electron', 'preload.ts'), 'cjs', '.js'],
  ['preview-guest-preload', path.join(app, 'electron', 'preview-guest-preload-entry.ts'), 'cjs', '.js'],
]
await mkdir(main, { recursive: true })
for (const [name, entryPoint, format, extension] of entries) {
  const result = await esbuild.build({
    ...common,
    entryPoints: [entryPoint],
    format,
    outfile: path.join(main, `${name}${extension}`),
    ...(name === 'electron-main'
      ? { banner: { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" + envBanner } }
      : {}),
  })
  await writeFile(path.join(main, `${name}.metafile.json`), JSON.stringify(result.metafile))
}

function asarFiles(asarPath) {
  const bytes = readFileSync(asarPath)
  if (bytes.length < 16) throw new Error(`ASAR header is truncated: ${asarPath}`)
  const jsonSize = bytes.readUInt32LE(12)
  const headerEnd = 16 + jsonSize
  let tree
  try {
    tree = JSON.parse(bytes.subarray(16, headerEnd).toString('utf8'))
  } catch (error) {
    throw new Error(`Cannot parse ASAR header: ${asarPath}`, { cause: error })
  }
  const result = new Map()
  const visit = (node, prefix) => {
    for (const [name, value] of Object.entries(node || {})) {
      const relative = `${prefix}${name}`
      if (value && typeof value === 'object' && value.files) {
        visit(value.files, `${relative}/`)
      } else if (value && typeof value === 'object' && value.offset !== undefined && value.size !== undefined) {
        const start = headerEnd + Number(value.offset)
        result.set(relative, bytes.subarray(start, start + Number(value.size)))
      }
    }
  }
  visit(tree.files, '')
  return result
}

function stripSourceMapLine(bytes) {
  const text = bytes.toString('utf8')
  const marker = '\n//# sourceMappingURL='
  const index = text.lastIndexOf(marker)
  if (index < 0 || !text.slice(index).trimEnd().startsWith(marker.trimStart())) return text
  return text.slice(0, index + 1)
}

function outputFiles(root) {
  const result = new Map()
  const visit = async (directory, prefix = '') => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const relative = `${prefix}${entry.name}`
      const file = path.join(directory, entry.name)
      if (entry.isDirectory()) await visit(file, `${relative}/`)
      else if (/\.(?:js|mjs)$/.test(entry.name)) result.set(relative.replaceAll(path.sep, '/'), readFileSync(file))
    }
  }
  return visit(root).then(() => result)
}

const shipped = asarFiles(path.join(pack, 'resources', 'app.asar'))
const shippedJs = new Map()
const normalizedScripts = (files) => {
  const result = new Map()
  for (const [name, bytes] of files) {
    if (name.startsWith('node_modules/') || name.includes('/node_modules/')) continue
    const dist = name.indexOf('dist/')
    const relative = dist >= 0 ? name.slice(dist + 'dist/'.length) : name
    if (/\.(?:js|mjs)$/.test(relative)) result.set(relative, bytes)
  }
  return result
}
const addShippedScripts = (files) => {
  for (const [name, bytes] of normalizedScripts(files)) shippedJs.set(name, bytes)
}
addShippedScripts(shipped)
const unpackedDist = path.join(pack, 'resources', 'app.asar.unpacked', 'dist')
try {
  addShippedScripts(await outputFiles(unpackedDist))
} catch (error) {
  if (error?.code !== 'ENOENT') throw error
}
const shippedNames = [...shippedJs.keys()].sort()
const exactProduct = path.join(app, 'dist')
const reconstructed = normalizedScripts(await outputFiles(exactProduct))
const reconstructedNames = [...reconstructed.keys()].sort()
if (JSON.stringify(shippedNames) !== JSON.stringify(reconstructedNames)) {
  const reconstructedSet = new Set(reconstructedNames)
  const shippedSet = new Set(shippedNames)
  const missing = shippedNames.filter((name) => !reconstructedSet.has(name)).slice(0, 12)
  const extra = reconstructedNames.filter((name) => !shippedSet.has(name)).slice(0, 12)
  throw new Error(
    `Upstream desktop output set differs from shipped scripts: shipped=${shippedNames.length} reconstructed=${reconstructedNames.length} missing=${missing.join(',')} extra=${extra.join(',')}`,
  )
}
for (const name of shippedNames) {
  if (stripSourceMapLine(shippedJs.get(name)) !== stripSourceMapLine(reconstructed.get(name))) {
    throw new Error(`Bundle graph output differs from shipped product file: dist/${name}`)
  }
}

const manifest = {
  schema: 1,
  rendererMaps: renderer,
  mainMetafiles: main,
  equivalence: {
    asar: 'resources/app.asar/dist',
    unpacked: 'resources/app.asar.unpacked/dist',
    product: exactProduct,
    shippedJs: shippedNames,
    comparedAfter: 'stripping trailing //# sourceMappingURL= line',
  },
}
await writeFile(path.join(output, 'graph-emitter.json'), JSON.stringify(manifest))
