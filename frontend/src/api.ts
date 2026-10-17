export type Chord = { start: number; duration: number; chord: string | null; confidence: number; source: string }
export type Analysis = { duration: number; bpm: number | null; beats: number[]; key: string | null; key_confidence: number; chords: Chord[]; time_signature: string }
export type SongSummary = { id: string; filename: string; created_at: string; status: string; progress: number; stage: string; revision: number; melody_status?: string; melody_progress?: number }
export type Song = SongSummary & { error: string | null; analysis: Analysis | null; original_analysis: Analysis | null; has_edits: boolean; has_tab: boolean }
export type Tab = { revision: number; text: string; tab: { capo: number; strokes: { time: number; bar: number; beat: number; sounding_chord: string | null }[] } }

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) {
    let message = `リクエストに失敗しました（${response.status}）`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = '入力内容（区間・BPMなど）を確認してください。'
    } catch { /* HTTPエラー本文がJSONでない場合は共通メッセージを表示する。 */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}
export const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const chordNames = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B','Cm','C#m','Dm','D#m','Em','Fm','F#m','Gm','G#m','Am','A#m','Bm']
export const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`

export type MelodyNote = { start: number; duration: number; midi: number; confidence: number; string: number | null; fret: number | null }
export type MelodyState = { status: string; progress: number; error: string | null; result: { duration: number; method: string; notes: MelodyNote[] } | null }

export type ScoreEvent = { start: number; duration: number; source_start: number; midi: number | null; confidence?: number; full_abc_start: number; ticks: number; tie_start: boolean; tie_stop: boolean }
export type StaffScore = { bpm: number; origin: number; region_end: number; bars: { number: number; events: ScoreEvent[] }[]; abc: string; musicxml: string; omitted_short_notes: number }
export type VocalResult = { duration: number; region_start?: number; region_end?: number; method: string; bpm?: number | null; estimated_bpm?: number | null; vocals_available?: boolean; notes: { start: number; duration: number; midi: number; confidence: number }[]; score?: StaffScore | null }
export type VocalState = { status: string; progress: number; error: string | null; result: VocalResult | null }
