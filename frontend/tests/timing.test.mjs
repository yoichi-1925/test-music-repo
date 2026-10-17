import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isActive, playbackWindow } from '../src/timing.ts'

test('seek rounding still highlights the selected note', () => {
  assert.equal(isActive(1.044897, { start: 1.044897959, duration: .48 }), true)
})
test('a chord boundary selects the next chord and rests stay empty', () => {
  assert.equal(isActive(2, { start: 0, duration: 2 }), false)
  assert.equal(isActive(2, { start: 2, duration: 2 }), true)
  assert.equal(isActive(1.5, { start: 0, duration: 1 }), false)
  assert.equal(isActive(1.5, { start: 2, duration: 1 }), false)
})
test('seeking backwards selects the earlier segment', () => {
  assert.equal(isActive(.5, { start: 0, duration: 1 }), true)
  assert.equal(isActive(.5, { start: 1, duration: 1 }), false)
})
test('end of audio keeps the last score window visible', () => {
  assert.deepEqual(playbackWindow(8, 8), { start: 0, end: 8 })
  assert.deepEqual(playbackWindow(16, 16), { start: 8, end: 16 })
  assert.deepEqual(playbackWindow(8, 10), { start: 8, end: 10 })
  assert.deepEqual(playbackWindow(-1, 10), { start: 0, end: 8 })
})
