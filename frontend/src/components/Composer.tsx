import type React from 'react'
import { useEffect, useRef, useState } from 'react'
import { useApp } from '../App'
import { Arrow, FileIcon, LinkIcon, MicIcon, StopIcon, TextIcon, VideoIcon } from '../icons'

type Tab = 'text' | 'url' | 'file' | 'voice' | 'video'

const EXAMPLES = [
  'NASA confirmed that Earth will experience six days of complete darkness in December.',
  'India won the 2024 T20 World Cup, beating South Africa in the final.',
  'The new ₹2000 notes contain a GPS nano chip that lets authorities track them.',
]

const ACCEPT: Record<'file' | 'voice' | 'video', string> = {
  file: '.png,.jpg,.jpeg,.webp,.gif,.bmp,.pdf,.docx,.txt,.md',
  voice: '.mp3,.wav,.m4a,.ogg,.webm,.flac,.aac',
  video: '.mp4,.mov,.mkv,.webm,.avi',
}

function fmtSize(n: number) {
  return n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`
}

// minimal typing for the browser speech API
type SR = {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: (e: { resultIndex: number; results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void
  onend: () => void
  onerror: (e: { error: string }) => void
  start: () => void
  stop: () => void
}

// survives the composer unmounting while a check runs, so "Edit and try again" keeps the input
const draft = { tab: 'text' as Tab, text: '', url: '' }

export default function Composer() {
  const { start } = useApp()
  const [tab, setTab] = useState<Tab>(draft.tab === 'text' || draft.tab === 'url' ? draft.tab : 'text')
  const [text, setText] = useState(draft.text)
  const [url, setUrl] = useState(draft.url)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string>('')
  const [over, setOver] = useState(false)
  const [err, setErr] = useState('')
  const [dictating, setDictating] = useState(false)
  const [recording, setRecording] = useState(false)
  const [secs, setSecs] = useState(0)
  const sr = useRef<SR | null>(null)
  const rec = useRef<MediaRecorder | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!file) return setPreview('')
    const u = URL.createObjectURL(file)
    setPreview(u)
    return () => URL.revokeObjectURL(u)
  }, [file])

  useEffect(() => {
    if (!recording) return
    const t = window.setInterval(() => setSecs((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [recording])

  useEffect(() => {
    Object.assign(draft, { tab, text, url })
  }, [tab, text, url])

  const words = text.trim() ? text.trim().split(/\s+/).length : 0

  function switchTab(t: Tab) {
    setTab(t)
    setErr('')
    if (t !== tab) setFile(null)
  }

  function pick(f: File | undefined) {
    if (!f) return
    setErr('')
    setFile(f)
  }

  function dictate() {
    const W = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR }
    const Ctor = W.SpeechRecognition ?? W.webkitSpeechRecognition
    if (!Ctor) {
      setErr('This browser has no speech recognition. Use Chrome or Edge, or record in the Voice tab.')
      return
    }
    if (dictating) {
      sr.current?.stop()
      return
    }
    const r = new Ctor()
    r.lang = navigator.language || 'en-IN'
    r.interimResults = false
    r.continuous = true
    r.onresult = (e) => {
      let add = ''
      for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) add += e.results[i][0].transcript
      if (add) setText((t) => (t ? t.trimEnd() + ' ' : '') + add.trim())
    }
    r.onend = () => setDictating(false)
    r.onerror = (e) => {
      setDictating(false)
      if (e.error === 'not-allowed') setErr('Microphone access was blocked. Allow it in the address bar and try again.')
    }
    sr.current = r
    r.start()
    setDictating(true)
  }

  async function toggleRecord() {
    if (recording) {
      rec.current?.stop()
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      const chunks: Blob[] = []
      mr.ondataavailable = (e) => chunks.push(e.data)
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        setRecording(false)
        const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' })
        setFile(new File([blob], `recording-${new Date().toISOString().slice(11, 19).replace(/:/g, '')}.webm`, { type: blob.type }))
      }
      rec.current = mr
      setSecs(0)
      setFile(null)
      mr.start()
      setRecording(true)
    } catch {
      setErr('Microphone access was blocked. Allow it in the address bar, or upload a recording instead.')
    }
  }

  function submit() {
    setErr('')
    if (tab === 'text') {
      if (text.trim().split(/\s+/).length < 3) return setErr('Write the claim as a full statement — at least a few words.')
      start({ kind: 'text', text }, text.trim())
    } else if (tab === 'url') {
      if (!/^(https?:\/\/)?[\w-]+(\.[\w-]+)+/.test(url.trim())) return setErr('Paste a full article link, like https://example.com/story.')
      start({ kind: 'url', url: url.trim() }, url.trim())
    } else {
      if (!file) return setErr(tab === 'voice' ? 'Record or upload a recording first.' : 'Choose a file first.')
      start({ kind: 'file', file }, file.name)
    }
  }

  const ready =
    (tab === 'text' && words >= 3) || (tab === 'url' && url.trim().length > 5) || (tab !== 'text' && tab !== 'url' && !!file)

  const tabs: [Tab, string, string, React.ReactElement][] = [
    ['text', 'Text', 'A message, headline or article', <TextIcon key="t" />],
    ['url', 'News link', 'Paste the link to a story', <LinkIcon key="u" />],
    ['file', 'Image or file', 'Screenshot, poster, PDF, Word', <FileIcon key="f" />],
    ['voice', 'Voice', 'Record or upload audio', <MicIcon key="v" />],
    ['video', 'Video', 'A short clip with speech', <VideoIcon key="vi" />],
  ]

  const dropzone = (kind: 'file' | 'voice' | 'video') => (
    <>
      {!file ? (
        <div
          className={`drop ${over ? 'over' : ''}`}
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            pick(e.dataTransfer.files[0])
          }}
        >
          <strong>
            {kind === 'file' ? 'Drop a screenshot, poster or document' : kind === 'voice' ? 'Drop an audio file' : 'Drop a video clip'}
          </strong>
          <p>
            {kind === 'file'
              ? 'PNG, JPG, WebP, PDF, Word or text · text is read with OCR'
              : kind === 'voice'
                ? 'MP3, WAV, M4A, OGG, WebM · speech is transcribed, then checked'
                : 'MP4, MOV, MKV, WebM · speech and on-screen text are extracted'}
            {' · up to 40 MB'}
          </p>
        </div>
      ) : (
        <div className="file-pill">
          {file.type.startsWith('image/') && <img src={preview} alt="" />}
          {file.type.startsWith('audio/') && <audio src={preview} controls />}
          {file.type.startsWith('video/') && <video src={preview} controls muted />}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="name">{file.name}</div>
            <div className="size">{fmtSize(file.size)}</div>
          </div>
          <button className="linkish" onClick={() => setFile(null)}>
            Remove
          </button>
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        accept={ACCEPT[kind]}
        onChange={(e) => {
          pick(e.target.files?.[0])
          e.target.value = ''
        }}
      />
    </>
  )

  return (
    <section className="desk" aria-label="Submit content to check">
      <div className="modes" role="tablist" aria-label="What do you want to check?">
        {tabs.map(([id, label, sub, icon]) => (
          <button key={id} role="tab" aria-selected={tab === id} className="mode" onClick={() => switchTab(id)}>
            <span className="m-title">
              {icon}
              {label}
            </span>
            <span className="m-sub">{sub}</span>
          </button>
        ))}
      </div>
      <div className="desk-body">
        {tab === 'text' && (
          <>
            <label htmlFor="claim" className="sr-only">
              Claim or article text
            </label>
            <textarea
              id="claim"
              className="field"
              placeholder="Paste a forwarded message, a headline, or a whole article…"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => (e.ctrlKey || e.metaKey) && e.key === 'Enter' && submit()}
            />
            <div className="desk-meta">
              <span>
                {words} words · {text.length} chars
              </span>
              <span className="spacer" />
              <button className="linkish" onClick={dictate}>
                {dictating ? '● Stop speaking' : '🎙 Speak instead'}
              </button>
              {text && (
                <button className="linkish" onClick={() => setText('')}>
                  Clear text
                </button>
              )}
            </div>
            {!text && (
              <div className="examples">
                <div className="eyebrow">Or try one of these</div>
                <div className="example-list">
                  {EXAMPLES.map((ex) => (
                    <button key={ex} className="example" onClick={() => setText(ex)}>
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
        {tab === 'url' && (
          <>
            <label htmlFor="url" className="sr-only">
              Article link
            </label>
            <input
              id="url"
              className="field"
              type="url"
              inputMode="url"
              placeholder="https://www.example.com/news/story"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
            <div className="desk-meta">
              <span>We read the article, pull out its claims and check each one.</span>
            </div>
          </>
        )}
        {tab === 'file' && dropzone('file')}
        {tab === 'voice' && (
          <>
            {!file && (
              <div className="rec">
                <button className={`rec-btn ${recording ? 'on' : ''}`} onClick={toggleRecord} aria-label={recording ? 'Stop recording' : 'Start recording'}>
                  {recording ? <StopIcon size={30} /> : <MicIcon size={32} />}
                </button>
                <div className="rec-time" aria-live="polite">
                  {recording ? `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}` : 'Record a claim'}
                </div>
                {!recording && <div className="desk-meta">or upload a recording below</div>}
              </div>
            )}
            {!recording && dropzone('voice')}
          </>
        )}
        {tab === 'video' && dropzone('video')}
        {err && (
          <div className="error" role="alert">
            {err}
          </div>
        )}
      </div>
      <div className="desk-foot">
        <span className="hint">We compare it with news reports, fact-checkers and official sources.</span>
        <button className="btn primary" onClick={submit} disabled={!ready}>
          Check it <Arrow />
        </button>
      </div>
    </section>
  )
}
