import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const studio = readFileSync(new URL('./studio.css', import.meta.url), 'utf8')
const workspaces = readFileSync(new URL('./workspaces.css', import.meta.url), 'utf8')
const palette = Object.fromEntries([...studio.matchAll(/(--[\w-]+):\s*(#[\da-f]{6});/gi)].map(([, key, value]) => [key, value]))

function luminance(hex) {
  const rgb = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255)
  const linear = rgb.map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
  return linear.reduce((sum, value, i) => sum + value * [0.2126, 0.7152, 0.0722][i], 0)
}
function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

test('control outlines and focus remain visible on both form surfaces', () => {
  for (const background of ['#ffffff', palette['--soft']]) {
    for (const color of ['--line-strong', '--focus']) {
      assert(contrast(palette[color], background) >= 3, `${color} against ${background}`)
    }
  }
  assert(contrast(palette['--line'], '#ffffff') >= 1.5)
  assert(contrast(palette['--muted'], palette['--soft']) >= 4.5)
})

test('green theme keeps primary buttons readable rather than reverting to black or blue', () => {
  assert.equal(palette['--teal'], '#237553')
  assert.equal(palette['--focus'], '#246b4d')
  assert(contrast(palette['--teal'], '#ffffff') >= 4.5)
  assert(contrast(palette['--teal-dark'], palette['--selected-surface']) >= 4.5)
})

test('edit fields and composite controls use deliberate control boundaries', () => {
  assert.match(studio, /input, select, textarea\s*\{[^}]*border-color: var\(--line-strong\)/)
  for (const selector of ['.term-answer-row input', '.cue-editor textarea', '.cue-time-fields input', '.studio-search', '.links-composer', '.lab-version-card']) {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    assert.match(workspaces, new RegExp(`${escaped}\\s*\\{[^}]*var\\(--line-strong\\)`))
  }
  assert.match(workspaces, /:root :is\(input, select, textarea\):focus\s*\{[^}]*var\(--focus\)/)
})

test('selected items use an explicit accent rather than nearly-white outlines', () => {
  for (const selector of ['.studio-tabs button.active', '.editor-studio .subtitle-edit-item.selected', '.lab-version-card.selected']) {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    assert.match(workspaces, new RegExp(`${escaped}\\s*\\{[^}]*border-color: var\\(--focus\\)`))
  }
  assert.doesNotMatch(studio + workspaces, /border(?:-[\w-]+)?:[^;{}]*#(?:e[0-9a-f]{5}|eee)\b/i)
})
