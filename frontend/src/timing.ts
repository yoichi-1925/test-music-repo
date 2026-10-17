// HTMLMediaElementのシーク時の小数丸め（約1μ秒）で、音符開始直前と誤判定しない。
export function isActive(time: number, event: { start: number; duration: number }) {
  const position = time + 0.0001
  return position >= event.start && position < event.start + event.duration
}

export function playbackWindow(time: number, duration: number, span = 8) {
  const start = Math.floor(Math.max(0, Math.min(time, duration - 1e-6)) / span) * span
  return { start, end: Math.min(start + span, duration) }
}
