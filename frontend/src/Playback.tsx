import { useEffect, useRef, useState } from 'react'
import type { Analysis, MelodyState } from './api'
import { clock, request } from './api'
import { isActive, playbackWindow } from './timing'

export function noteName(midi: number) {
  return ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][midi % 12] + (Math.floor(midi / 12) - 1)
}

export default function Playback({ songId, analysis, onPosition, dirty }: {
  songId: string; analysis: Analysis; onPosition: (time: number) => void; dirty: boolean
}) {
  const audio = useRef<HTMLAudioElement>(null)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState('1')
  const [melody, setMelody] = useState<MelodyState | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [follow, setFollow] = useState(true)
  const activeNote = useRef<HTMLButtonElement>(null)
  const noteStrip = useRef<HTMLDivElement>(null)
  const scoreScroll = useRef<HTMLDivElement>(null)
  const notes = melody?.result?.notes ?? []
  const currentNote = notes.find(note => isActive(time, note))
  const currentChord = analysis.chords.find(chord => isActive(time, chord))
  const processing = melody?.status === 'queued' || melody?.status === 'analyzing'
  const span = 8
  const { start, end } = playbackWindow(time, analysis.duration, span)
  const visibleNotes = notes.filter(note => note.start < end && note.start + note.duration > start)
  const low = Math.min(60, ...visibleNotes.map(note => note.midi)) - 2
  const high = Math.max(72, ...visibleNotes.map(note => note.midi)) + 2
  const left = 50, width = 730
  const x = (seconds: number) => left + (seconds - start) / span * width
  const y = (midi: number) => 200 - (midi - low) / (high - low) * 130

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const value = await request<MelodyState>(`/songs/${songId}/melody`, { signal: controller.signal })
        if (controller.signal.aborted) return
        setMelody(value); setError('')
        if (value.status === 'queued' || value.status === 'analyzing') timer = setTimeout(poll, 1500)
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'メロディ情報を取得できませんでした')
          timer = setTimeout(poll, 4000)
        }
      }
    }
    poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [songId, refresh])

  useEffect(() => {
    if (!playing) return
    let frame: number, last = 0
    const tick = (now: number) => {
      if (audio.current && now - last >= 80) {
        const next = audio.current.currentTime
        setTime(next); onPosition(next); last = now
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, onPosition])

  useEffect(() => {
    const node = activeNote.current, strip = noteStrip.current
    if (follow && node && strip) strip.scrollTo({ left: node.offsetLeft - strip.clientWidth / 2 + node.offsetWidth / 2, behavior: 'auto' })
  }, [currentNote?.start, follow, playing])

  useEffect(() => {
    const element = scoreScroll.current
    if (follow && element) {
      const svgWidth = element.querySelector('svg')?.getBoundingClientRect().width ?? 810
      element.scrollTo({ left: x(time) / 810 * svgWidth - element.clientWidth / 2, behavior: 'auto' })
    }
  }, [time, follow, playing])

  async function extract() {
    setError(''); setStarting(true)
    try {
      await request(`/songs/${songId}/melody`, { method: 'POST' })
      setMelody(old => ({ status: 'queued', progress: 0, error: null, result: old?.result ?? null }))
      setRefresh(value => value + 1)
    } catch (err) { setError(err instanceof Error ? err.message : 'メロディ推定を開始できませんでした') }
    finally { setStarting(false) }
  }
  function seek(value: number) {
    if (!audio.current) return
    audio.current.currentTime = value
    setTime(value); onPosition(value)
  }
  function sync() {
    if (audio.current) { setTime(audio.current.currentTime); onPosition(audio.current.currentTime) }
  }

  return <section className="playback-panel" aria-label="音源と楽譜の同期再生">
    <div className="playback-heading"><div><span className="eyebrow">PLAY ALONG</span><h2>音源と一緒に、譜面を追いかける。</h2></div><span className="playback-clock">{clock(time)} / {clock(analysis.duration)}</span></div>
    <audio ref={audio} controls preload="metadata" src={`/api/songs/${songId}/audio`} aria-label="元の音源" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onTimeUpdate={sync} onSeeked={sync} onEnded={() => { setPlaying(false); sync() }} onError={() => setError('音源を再生できません。サーバーと元のファイルを確認してください。')}/>
    <div className="playback-controls"><label>再生速度 <select aria-label="再生速度" value={rate} onChange={event => {
      setRate(event.target.value)
      if (audio.current) audio.current.playbackRate = Number(event.target.value)
    }}>{['0.5', '0.75', '1', '1.25'].map(value => <option value={value} key={value}>{value}×</option>)}</select></label><label><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)}/> 音符一覧を自動追従</label><span>現在のコード <strong data-testid="playing-chord">{currentChord?.chord ?? 'N.C.'}</strong></span><span>メロディ <strong data-testid="playing-note">{currentNote ? noteName(currentNote.midi) : '—'}</strong></span></div>
    {dirty && <p className="inline-note">同期表示は保存済みのコードです。編集中の変更は保存後に反映されます。</p>}
    <div className="melody-actions"><div><strong>メロディライン（推定）</strong><p>単旋律向けの音高推定です。伴奏込みの曲では、歌や主旋律を正しく拾えない場合があります。</p></div><button className="secondary" disabled={processing || starting} onClick={extract}>{processing ? `メロディ推定中 ${melody?.progress ?? 0}%` : notes.length ? 'メロディを再推定' : 'メロディを推定'}</button></div>
    {processing && <progress max={100} value={melody?.progress ?? 0} aria-label="メロディ推定進捗"/>}
    {(error || melody?.error) && <p role="alert" className="playback-error">{error || melody?.error}</p>}
    <div className="score-scroll" ref={scoreScroll}><svg viewBox="0 0 810 365" role="img" aria-label={`${start.toFixed(0)}秒から${end.toFixed(1)}秒のコードとメロディTAB`}>
      <text x="4" y="28" className="score-label">CHORD</text>
      {analysis.chords.filter(chord => chord.start < end && chord.start + chord.duration > start).map(chord => {
        const a = Math.max(chord.start, start), b = Math.min(chord.start + chord.duration, end)
        const active = isActive(time, chord)
        return <g key={chord.start} className={active ? 'score-chord active' : 'score-chord'}><rect x={x(a)} y="8" width={Math.max(1, x(b) - x(a) - 2)} height="30" rx="4"/><text x={x(a) + 6} y="28">{chord.chord ?? 'N.C.'}</text></g>
      })}
      <text x="4" y="60" className="score-label">NOTE</text>
      {Array.from({ length: high - low + 1 }, (_, i) => low + i).filter(midi => midi % 12 === 0 || midi % 12 === 7).map(midi => <g key={midi}><line x1={left} x2={x(end)} y1={y(midi)} y2={y(midi)} className="pitch-grid"/><text x="6" y={y(midi) + 3} className="score-label">{noteName(midi)}</text></g>)}
      {visibleNotes.map(note => <g key={note.start} className={`pitch-note ${isActive(time, note) ? 'active' : ''}`}><rect x={x(Math.max(start, note.start))} y={y(note.midi) - 5} width={Math.max(3, x(Math.min(end, note.start + note.duration)) - x(Math.max(start, note.start)))} height="10" rx="3"/><text x={x(Math.max(start, note.start)) + 2} y={y(note.midi) - 10}>{noteName(note.midi)}</text></g>)}
      <text x="4" y="232" className="score-label">TAB</text>
      {['e', 'B', 'G', 'D', 'A', 'E'].map((name, i) => <g key={name}><text x="19" y={251 + i * 16} className="score-string">{name}</text><line x1={left} x2={x(end)} y1={247 + i * 16} y2={247 + i * 16} className="tab-string"/></g>)}
      {visibleNotes.filter(note => note.string !== null).map(note => {
        const a = x(Math.max(start, note.start)), b = 247 + (note.string! - 1) * 16
        return <g key={note.start} className={`fret-note ${isActive(time, note) ? 'active' : ''}`}><rect x={a - 5} y={b - 8} width="22" height="16" rx="3"/><text x={a + 5} y={b + 4} textAnchor="middle">{note.fret}</text></g>
      })}
      {Array.from({ length: Math.ceil(end - start) }, (_, i) => start + i).map(t => <text key={t} x={x(t)} y="353" className="score-label">{t.toFixed(0)}s</text>)}
      <line data-testid="score-playhead" x1={x(time)} x2={x(time)} y1="3" y2="334" className="playhead"/>
    </svg></div>
    {!melody?.result && !processing && <p className="inline-note">「メロディを推定」で音符と単音TABを追加できます。コードだけでも音源と同期します。</p>}
    {melody?.status === 'completed' && !notes.length && <p className="inline-note">信頼できる音高が見つかりませんでした。独奏や歌声がはっきりした音源でお試しください。</p>}
    {notes.length > 0 && <div className="melody-notes" ref={noteStrip} aria-label="表示区間の推定音符一覧">{visibleNotes.map(note => <button key={note.start} ref={currentNote === note ? activeNote : undefined} className={isActive(time, note) ? 'active' : ''} aria-label={`${note.start.toFixed(2)}秒の${noteName(note.midi)}へ移動`} onClick={() => seek(note.start)}><small>{note.start.toFixed(2)}s</small><strong>{noteName(note.midi)}</strong><span>{note.string ? `${note.string}弦 ${note.fret}F` : '音域外'}</span></button>)}</div>}
    <p className="playback-footnote">再生しているのはアップロードした元音源です。表示の音符は自動採譜の参考情報で、五線譜のリズム表記やボーカル分離は行いません。</p>
  </section>
}
