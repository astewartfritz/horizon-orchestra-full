from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

_log = logging.getLogger(__name__)

# Inline HTML for the STT page — a simple, clean single-page app using
# the Web Speech API for browser-based speech recognition, plus a
# file-upload fallback that hits our /api/stt/transcribe endpoint.

STT_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Orchestra — Speech to Text</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-secondary: #8b949e;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --green: #3fb950;
    --red: #f85149;
    --orange: #d29922;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }
  .topbar {
    display: flex;
    align-items: center;
    padding: 12px 20px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  .topbar h1 { font-size: 16px; font-weight: 600; margin-right: auto; }
  .topbar a {
    color: var(--accent);
    text-decoration: none;
    font-size: 13px;
  }
  .topbar a:hover { text-decoration: underline; }
  .container {
    flex: 1;
    max-width: 720px;
    width: 100%;
    margin: 0 auto;
    padding: 24px 16px;
    display: flex;
    flex-direction: column;
  }
  .record-area {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    padding: 32px 16px;
    border: 2px dashed var(--border);
    border-radius: 12px;
    background: var(--surface);
    transition: border-color 0.2s;
  }
  .record-area.listening { border-color: var(--green); }
  .record-area.error { border-color: var(--red); }
  .record-btn {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    border: 3px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font-size: 32px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
  }
  .record-btn:hover { border-color: var(--accent); background: #1c2333; }
  .record-btn.listening {
    border-color: var(--green);
    background: #0d2a1a;
    animation: pulse 1.5s infinite;
  }
  @keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(63,185,80,0.4); }
    70% { box-shadow: 0 0 0 16px rgba(63,185,80,0); }
    100% { box-shadow: 0 0 0 0 rgba(63,185,80,0); }
  }
  .status-text {
    font-size: 14px;
    color: var(--text-secondary);
    text-align: center;
  }
  .status-text.listening { color: var(--green); }
  .interim {
    font-size: 15px;
    color: var(--text-secondary);
    min-height: 1.5em;
    text-align: center;
    font-style: italic;
  }
  .result-area {
    margin-top: 20px;
    flex: 1;
    display: flex;
    flex-direction: column;
  }
  .result-area h3 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }
  .result-box {
    flex: 1;
    min-height: 120px;
    padding: 12px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 15px;
    line-height: 1.6;
    color: var(--text);
    resize: vertical;
    tab-size: 2;
  }
  .result-box:focus { outline: none; border-color: var(--accent); }
  .toolbar {
    display: flex;
    gap: 8px;
    margin-top: 12px;
    flex-wrap: wrap;
  }
  .toolbar button, .toolbar label {
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s;
  }
  .toolbar button:hover, .toolbar label:hover {
    border-color: var(--accent);
    background: #1c2333;
  }
  .toolbar .primary {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }
  .toolbar .primary:hover { background: var(--accent-hover); }
  .upload-section {
    margin-top: 24px;
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
  }
  .upload-section h3 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
  }
  .upload-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .upload-row input[type="file"] {
    flex: 1;
    font-size: 13px;
    color: var(--text-secondary);
  }
  .language-select {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font-size: 13px;
  }
  .file-status {
    margin-top: 8px;
    font-size: 13px;
    color: var(--text-secondary);
  }
  .lang-hint {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 4px;
  }
</style>
</head>
<body>

<div class="topbar">
  <h1>&#x1F399; Speech to Text</h1>
  <a href="/app">&larr; Back to Chat</a>
</div>

<div class="container">

  <!-- Browser Speech Recognition -->
  <div class="record-area" id="recordArea">
    <button class="record-btn" id="recordBtn" onclick="toggleRecording()">&#x1F3A4;</button>
    <div class="status-text" id="statusText">Click the mic to start recording</div>
    <div class="interim" id="interimText"></div>
  </div>

  <div class="result-area">
    <h3>Transcription</h3>
    <textarea class="result-box" id="resultBox" placeholder="Transcribed text will appear here..."></textarea>
    <div class="toolbar">
      <button class="primary" onclick="copyText()">&#x1F4CB; Copy</button>
      <button onclick="clearText()">&#x1F5D1; Clear</button>
      <button onclick="sendToChat()">&#x1F4AC; Send to Chat</button>
    </div>
  </div>

  <!-- File Upload -->
  <div class="upload-section">
    <h3>&#x1F4C2; Upload Audio File</h3>
    <div class="upload-row">
      <input type="file" id="audioFile" accept="audio/*">
      <select class="language-select" id="uploadLang">
        <option value="">Auto-detect</option>
        <option value="en">English</option>
        <option value="es">Spanish</option>
        <option value="fr">French</option>
        <option value="de">German</option>
        <option value="ja">Japanese</option>
        <option value="zh">Chinese</option>
      </select>
      <button onclick="uploadAudio()" class="primary">Transcribe</button>
    </div>
    <div class="file-status" id="fileStatus"></div>
  </div>

</div>

<script>
let recognition = null;
let isListening = false;
let finalTranscript = '';

function getRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.continuous = true;
  r.interimResults = true;
  r.lang = 'en-US';
  return r;
}

function toggleRecording() {
  if (isListening) { stopRecording(); return; }
  startRecording();
}

function startRecording() {
  if (!recognition) {
    recognition = getRecognition();
    if (!recognition) {
      document.getElementById('statusText').textContent = 'Speech recognition not supported in this browser. Try Chrome or Edge.';
      document.getElementById('recordArea').className = 'record-area error';
      return;
    }

    recognition.onresult = function(e) {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          finalTranscript += e.results[i][0].transcript + ' ';
        } else {
          interim += e.results[i][0].transcript;
        }
      }
      document.getElementById('resultBox').value = finalTranscript;
      document.getElementById('interimText').textContent = interim;
      // Auto-scroll result
      const box = document.getElementById('resultBox');
      box.scrollTop = box.scrollHeight;
    };

    recognition.onerror = function(e) {
      console.error('Speech error:', e.error);
      document.getElementById('statusText').textContent = 'Error: ' + e.error;
      document.getElementById('recordArea').className = 'record-area error';
      stopRecording();
    };

    recognition.onend = function() {
      if (isListening) {
        // Restart if still should be listening (continuous mode)
        try { recognition.start(); } catch(ex) {}
      } else {
        document.getElementById('statusText').textContent = 'Recording stopped';
        document.getElementById('recordArea').className = 'record-area';
        document.getElementById('recordBtn').className = 'record-btn';
        document.getElementById('interimText').textContent = '';
      }
    };
  }

  finalTranscript = document.getElementById('resultBox').value || '';
  try { recognition.start(); } catch(ex) {}
  isListening = true;
  document.getElementById('recordBtn').className = 'record-btn listening';
  document.getElementById('recordBtn').textContent = '\u23F9';
  document.getElementById('statusText').textContent = 'Listening...';
  document.getElementById('statusText').className = 'status-text listening';
  document.getElementById('recordArea').className = 'record-area listening';
}

function stopRecording() {
  isListening = false;
  if (recognition) {
    try { recognition.stop(); } catch(ex) {}
  }
  document.getElementById('recordBtn').className = 'record-btn';
  document.getElementById('recordBtn').textContent = '\uD83C\uDFA4';
  document.getElementById('statusText').className = 'status-text';
  document.getElementById('interimText').textContent = '';
}

function copyText() {
  const box = document.getElementById('resultBox');
  if (!box.value) return;
  navigator.clipboard.writeText(box.value).then(function() {
    const btn = document.querySelector('.toolbar .primary');
    const orig = btn.textContent;
    btn.textContent = '\u2713 Copied!';
    setTimeout(function() { btn.textContent = orig; }, 1500);
  });
}

function clearText() {
  finalTranscript = '';
  document.getElementById('resultBox').value = '';
}

function sendToChat() {
  const text = document.getElementById('resultBox').value;
  if (!text) return;
  // Store in sessionStorage for the chat page to pick up
  sessionStorage.setItem('orchestra_stt_text', text);
  window.location.href = '/app';
}

function uploadAudio() {
  const fileInput = document.getElementById('audioFile');
  const statusEl = document.getElementById('fileStatus');
  const lang = document.getElementById('uploadLang').value;

  if (!fileInput.files || !fileInput.files[0]) {
    statusEl.textContent = 'Please select an audio file first.';
    statusEl.style.color = 'var(--orange)';
    return;
  }

  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append('file', file);
  if (lang) formData.append('language', lang);

  statusEl.textContent = 'Uploading & transcribing...';
  statusEl.style.color = 'var(--text-secondary)';

  fetch('/api/stt/transcribe', { method: 'POST', body: formData })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) {
        statusEl.textContent = 'Error: ' + data.error;
        statusEl.style.color = 'var(--red)';
        return;
      }
      const box = document.getElementById('resultBox');
      if (box.value) box.value += '\n---\n';
      box.value += data.text;
      finalTranscript = box.value;
      statusEl.textContent = 'Transcription complete (' + (data.duration_seconds || '?') + 's audio)';
      statusEl.style.color = 'var(--green)';
    })
    .catch(function(err) {
      statusEl.textContent = 'Upload failed: ' + err.message;
      statusEl.style.color = 'var(--red)';
    });
}

// Check for existing STT text from a previous visit
(function() {
  const saved = sessionStorage.getItem('orchestra_stt_text');
  if (saved) {
    document.getElementById('resultBox').value = saved;
    sessionStorage.removeItem('orchestra_stt_text');
  }
})();
</script>
</body>
</html>"""


def register_stt_routes(app: FastAPI) -> None:

    @app.get("/stt", response_class=HTMLResponse)
    async def stt_page():
        return STT_PAGE_HTML

    @app.post("/api/stt/transcribe")
    async def transcribe_audio(
        file: UploadFile = File(...),
        language: str = Form(""),
    ):
        supported = ("audio/wav", "audio/mpeg", "audio/mp3", "audio/ogg",
                     "audio/flac", "audio/x-wav", "audio/webm", "audio/aac",
                     "audio/m4a", "")
        if file.content_type and file.content_type not in supported:
            _log.warning("Unsupported content type: %s", file.content_type)

        try:
            suffix = Path(file.filename or "audio.webm").suffix or ".webm"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name

            try:
                from orchestra.speech_provider import (
                    STTBackend, STTConfig, SpeechProvider,
                )
            except ImportError:
                os.unlink(tmp_path)
                raise HTTPException(
                    status_code=501,
                    detail="Speech provider not installed. Install with: pip install code-agent[speech]",
                )

            config = STTConfig(backend=STTBackend.WHISPER_API)
            if language:
                config.language = language

            provider = SpeechProvider()
            result = await provider.transcribe(tmp_path, config)

            os.unlink(tmp_path)
            return JSONResponse({
                "text": result.text,
                "language": result.language or language or "en",
                "duration_seconds": result.duration,
                "confidence": result.confidence,
            })

        except HTTPException:
            raise
        except Exception as exc:
            _log.exception("Transcription failed")
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
