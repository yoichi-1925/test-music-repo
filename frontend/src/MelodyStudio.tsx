import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { clock, json, request } from './api'
import type { VocalState } from './api'
const StaffScore = lazy(() => import('./StaffScore'))
import { isActive } from './timing'

const pitchName = (midi: number) => ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][midi % 12] + (Math.floor(midi / 12) - 1)

export default function MelodyStudio({ songId, onSaved }: { songId: string; onSaved: () => Promise<void> }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [state, setState] = useState<VocalState | null>(null)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [source, setSource] = useState('mix')
  const [mode, setMode] = useState('original')
  const [start, setStart] = useState('0')
  const [end, setEnd] = useState('30')
  const [bpm, setBpm] = useState('')
  const [rate, setRate] = useState('1')
  const [follow, setFollow] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const initialized = useRef(false)
  const pendingSeek = useRef<number | null>(null)
  const result = state?.result
  const processing = state?.status === 'queued' || state?.status === 'analyzing'
  const offset = mode === 'vocals' ? result?.region_start ?? 0 : 0
  const current = result?.score ? result.score.bars.flatMap(bar=>bar.events).find(note=>isActive(time,note) && note.midi !== null) : result?.notes.find(note => isActive(time, note))
  const validRange = Number(start) >= 0 && Number(end) > Number(start) && (!duration || Number(start) < duration)
  const validBpm = !bpm || Number(bpm) >= 20 && Number(bpm) <= 300

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const next = await request<VocalState>(`/songs/${songId}/melody`, {signal:controller.signal})
        if (controller.signal.aborted) return
        setState(next)
        if (!initialized.current && next.result) {
          initialized.current = true
          setStart(String(next.result.region_start ?? 0)); setEnd(String(next.result.region_end ?? next.result.duration))
          setSource(next.result.method.includes('demucs') ? 'mix' : 'solo')
          setBpm(next.result.bpm ? String(next.result.bpm) : '')
        }
        if (next.status === 'queued' || next.status === 'analyzing') timer = setTimeout(poll, 1600)
        else if (next.status === 'completed') await onSaved()
      } catch (err) {
        if (!controller.signal.aborted) { setError(err instanceof Error ? err.message : '接続エラー'); timer = setTimeout(poll, 4000) }
      }
    }
    poll()
    return () => {controller.abort(); clearTimeout(timer)}
  }, [songId, refresh, onSaved])
  useEffect(() => {
    if (!playing) return
    let frame: number, last = 0
    const tick = (now: number) => {
      if (audio.current && pendingSeek.current === null && now - last >= 80) {setTime(audio.current.currentTime + offset); last = now}
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, offset])
  function sync() {
    if (audio.current && pendingSeek.current === null) setTime(audio.current.currentTime + offset)
  }
  function seek(seconds: number) {
    if (!audio.current) return
    const last = Number.isFinite(audio.current.duration) ? Math.max(0, audio.current.duration - .001) : 600
    const relative = Math.max(0, Math.min(seconds - offset, last))
    audio.current.currentTime = relative
    setTime(relative + offset)
  }
  function changeMode(value: string) {
    audio.current?.pause()
    pendingSeek.current = time
    setMode(value)
  }
  async function analyze() {
    if (processing || !validRange || !validBpm) return
    setBusy(true); setError('')
    if (mode === 'vocals') changeMode('original')
    try {
      await request(`/songs/${songId}/melody`, json('POST', {source, start:Number(start), end:Number(end), bpm:bpm ? Number(bpm) : null}))
      setState(old => ({status:'queued', progress:0, error:null, result:old?.result ?? null}))
      setRefresh(value => value + 1)
    } catch (err) {setError(err instanceof Error ? err.message : '解析を開始できませんでした')}
    finally {setBusy(false)}
  }
  async function reviseRhythm() {
    if (!bpm || !validBpm) return
    setBusy(true); setError('')
    try {setState(await request<VocalState>(`/songs/${songId}/score`, json('POST', {bpm:Number(bpm)})))}
    catch(err) {setError(err instanceof Error ? err.message : '譜面を作成できませんでした')}
    finally {setBusy(false)}
  }
  return <section className="melody-studio">
    <div className="studio-heading"><span className="eyebrow">MELODY FIRST</span><h2>主旋律を聴いて、五線譜へ。</h2><p>まずは20〜30秒の区間で、分離した歌声と音符を確認しましょう。</p></div>
    <div className="analysis-settings">
      <label>音源の種類<select aria-label="音源の種類" value={source} onChange={event=>setSource(event.target.value)} disabled={processing || busy}><option value="mix">歌＋伴奏（ボーカル分離）</option><option value="solo">独奏・分離済みの歌声</option></select></label>
      <label>開始（秒）<input aria-label="解析開始秒" type="number" min="0" max="600" step="0.1" value={start} onChange={event=>setStart(event.target.value)} disabled={processing || busy}/></label>
      <label>終了（秒）<input aria-label="解析終了秒" type="number" min="0" max={duration || 600} step="0.1" value={end} onChange={event=>setEnd(event.target.value)} disabled={processing || busy}/></label>
      <label>BPM（空欄で推定）<input aria-label="採譜BPM" type="number" min="20" max="300" step="any" value={bpm} placeholder={result?.bpm ? result.bpm.toFixed(1) : '自動'} onChange={event=>setBpm(event.target.value)} disabled={processing || busy}/></label>
      <button className="primary" disabled={processing || busy || !validRange || !validBpm} onClick={analyze}>{processing ? `主旋律を解析中 ${state?.progress ?? 0}%` : '主旋律を解析'} →</button>
    </div>
    <p className="studio-note">歌声はPC内で分離します。初回は約80MBのモデル取得が必要です。Intel Macでは分離に時間がかかります。終了秒は音源末尾までに制限されます。</p>
    {processing && <div className="progress-panel" role="status"><strong>{state?.status === 'queued' ? '解析待ち' : (state?.progress ?? 0) < 55 ? '歌声と伴奏を分離しています' : '音高・リズムを整理しています'}</strong><progress aria-label="主旋律解析進捗" max="100" value={state?.progress ?? 0}/><p>元音源を外部へ送信しません。処理中も元音源を再生できます。</p></div>}
    {(error || state?.error) && <div className="alert error" role="alert">{error || state?.error}</div>}
    <div className="review-player">
      <div className="review-player-top"><div className="source-switch"><button aria-pressed={mode==='original'} onClick={()=>changeMode('original')}>元音源</button><button aria-pressed={mode==='vocals'} disabled={!result?.vocals_available || processing} onClick={()=>changeMode('vocals')}>分離した歌声</button></div><span>{clock(time)} / {clock(duration || result?.duration || 0)}</span></div>
      <audio key={`${songId}-${mode}-${mode==='vocals' ? result?.region_start : ''}`} ref={audio} controls preload="metadata" aria-label="確認用音源" src={`/api/songs/${songId}/${mode === 'vocals' ? 'vocals' : 'audio'}`} onLoadedMetadata={()=>{
        if (!audio.current) return
        if (mode==='original') setDuration(audio.current.duration)
        audio.current.playbackRate = Number(rate)
        const desired = pendingSeek.current
        pendingSeek.current = null
        if (desired !== null) seek(desired)
      }} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onTimeUpdate={sync} onSeeked={sync} onEnded={()=>{setPlaying(false); sync()}} onError={()=>setError('音源を読み込めません。サーバーとファイルを確認してください。')}/>
      <div className="playback-controls"><label>速度<select aria-label="再生速度" value={rate} onChange={event=>{setRate(event.target.value); if(audio.current) audio.current.playbackRate=Number(event.target.value)}}>{['0.5','0.75','1'].map(value=><option key={value} value={value}>{value}×</option>)}</select></label><label><input type="checkbox" checked={follow} onChange={event=>setFollow(event.target.checked)}/> 五線譜を自動追従</label>{result && <button className="text-button" onClick={()=>seek(result.region_start ?? 0)}>解析区間の先頭へ ↗</button>}<span className="current-pitch">現在の音 <strong data-testid="playing-note">{current && current.midi !== null ? pitchName(current.midi) : '—'}</strong></span></div>
      {mode==='vocals' && <p className="studio-note">分離した歌声は解析区間のみです。表示時刻は元音源の位置に合わせています。音源切替時は一時停止します。</p>}
    </div>
    {result && <div className="staff-result">
      <div className="staff-result-top"><div><span className="eyebrow">MELODY SCORE · DRAFT</span><h3>主旋律の五線譜</h3><p>{(result.region_start ?? 0).toFixed(1)}〜{(result.region_end ?? result.duration).toFixed(1)}秒 · {result.notes.length}音 · {result.bpm ? `${result.bpm.toFixed(1)} BPM` : 'テンポ未確定'} · {result.method.includes('demucs') ? 'ボーカル分離あり' : '分離なし'}</p></div><div className="score-actions"><button className="secondary" onClick={reviseRhythm} disabled={processing || busy || !bpm || !validBpm}>BPMで譜面を再整理</button>{result.score && <a className="secondary" href={`/api/songs/${songId}/score?format=musicxml`}>MusicXML保存 ↗</a>}</div></div>
      {result.estimated_bpm && result.bpm && Math.abs(result.estimated_bpm - result.bpm) > .1 && <p className="studio-note">音源からのテンポ推定は{result.estimated_bpm.toFixed(1)} BPMです。現在の譜面は入力されたBPMで整理しています。</p>}
      {!!result.score?.omitted_short_notes && <p className="alert notice">格子に収まらない短い音を{result.score.omitted_short_notes}音省略しています。BPMが半分に推定されていないか確認してください。</p>}
      <p className="studio-note">4/4・16分音符単位の採譜下書きです。小節頭は区間先頭を仮定し、調号は付けず臨時記号で表示します。音高の不確かな音符は茶色、現在位置は緑色です。</p>
      {result.score ? <Suspense fallback={<p>五線譜を準備しています…</p>}><StaffScore score={result.score} time={time} follow={follow} onSeek={seek}/></Suspense> : <div className="score-placeholder">BPMを入力して「BPMで譜面を再整理」を押すと、五線譜を作成できます。</div>}
      {!result.notes.length && <p className="alert notice">信頼できる音高を検出できませんでした。歌声がある区間を選び直してください。</p>}
      <p className="studio-note">ボーカル分離後も、ハモリ・ビブラート・ラップ・残った伴奏による誤推定があります。元音源と歌声を聴き比べて確認してください。五線譜上の音符をクリックすると、その位置へ移動します。</p>
    </div>}
  </section>
}
