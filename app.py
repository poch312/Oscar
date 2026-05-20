import os
import threading
import uuid
import time as time_lib
from pathlib import Path
from dotenv import load_dotenv
import requests as req_lib
from flask import Flask, request, jsonify, send_file

load_dotenv()

from agent import memory
from agent.oscar import OscarAgent

memory.init_db()

app = Flask(__name__)

_jobs: dict = {}
_jobs_lock = threading.Lock()
_JOB_TTL = 600


def _cleanup_jobs():
    now = time_lib.monotonic()
    expired = [jid for jid, j in _jobs.items() if now - j["created_at"] > _JOB_TTL]
    for jid in expired:
        del _jobs[jid]


def _job_worker(job_id: str, session_id: str, message: str):
    from config import Config
    provider_label = "modelo local (puede tardar 2-5 min)" if Config.PROVIDER == "ollama" else "Groq"
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["progress"] = f"Consultando {provider_label}..."
    try:
        msgs = memory.get_messages(session_id)
        if not any(m["role"] == "user" for m in msgs):
            memory.update_session_name(session_id, message[:50])
        agent = OscarAgent(session_id)
        text, saved_files = agent.chat(message)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = {"text": text, "saved_files": saved_files}
    except req_lib.exceptions.Timeout:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = "La red es lenta. Espera unos segundos y vuelve a intentarlo."
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)


def _extract_text(file_bytes: bytes, filename: str) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n\n".join(p.get_text() for p in doc)
        doc.close()
        return text[:40_000]
    except ImportError:
        pass
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        import io
        text = pdfminer_extract(io.BytesIO(file_bytes)) or ""
        return text[:40_000]
    except Exception as e:
        return f"[No se pudo extraer texto de '{filename}': {e}]"


HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OSCAR</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0e1117;color:#fafafa;height:100vh;display:flex;overflow:hidden}
#overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10}
#overlay.open{display:block}
#sidebar{width:260px;min-width:260px;background:#1a1f2e;border-right:1px solid #2d3748;display:flex;flex-direction:column;padding:14px;gap:6px;overflow-y:auto;z-index:20;transition:transform .25s ease}
#sidebar h1{font-size:18px;color:#667eea;margin-bottom:2px}
#sidebar .sub{font-size:10px;color:#718096;margin-bottom:10px;line-height:1.4}
.btn-new{background:#667eea;color:#fff;width:100%;text-align:left;padding:9px 12px;border:none;border-radius:8px;cursor:pointer;font-size:13px}
.btn-new:hover{background:#5a67d8}
.divider{border:none;border-top:1px solid #2d3748;margin:6px 0}
.lbl{font-size:10px;color:#718096;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px}
.sess{display:flex;align-items:center;gap:4px;padding:7px 8px;border-radius:6px;cursor:pointer;font-size:12px;color:#a0aec0}
.sess:hover,.sess.active{background:#2d3748;color:#fafafa}
.sess .sname{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sess .del{color:#fc8181;font-size:13px;flex-shrink:0;opacity:.6}
.doc-item{font-size:11px;color:#718096;padding:3px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
#header{padding:10px 14px;background:#1a1f2e;border-bottom:1px solid #2d3748;flex-shrink:0;display:flex;align-items:center;gap:10px}
#menu-btn{background:none;border:none;color:#a0aec0;font-size:22px;cursor:pointer;padding:2px 4px;display:none;flex-shrink:0;line-height:1}
#cfg-btn{background:none;border:none;color:#a0aec0;font-size:18px;cursor:pointer;padding:2px 4px;flex-shrink:0;line-height:1}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:#1a1f2e;border:1px solid #2d3748;border-radius:12px;padding:20px;width:90%;max-width:440px;max-height:90vh;overflow-y:auto}
.modal h3{color:#667eea;margin-bottom:14px;font-size:15px}
.modal label{display:block;font-size:11px;color:#718096;margin-bottom:3px;margin-top:10px}
.modal input{width:100%;background:#2d3748;border:1px solid #4a5568;border-radius:6px;color:#fafafa;padding:8px 10px;font-size:13px}
.modal .save-btn{margin-top:16px;background:#667eea;color:#fff;border:none;border-radius:8px;padding:9px 18px;cursor:pointer;font-size:13px;width:100%}
#htext{flex:1;min-width:0}
#htext h2{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#htext p{font-size:10px;color:#718096;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#api-warn{background:#744210;color:#fefcbf;padding:8px 14px;font-size:12px;text-align:center;flex-shrink:0;display:none}
#messages{flex:1;overflow-y:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:85%;padding:10px 14px;border-radius:14px;font-size:14px;line-height:1.6;overflow-wrap:break-word}
.msg.user{background:#667eea;color:#fff;align-self:flex-end;border-bottom-right-radius:3px}
.msg.assistant{background:#1a1f2e;color:#e2e8f0;align-self:flex-start;border:1px solid #2d3748;border-bottom-left-radius:3px}
.msg.thinking{color:#718096;font-style:italic}
.dl-btn{display:inline-block;margin-top:8px;padding:6px 12px;background:#38a169;color:#fff;border-radius:6px;font-size:12px;text-decoration:none}
#input-area{padding:10px 12px;background:#1a1f2e;border-top:1px solid #2d3748;display:flex;gap:8px;align-items:flex-end;flex-shrink:0}
#user-input{flex:1;background:#2d3748;border:1px solid #4a5568;border-radius:10px;color:#fafafa;padding:10px 13px;font-size:15px;resize:none;max-height:120px;min-height:46px;font-family:inherit;min-width:0}
#user-input:focus{outline:none;border-color:#667eea}
#send-btn{background:#667eea;color:#fff;border:none;border-radius:10px;padding:10px 16px;cursor:pointer;font-size:15px;height:46px;flex-shrink:0}
#send-btn:disabled{background:#4a5568;cursor:not-allowed}
#upload-label{cursor:pointer;color:#667eea;font-size:24px;padding:8px 2px;line-height:1;flex-shrink:0}
@media(max-width:800px){
  #sidebar{position:fixed;top:0;left:0;height:100%;transform:translateX(-100%)}
  #sidebar.open{transform:translateX(0)}
  #menu-btn{display:block}
}
</style>
</head>
<body>
<div id="overlay" onclick="closeSidebar()"></div>
<div id="sidebar">
  <h1>&#128218; OSCAR</h1>
  <p class="sub">Orientador de Saberes Curriculares,<br>Academicos y de Recursos</p>
  <button class="btn-new" onclick="newSession()">+ Nueva conversacion</button>
  <hr class="divider">
  <div class="lbl">Conversaciones</div>
  <div id="session-list"></div>
  <hr class="divider">
  <div class="lbl">Base de Conocimiento</div>
  <input type="file" id="kb-file-input" accept=".pdf,.txt" style="display:none" onchange="uploadToKB()">
  <label for="kb-file-input" style="cursor:pointer;color:#667eea;font-size:11px;display:block;padding:5px 8px;border-radius:6px;border:1px dashed #4a5568;text-align:center;margin-bottom:4px">+ Agregar documento permanente</label>
  <div id="kb-list"></div>
  <hr class="divider">
  <div class="lbl">Documentos de sesion</div>
  <input type="file" id="file-input" accept=".pdf,.txt" style="display:none" onchange="uploadFile()">
  <div id="docs-list"></div>
</div>
<div id="main">
  <div id="header">
    <button id="menu-btn" onclick="toggleSidebar()">&#9776;</button>
    <div id="htext">
      <h2>OSCAR &mdash; Agente Docente</h2>
      <p id="provider-label">Especialista en educacion colombiana &middot; Matematicas &middot; STEM</p>
    </div>
    <button id="cfg-btn" onclick="openCfg()" title="Configurar institucion">&#9881;</button>
  </div>
  <div class="modal-overlay" id="cfg-modal" onclick="closeCfgOutside(event)">
    <div class="modal">
      <h3>&#127eb; Contexto Institucional</h3>
      <label>Nombre del docente</label>
      <input id="cf-docente" placeholder="Prof. Juan Perez">
      <label>Institucion educativa</label>
      <input id="cf-inst" placeholder="IE Nombre del Colegio">
      <label>Municipio</label>
      <input id="cf-municipio" placeholder="Ciudad, Departamento">
      <label>Modelo pedagogico</label>
      <input id="cf-modelo" placeholder="Constructivista, ABP, etc.">
      <label>Metodologia principal</label>
      <input id="cf-met" placeholder="ABP, Aula invertida, Maker...">
      <label>Grados a cargo</label>
      <input id="cf-grados" placeholder="8, 9, 10, 11">
      <button class="save-btn" onclick="saveCfg()">Guardar configuracion</button>
    </div>
  </div>
  <div id="api-warn"></div>
  <div id="messages"></div>
  <div id="input-area">
    <label id="upload-label" for="file-input" title="Cargar PDF o TXT">&#128206;</label>
    <textarea id="user-input" placeholder="Escribe tu consulta aqui..." rows="1"
      onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
    <button id="send-btn" onclick="sendMessage()">Enviar</button>
  </div>
</div>
<script>
let sid = null;
let _currentPollTimer = null;

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('overlay').classList.toggle('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('overlay').classList.remove('open');
}

async function openCfg(){
  const ctx=await fetch('/api/institutional').then(r=>r.json());
  document.getElementById('cf-docente').value=ctx.nombre_docente||'';
  document.getElementById('cf-inst').value=ctx.nombre_institucion||'';
  document.getElementById('cf-municipio').value=ctx.municipio||'';
  document.getElementById('cf-modelo').value=ctx.modelo_pedagogico||'';
  document.getElementById('cf-met').value=ctx.metodologia||'';
  document.getElementById('cf-grados').value=ctx.grados||'';
  document.getElementById('cfg-modal').classList.add('open');
}
function closeCfgOutside(e){
  if(e.target===document.getElementById('cfg-modal'))
    document.getElementById('cfg-modal').classList.remove('open');
}
async function saveCfg(){
  await fetch('/api/institutional',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      nombre_docente:document.getElementById('cf-docente').value,
      nombre_institucion:document.getElementById('cf-inst').value,
      municipio:document.getElementById('cf-municipio').value,
      modelo_pedagogico:document.getElementById('cf-modelo').value,
      metodologia:document.getElementById('cf-met').value,
      grados:document.getElementById('cf-grados').value,
    })
  });
  document.getElementById('cfg-modal').classList.remove('open');
}

async function loadKB(){
  const docs=await fetch('/api/kb').then(r=>r.json());
  const list=document.getElementById('kb-list');
  list.innerHTML='';
  for(const d of docs){
    const el=document.createElement('div');
    el.className='doc-item';
    el.style.cssText='display:flex;align-items:center;gap:4px';
    el.innerHTML='<span style="flex:1;overflow:hidden;text-overflow:ellipsis">&#128218; '+d.filename+'</span>'
      +'<span style="color:#fc8181;cursor:pointer;font-size:13px;flex-shrink:0" onclick="deleteFromKB(\''+encodeURIComponent(d.filename)+'\')">x</span>';
    list.appendChild(el);
  }
}

async function uploadToKB(){
  const input=document.getElementById('kb-file-input');
  const file=input.files[0];
  if(!file)return;
  const placeholder=document.createElement('div');
  placeholder.className='doc-item';
  placeholder.textContent='Indexando '+file.name+'...';
  document.getElementById('kb-list').prepend(placeholder);
  const fd=new FormData();
  fd.append('file',file);
  try{
    const res=await fetch('/api/kb/upload',{method:'POST',body:fd}).then(r=>r.json());
    if(res.error) placeholder.textContent='Error: '+res.error;
    else await loadKB();
  }catch(e){placeholder.textContent='Error al subir.';}
  input.value='';
}

async function deleteFromKB(filename){
  await fetch('/api/kb/'+filename,{method:'DELETE'});
  await loadKB();
}

async function init() {
  const cfg = await fetch('/api/config').then(r=>r.json());
  if (!cfg.api_key_set) {
    const w = document.getElementById('api-warn');
    w.style.display='block';
    w.textContent='Configura GROQ_API_KEY en el archivo .env y reinicia el servidor.';
  }
  document.getElementById('provider-label').textContent =
    'Proveedor: ' + (cfg.provider||'groq').toUpperCase() + ' · ' + (cfg.model||'');
  const sessions = await fetch('/api/sessions').then(r=>r.json());
  if (sessions.length > 0) { renderSessions(sessions); await switchSession(sessions[0].id); }
  else await newSession();
  await loadKB();
}

async function newSession() {
  const res = await fetch('/api/sessions',{method:'POST'}).then(r=>r.json());
  sid = res.id; clearMsgs(); addWelcome(); await refreshSessions();
}

async function refreshSessions() {
  const sessions = await fetch('/api/sessions').then(r=>r.json());
  renderSessions(sessions);
}

function renderSessions(sessions) {
  const list = document.getElementById('session-list');
  list.innerHTML='';
  for (const s of sessions) {
    const el = document.createElement('div');
    el.className='sess'+(s.id===sid?' active':'');
    el.innerHTML='<span class="sname">'+s.name+'</span>'
      +'<span class="del" onclick="delSession(\''+s.id+'\',event)">x</span>';
    el.onclick=()=>{switchSession(s.id);closeSidebar();}
    list.appendChild(el);
  }
}

async function switchSession(id) {
  sid=id; clearMsgs();
  const msgs=await fetch('/api/messages/'+id).then(r=>r.json());
  if(msgs.length===0) addWelcome();
  else for(const m of msgs) addMsg(m.role,m.text);
  await refreshSessions();
}

async function delSession(id,e) {
  e.stopPropagation();
  await fetch('/api/sessions/'+id,{method:'DELETE'});
  if(id===sid) await newSession(); else await refreshSessions();
}

function clearMsgs(){document.getElementById('messages').innerHTML='';}

function addWelcome(){
  addMsg('assistant','Hola! Soy OSCAR. Estoy aqui para apoyarte con planeaciones, mallas curriculares, guias, rubricas, evaluaciones, proyectos STEM y toda la documentacion docente que necesites. Con que empezamos?');
}

function addMsg(role,text,downloads=[]){
  const c=document.getElementById('messages');
  const d=document.createElement('div');
  d.className='msg '+role;
  d.textContent=text;
  for(const f of downloads){
    const a=document.createElement('a');
    a.href='/api/download/'+f.filename;
    a.className='dl-btn';
    a.textContent='Descargar: '+f.filename;
    a.download=f.filename;
    d.appendChild(document.createElement('br'));
    d.appendChild(a);
  }
  c.appendChild(d);
  c.scrollTop=c.scrollHeight;
  return d;
}

async function sendMessage(){
  const input=document.getElementById('user-input');
  const text=input.value.trim();
  if(!text||!sid)return;
  const btn=document.getElementById('send-btn');
  if(btn.disabled)return;
  input.value=''; input.style.height='auto';
  addMsg('user',text);
  const thinking=addMsg('assistant','OSCAR esta pensando...');
  thinking.classList.add('thinking');
  btn.disabled=true;
  if(_currentPollTimer){clearTimeout(_currentPollTimer);_currentPollTimer=null;}
  try{
    const res=await fetch('/api/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session_id:sid,message:text})
    });
    if(!res.ok){
      const err=await res.json().catch(()=>({error:'Error desconocido'}));
      thinking.remove();
      addMsg('assistant','Error: '+(err.error||res.status));
      btn.disabled=false;
      return;
    }
    const data=await res.json();
    _pollJob(data.job_id,thinking,btn,Date.now(),0);
  }catch(e){
    thinking.remove();
    addMsg('assistant','Error de conexion. Verifica que el servidor este corriendo.');
    btn.disabled=false;
  }
}

function _pollJob(job_id,thinkingEl,btn,startTime,errCount){
  const POLL=2000,MAX_WAIT=660000,MAX_ERR=5;
  _currentPollTimer=setTimeout(async()=>{
    if(Date.now()-startTime>MAX_WAIT){
      thinkingEl.remove();
      addMsg('assistant','Tiempo de espera agotado (11 min). El modelo local es muy lento para esta consulta — intenta una pregunta más corta.');
      btn.disabled=false; return;
    }
    try{
      const res=await fetch('/api/job/'+job_id);
      const data=await res.json();
      if(data.status==='done'){
        thinkingEl.remove();
        addMsg('assistant',data.text,data.saved_files||[]);
        refreshSessions(); btn.disabled=false; _currentPollTimer=null; return;
      }
      if(data.status==='error'||data.status==='expired'){
        thinkingEl.remove();
        addMsg('assistant','Error: '+(data.error||'Resultado no disponible'));
        btn.disabled=false; _currentPollTimer=null; return;
      }
      if(data.progress) thinkingEl.textContent='OSCAR esta pensando... ('+data.progress+')';
      _pollJob(job_id,thinkingEl,btn,startTime,0);
    }catch(e){
      if(errCount+1>=MAX_ERR){
        thinkingEl.remove();
        addMsg('assistant','Se perdio la conexion. Refresca la pagina cuando se recupere.');
        btn.disabled=false; return;
      }
      _pollJob(job_id,thinkingEl,btn,startTime,errCount+1);
    }
  },POLL);
}

async function uploadFile(){
  const input=document.getElementById('file-input');
  const file=input.files[0];
  if(!file)return;
  addMsg('user','Cargando: '+file.name+'...');
  const thinking=addMsg('assistant','Analizando '+file.name+'...');
  thinking.classList.add('thinking');
  const fd=new FormData();
  fd.append('session_id',sid);
  fd.append('file',file);
  try{
    const res=await fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json());
    thinking.remove();
    if(res.error) addMsg('assistant','Error: '+res.error);
    else{
      addMsg('assistant',res.response);
      const dl=document.getElementById('docs-list');
      const el=document.createElement('div');
      el.className='doc-item'; el.textContent='📄 '+file.name;
      dl.appendChild(el);
    }
  }catch(e){thinking.remove();addMsg('assistant','Error al cargar el documento.');}
  input.value='';
}

function handleKey(e){
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}
}
function autoResize(el){
  el.style.height='auto';
  el.style.height=Math.min(el.scrollHeight,120)+'px';
}
init();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return HTML


@app.route("/api/config")
def config():
    from config import Config
    key_set = bool(Config.GROQ_API_KEY) if Config.PROVIDER == "groq" else True
    return jsonify({
        "api_key_set": key_set,
        "provider": Config.PROVIDER,
        "model": Config.GROQ_MODEL if Config.PROVIDER == "groq" else Config.OLLAMA_MODEL,
    })


@app.route("/api/institutional", methods=["GET"])
def get_institutional():
    return jsonify(memory.get_institutional_context())


@app.route("/api/institutional", methods=["POST"])
def set_institutional():
    data = request.get_json() or {}
    memory.set_institutional_context(data)
    return jsonify({"ok": True})


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    return jsonify(memory.get_sessions())


@app.route("/api/sessions", methods=["POST"])
def new_session():
    sid = memory.create_session()
    return jsonify({"id": sid, "name": "Nueva conversacion"})


@app.route("/api/sessions/<sid>", methods=["DELETE"])
def delete_session(sid):
    memory.delete_session(sid)
    return jsonify({"ok": True})


@app.route("/api/messages/<sid>")
def get_messages(sid):
    msgs = memory.get_messages(sid)
    result = []
    for m in msgs:
        if m["role"] not in ("user", "assistant"):
            continue
        content = m["content"]
        if isinstance(content, list):
            text = "\n".join(
                b["text"] for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content)
        if text.strip():
            result.append({"role": m["role"], "text": text})
    return jsonify(result)


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    session_id = data.get("session_id")
    message = (data.get("message") or "").strip()
    if not session_id or not message:
        return jsonify({"error": "Faltan session_id o message"}), 400
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _cleanup_jobs()
        _jobs[job_id] = {
            "status": "pending",
            "result": None,
            "error": None,
            "created_at": time_lib.monotonic(),
            "session_id": session_id,
            "progress": "Iniciando...",
        }
    t = threading.Thread(target=_job_worker, args=(job_id, session_id, message), daemon=True)
    t.start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/job/<job_id>")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return jsonify({"status": "expired", "error": "Resultado no disponible. Reintenta."}), 404
    if job["status"] == "done":
        with _jobs_lock:
            _jobs.pop(job_id, None)
        return jsonify({"status": "done", "text": job["result"]["text"], "saved_files": job["result"]["saved_files"]})
    if job["status"] == "error":
        with _jobs_lock:
            _jobs.pop(job_id, None)
        return jsonify({"status": "error", "error": job["error"]})
    return jsonify({"status": job["status"], "progress": job["progress"]})


@app.route("/api/upload", methods=["POST"])
def upload():
    sid = request.form.get("session_id")
    file = request.files.get("file")
    if not sid or not file:
        return jsonify({"error": "Faltan datos"}), 400

    filename = file.filename
    if memory.document_exists(sid, filename):
        return jsonify({"ok": True, "response": f"'{filename}' ya estaba cargado."})

    file_bytes = file.read()
    if filename.lower().endswith(".pdf"):
        text = _extract_text(file_bytes, filename)
    else:
        text = file_bytes.decode("utf-8", errors="replace")[:40_000]

    memory.add_document(sid, filename, text)
    context_msg = (
        f"El docente ha cargado el documento '{filename}'.\n\n"
        f"Contenido:\n\n{text}\n\n"
        "Analiza este documento y confirma que lo procesaste correctamente."
    )
    try:
        agent = OscarAgent(sid)
        response_text, _ = agent.process_upload(context_msg)
        return jsonify({"ok": True, "response": response_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/kb")
def list_kb():
    return jsonify(memory.list_kb_documents())


@app.route("/api/kb/upload", methods=["POST"])
def upload_kb():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No se recibió archivo"}), 400
    filename = file.filename
    file_bytes = file.read()
    if filename.lower().endswith(".pdf"):
        text = _extract_text(file_bytes, filename)
    else:
        text = file_bytes.decode("utf-8", errors="replace")[:200_000]
    chunks = memory.add_kb_document(filename, text)
    return jsonify({"ok": True, "filename": filename, "chunks": chunks})


@app.route("/api/kb/<path:filename>", methods=["DELETE"])
def delete_kb(filename):
    memory.delete_kb_document(filename)
    return jsonify({"ok": True})


@app.route("/api/download/<filename>")
def download(filename):
    filepath = Path("data/generados") / filename
    if not filepath.exists():
        return "Archivo no encontrado", 404
    return send_file(filepath, as_attachment=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
