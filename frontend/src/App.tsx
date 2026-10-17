import { useCallback, useEffect, useRef, useState } from 'react'
import { request } from './api'
import type { Song, SongSummary } from './api'
import MelodyStudio from './MelodyStudio'

const statuses: Record<string, string> = {idle:'未解析',queued:'解析待ち',analyzing:'解析中',completed:'解析完了',failed:'要確認'}
export default function App() {
  const [library, setLibrary] = useState<SongSummary[]>([])
  const [song, setSong] = useState<Song | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [drag, setDrag] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const refresh = useCallback(async () => setLibrary(await request<SongSummary[]>('/songs')), [])
  useEffect(() => {
    const controller = new AbortController()
    request<SongSummary[]>('/songs',{signal:controller.signal}).then(setLibrary).catch(err=>{
      if (!controller.signal.aborted) setError(`APIに接続できません。サーバーの起動を確認してください。${err instanceof Error ? err.message : ''}`)
    })
    return ()=>controller.abort()
  }, [])
  async function open(id: string) {
    setBusy(true); setError('')
    try {setSong(await request<Song>(`/songs/${id}/analysis`))}
    catch(err) {setError(err instanceof Error ? err.message : '音源を開けませんでした')}
    finally {setBusy(false)}
  }
  async function upload(file?: File) {
    if (!file || busy) return
    if (!/\.(mp3|wav)$/i.test(file.name) || !file.size || file.size > 100*1024*1024) {setError('MP3/WAV（空でない100MiB以内）を選んでください'); return}
    setBusy(true); setError('')
    try {
      const form = new FormData(); form.append('file',file)
      setSong(await request<Song>('/songs',{method:'POST',body:form}))
      await refresh()
    } catch(err) {setError(err instanceof Error ? err.message : 'アップロードに失敗しました')}
    finally {setBusy(false); if(input.current) input.current.value=''}
  }
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/"><span className="brand-mark">♮</span><span>Melody Room<span className="brand-caption">LISTEN CLOSELY. WRITE THE MELODY.</span></span></a>
      <div className="workspace-label"><span>主旋律のワークスペース</span><span className="local-dot">LOCAL</span></div>
      <button className="nav-active" disabled={busy} onClick={()=>input.current?.click()}>＋ <span>音源を追加</span><span className="nav-note">↗</span></button>
      <div className="library-label">あなたの音源 <span>{library.length.toString().padStart(2,'0')}</span></div>
      <nav className="library" aria-label="保存した音源">{library.length ? library.map(item=><button key={item.id} disabled={busy} className={`song-link ${song?.id===item.id ? 'selected' : ''}`} onClick={()=>open(item.id)}><span className="song-icon">♫</span><span className="song-link-text"><strong>{item.filename}</strong><small>{statuses[item.melody_status ?? 'idle']}</small></span><span className={`tiny-dot ${item.melody_status ?? 'idle'}`}/></button>) : <p className="empty-library">音源を追加すると、<br/>ここに保存されます。</p>}</nav>
      <div className="side-footer"><div className="string-art"><i/><i/><i/><i/><i/></div><strong>まずは、一つひとつの音を。<br/>歌声から、主旋律の五線譜へ。</strong><p>音源の処理はこのPCで行います。</p><span>MELODY FIRST · VOL. 02</span></div>
    </aside>
    <main><header className="topbar"><span>WORKSPACE <span className="breadcrumb">／ 主旋律の採譜</span></span><span className="local-status"><i/> ローカル環境</span></header><div className="content">
      <div className="page-heading"><div className="eyebrow">SEPARATE. LISTEN. TRANSCRIBE.</div><h1>聴こえる主旋律を、<span>五線譜に。</span></h1><p>歌声を伴奏から分けて、音高とリズムを確認する。</p></div>
      <ol className="steps" aria-label="作業の流れ">{['音源を選ぶ','主旋律を解析','五線譜を確認'].map((label,i)=><li key={label} className="reached"><span>0{i+1}</span>{label}<b>→</b></li>)}</ol>
      {error && <div className="alert error" role="alert">{error}<button aria-label="エラーを閉じる" onClick={()=>setError('')}>×</button></div>}
      <section className={`upload-panel ${drag ? 'dragging' : ''}`} aria-label="音源アップロード" onDragOver={event=>{event.preventDefault(); setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={event=>{event.preventDefault(); setDrag(false); upload(event.dataTransfer.files[0])}}>
        <div className="upload-illustration" aria-hidden="true"><div className="disc"><span>♪</span></div><div className="mini-wave">▂▅▃▇▄▂▆▃▅</div></div><div className="upload-copy"><span className="eyebrow">START WITH A VOICE</span><h2>{busy ? '音源を準備しています…' : 'ここに音源をドロップ'}</h2><p>MP3・WAV ／ 最大100MiB・10分</p></div>
        <button className="primary" disabled={busy} onClick={()=>input.current?.click()}>＋ ファイルを選ぶ</button><input ref={input} className="sr-only" type="file" accept=".mp3,.wav" aria-label="音楽ファイル" onChange={event=>upload(event.target.files?.[0])}/>
      </section>
      {song ? <section><div className="section-heading"><div><span className="section-number">01</span><h2>{song.filename}</h2></div><span className="status-pill">主旋律ワークスペース</span></div><MelodyStudio key={song.id} songId={song.id} onSaved={refresh}/></section> : <div className="empty-workspace"><span>音源を選び、歌声のある短い区間から確認しましょう。</span><div>01 SEPARATE <i/> 02 TRANSCRIBE <i/> 03 REVIEW</div></div>}
      <footer><span>MELODY ROOM</span><p>自動採譜は下書きです。分離した歌声と聴き比べて確認してください。</p><span>ONE MELODY AT A TIME ♩</span></footer>
    </div></main>
  </div>
}
