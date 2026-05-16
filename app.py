import os
from pathlib import Path
from dotenv import load_dotenv
import requests as req_lib
from flask import Flask, request, jsonify, send_file

load_dotenv()

from agent import memory
from agent.oscar import OscarAgent

memory.init_db()

app = Flask(__name__)


def _extract_text(file_bytes: bytes, filename: str) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n\n".join(p.get_text() for p in doc)
        doc.close()
        return text[:80_000]
    except ImportError:
        pass
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        import io
        text = pdfminer_extract(io.BytesIO(file_bytes)) or ""
        return text[:80_000]
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
  <div class="lbl">Documentos cargados</div>
  <input type="file" id="file-input" accept=".pdf,.txt" style="display:none" onchange="uploadFile()">
  <div id="docs-list"></div>
</div>
<div id="main">
  <div id="header">
    <button id="menu-btn" onclick="toggleSidebar()">&#9776;</button>
    <div id="htext">
      <h2>OSCAR &mdash; Agente Docente</h2>
      <p>Especialista en educacion colombiana &middot; Matematicas &middot; STEM</p>
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

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('overlay').classList.toggle('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('overlay').classList.remove('open');
}

async function init() {
  const cfg = await fetch('/api/config').then(r=>r.json());
  if (!cfg.api_key_set) {
    const w = document.getElementById('api-warn');
    w.style.display='block';
    w.textContent='Configura GEMINI_API_KEY en el archivo .env y reinicia el servidor.';
  }
  const sessions = await fetch('/api/sessions').then(r=>r.json());
  if (sessions.length > 0) { renderSessions(sessions); await switchSession(sessions[0].id); }
  else await newSession();
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
  input.value=''; input.style.height='auto';
  addMsg('user',text);
  const thinking=addMsg('assistant','OSCAR esta pensando...');
  thinking.classList.add('thinking');
  document.getElementById('send-btn').disabled=true;
  try{
    const res=await fetch('/api/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session_id:sid,message:text})
    }).then(r=>r.json());
    thinking.remove();
    if(res.error) addMsg('assistant','Error: '+res.error);
    else{addMsg('assistant',res.text,res.saved_files||[]);refreshSessions();}
  }catch(e){
    thinking.remove();
    addMsg('assistant','Error de conexion. Verifica que el servidor este corriendo.');
  }
  document.getElementById('send-btn').disabled=false;
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
    return jsonify({"api_key_set": bool(os.getenv("GEMINI_API_KEY"))})


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
    sid = data.get("session_id")
    message = (data.get("message") or "").strip()
    if not sid or not message:
        return jsonify({"error": "Faltan session_id o message"}), 400

    msgs = memory.get_messages(sid)
    if not any(m["role"] == "user" for m in msgs):
        memory.update_session_name(sid, message[:50])

    try:
        agent = OscarAgent(sid)
        text, saved_files = agent.chat(message)
        return jsonify({"text": text, "saved_files": saved_files})
    except req_lib.exceptions.Timeout:
        return jsonify({"error": "La red es lenta. Espera unos segundos y vuelve a intentarlo."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        text = file_bytes.decode("utf-8", errors="replace")[:80_000]

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


@app.route("/api/download/<filename>")
def download(filename):
    filepath = Path("data/generados") / filename
    if not filepath.exists():
        return "Archivo no encontrado", 404
    return send_file(filepath, as_attachment=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
