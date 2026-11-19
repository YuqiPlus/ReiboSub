import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'))

test('frontend declares the supported Node minimum and a full-tree audit command', () => {
  assert.equal(manifest.engines.node, '>=22.12.0')
  assert.match(manifest.scripts['audit:deps'], /npm audit --include=dev/)
})

test('build tools are development dependencies and the lock matches the manifest', () => {
  assert(manifest.dependencies.vue)
  for (const name of ['vite', '@vitejs/plugin-vue']) {
    assert(manifest.devDependencies[name])
    assert.equal(manifest.dependencies[name], undefined)
  }
  for (const kind of ['dependencies', 'devDependencies']) {
    assert.deepEqual(lock.packages[''][kind], manifest[kind])
  }
})

test('locked dependencies retain fixes for the audited advisories', () => {
  // Known fixed floors complement, but do not replace, a fresh npm audit.
  const floors = { vue: '3.5.42', '@vue/server-renderer': '3.5.42', vite: '7.3.8',
    esbuild: '0.25.0', postcss: '8.5.23', nanoid: '3.3.18', 'source-map-js': '1.2.2' }
  const compare = (a, b) => {
    const left = a.split('.').map(Number), right = b.split('.').map(Number)
    for (let i = 0; i < 3; i++) { if (left[i] !== right[i]) return left[i] - right[i] }
    return 0
  }
  for (const [name, minimum] of Object.entries(floors)) {
    const version = lock.packages[`node_modules/${name}`]?.version
    assert.match(version || '', /^\d+\.\d+\.\d+$/)
    assert(compare(version, minimum) >= 0, `${name} ${version} must retain fixes from ${minimum}`)
  }
  assert.equal(lock.packages['node_modules/@vue/server-renderer'].version, lock.packages['node_modules/vue'].version)
})
