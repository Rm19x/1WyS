import os
import re
import socket
import platform
import hashlib
import mimetypes
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit, join_room, disconnect

# =========================================================
# 1WyS By Mr.Rm19 - LAN Chat, File Vault & Screen Grid Host
# =========================================================

APP_NAME = "1WyS By Mr.Rm19"
APP_VERSION = "v1.1.0-mobile"

def detect_runtime_mode():
    is_termux = bool(os.environ.get("TERMUX_VERSION")) or os.path.exists("/data/data/com.termux/files/usr")
    mode = "TERMUX_HOST" if is_termux else "PC_HOST"
    base_dir = os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(base_dir, "uploads_1wys")
    os.makedirs(upload_dir, exist_ok=True)
    port = int(os.environ.get("PORT_1WYS", "5050"))
    return mode, base_dir, upload_dir, port

def get_local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    if not ips:
        ips.add("127.0.0.1")
    return sorted(ips)

RUNTIME_MODE, BASE_DIR, UPLOAD_DIR, SERVER_PORT = detect_runtime_mode()
LOCAL_IPS = get_local_ips()

app = Flask(__name__)
app.config["SECRET_KEY"] = "1wys-mrrm19-secret-key"
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet", max_http_buffer_size=15 * 1024 * 1024)

ROOMS = ["Umum", "File & Dokumen", "Pantau Layar"]
MESSAGES = {r: [] for r in ROOMS}
DM_MESSAGES = {}
PINNED = {r: f"Selamat datang di {APP_NAME} ({RUNTIME_MODE})" for r in ROOMS}

DEVICES = {}
ALIAS_BY_IP = {}
KICKED_IPS = set()
ACTIVE_SHARES = {}

def now_str():
    return datetime.now().strftime("%H:%M:%S")

def dm_key(a, b):
    return "|".join(sorted([a, b]))

def sanitize_filename(filename):
    base = os.path.basename(filename or "file.bin")
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return clean[:120] or "file.bin"

def make_msg_id():
    raw = f"{datetime.now().timestamp()}-{os.urandom(6).hex()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]

def serialize_devices():
    out = []
    for sid, d in DEVICES.items():
        out.append({
            "sid": sid,
            "ip": d["ip"],
            "name": d["name"],
            "alias": d["alias"],
            "status_tag": d["status_tag"],
            "ua_short": d["ua_short"],
            "online_at": d["online_at"],
            "sharing": sid in ACTIVE_SHARES,
            "fps": ACTIVE_SHARES[sid]["fps"] if sid in ACTIVE_SHARES else 0
        })
    return out

def broadcast_presence():
    socketio.emit("presence_update", {
        "devices": serialize_devices(),
        "shares": list(ACTIVE_SHARES.values()),
        "rooms": ROOMS
    })

STARTUP_NOTICE = {
    "id": make_msg_id(),
    "sender": "SYSTEM",
    "ip": LOCAL_IPS[0],
    "room": "Umum",
    "text": f"[{APP_NAME}] Host aktif dalam mode {RUNTIME_MODE} di IP {', '.join(LOCAL_IPS)}:{SERVER_PORT}",
    "time": now_str(),
    "reply_to": None,
    "reactions": {},
    "edited": False,
    "deleted": False,
    "attachments": [],
    "is_system": True
}
MESSAGES["Umum"].append(STARTUP_NOTICE)

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="id" data-theme="whatsapp">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>{{ app_name }} - LAN Hub</title>
  <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  <style>
    :root {
      --bg: #0b141a;
      --panel: #111b21;
      --panel-2: #202c33;
      --bubble-in: #202c33;
      --bubble-out: #005c4b;
      --accent: #00a884;
      --text: #e9edef;
      --muted: #8696a0;
      --border: #2a3942;
      --danger: #ef4444;
      --font-size: 14px;
    }
    [data-theme="light"] {
      --bg: #efeae2;
      --panel: #f0f2f5;
      --panel-2: #ffffff;
      --bubble-in: #ffffff;
      --bubble-out: #d9fdd3;
      --accent: #008069;
      --text: #111b21;
      --muted: #54656f;
      --border: #d1d7db;
      --danger: #dc2626;
    }
    [data-theme="matrix"] {
      --bg: #030a05;
      --panel: #07130a;
      --panel-2: #0d1f12;
      --bubble-in: #0d1f12;
      --bubble-out: #11331a;
      --accent: #00ff66;
      --text: #b7ffcf;
      --muted: #4b9e68;
      --border: #173a20;
      --danger: #ff4d4d;
    }
    * { box-sizing: border-box; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
    html, body {
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--text);
      font-size: var(--font-size);
      height: 100dvh;
      width: 100%;
      overflow: hidden;
    }
    .app-shell {
      display: flex;
      flex-direction: column;
      height: 100dvh;
      width: 100%;
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 8px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-shrink: 0;
    }
    .brand-wrap { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .brand { font-weight: 700; color: var(--accent); white-space: nowrap; font-size: 15px; }
    .badge {
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 999px;
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--muted);
      white-space: nowrap;
    }
    .desktop-controls { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .mobile-header-btns { display: none; align-items: center; gap: 6px; }

    input, select, button {
      background: var(--panel-2);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 6px 9px;
      font-size: 12px;
    }
    button { cursor: pointer; font-weight: 600; }
    button.primary { background: var(--accent); color: #06100c; border: none; }
    button.danger { background: var(--danger); color: #fff; border: none; }

    /* Mobile Tab Bar (hanya muncul di HP) */
    .mobile-tabs {
      display: none;
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      grid-template-columns: 1fr 1fr 1fr;
      flex-shrink: 0;
    }
    .mobile-tab-btn {
      border: none;
      border-radius: 0;
      background: transparent;
      color: var(--muted);
      padding: 9px 6px;
      font-size: 12px;
      font-weight: 700;
      border-bottom: 2px solid transparent;
    }
    .mobile-tab-btn.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
      background: rgba(0, 168, 132, 0.06);
    }

    /* Desktop 3-Column Grid */
    .main-grid {
      flex: 1;
      display: grid;
      grid-template-columns: 265px 1fr 340px;
      min-height: 0;
      overflow: hidden;
    }
    .pane {
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    .sidebar, .monitor-col {
      background: var(--panel);
      padding: 10px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .sidebar { border-right: 1px solid var(--border); }
    .monitor-col { border-left: 1px solid var(--border); }

    .section-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: var(--muted);
      font-weight: 700;
      margin-bottom: 6px;
    }
    .room-btn {
      width: 100%;
      text-align: left;
      padding: 8px 10px;
      border-radius: 8px;
      background: transparent;
      border: 1px solid transparent;
      color: var(--text);
      margin-bottom: 4px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .room-btn.active { background: var(--panel-2); border-color: var(--accent); color: var(--accent); }

    .dev-card {
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 9px;
      font-size: 12px;
      display: flex;
      flex-direction: column;
      gap: 5px;
    }
    .dev-top { display: flex; justify-content: space-between; align-items: center; gap: 6px; }

    .chat-col { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--bg); }
    .pin-bar {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 6px 12px;
      font-size: 12px;
      color: var(--accent);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .pin-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .messages {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      -webkit-overflow-scrolling: touch;
    }
    .bubble {
      max-width: 82%;
      padding: 8px 11px;
      border-radius: 12px;
      background: var(--bubble-in);
      border: 1px solid var(--border);
      align-self: flex-start;
      word-break: break-word;
    }
    .bubble.mine { align-self: flex-end; background: var(--bubble-out); }
    .bubble.sys { align-self: center; max-width: 94%; background: var(--panel); font-size: 12px; color: var(--muted); text-align: center; }
    .meta { font-size: 11px; color: var(--muted); display: flex; justify-content: space-between; gap: 8px; margin-bottom: 3px; }
    .quote {
      border-left: 3px solid var(--accent);
      background: rgba(0,0,0,.18);
      padding: 4px 7px;
      border-radius: 5px;
      font-size: 11px;
      margin-bottom: 5px;
      color: var(--muted);
    }
    .msg-actions { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
    .msg-actions button { padding: 3px 7px; font-size: 11px; }
    .reactions { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; }
    .rx-chip { font-size: 11px; padding: 2px 7px; border-radius: 999px; background: var(--panel); border: 1px solid var(--border); cursor: pointer; }

    .reply-banner {
      background: var(--panel);
      border-top: 1px solid var(--border);
      padding: 6px 12px;
      font-size: 12px;
      display: none;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }

    .composer {
      background: var(--panel);
      border-top: 1px solid var(--border);
      padding: 8px 10px;
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }
    .file-btn-label {
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 9px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    .composer input[type="text"] {
      flex: 1;
      min-width: 0;
      padding: 9px 10px;
      font-size: 14px;
    }
    .send-btn { padding: 9px 13px; white-space: nowrap; }

    .grid-stage {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px;
    }
    .stream-box {
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 6px;
      font-size: 11px;
    }
    .stream-box img { width: 100%; border-radius: 6px; display: block; margin-top: 4px; background: #000; }
    .preview-box {
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px;
      font-size: 12px;
      max-height: 200px;
      overflow: auto;
      white-space: pre-wrap;
    }
    a.smart-link { color: var(--accent); text-decoration: underline; }
    code.inline-code { background: rgba(0,0,0,.25); padding: 1px 4px; border-radius: 4px; }

    /* Modal Profil di HP */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.65);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 14px;
      z-index: 99;
    }
    .modal-backdrop.open { display: flex; }
    .modal-card {
      width: 100%;
      max-width: 380px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .modal-row { display: flex; flex-direction: column; gap: 4px; }
    .modal-row label { font-size: 11px; color: var(--muted); font-weight: 700; }
    .modal-row input, .modal-row select { width: 100%; padding: 8px 10px; font-size: 13px; }

    footer {
      background: var(--panel);
      border-top: 1px solid var(--border);
      padding: 5px 12px;
      font-size: 11px;
      color: var(--muted);
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 6px;
      flex-shrink: 0;
    }

    /* ==================== MOBILE VIEWPORT (<= 900px) ==================== */
    @media (max-width: 900px) {
      .desktop-controls { display: none; }
      .mobile-header-btns { display: flex; }
      .mobile-tabs { display: grid; }
      .badge.host-ip { display: none; }

      .main-grid {
        display: block;
        position: relative;
        flex: 1;
        min-height: 0;
      }
      .pane {
        display: none;
        width: 100%;
        height: 100%;
        border: none !important;
      }
      .pane.mobile-active {
        display: flex;
      }
      .bubble { max-width: 88%; }
      footer { display: none; }
    }
  </style>
</head>
<body>
<div class="app-shell">
  <header>
    <div class="brand-wrap">
      <span class="brand">{{ app_name }}</span>
      <span class="badge">{{ runtime_mode }}</span>
      <span class="badge host-ip">IP: {{ local_ips | join(', ') }}:{{ server_port }}</span>
    </div>

    <!-- Kontrol Desktop -->
    <div class="desktop-controls">
      <input id="nickInput" type="text" placeholder="Nama HP / Pengguna" style="width:125px" />
      <input id="statusTagInput" type="text" placeholder="Status" style="width:105px" />
      <button onclick="saveProfileFromDesktop()">Simpan</button>
      <select id="themeSelect" onchange="changeTheme(this.value)">
        <option value="whatsapp">Tema: WA Dark</option>
        <option value="light">Tema: Terang</option>
        <option value="matrix">Tema: Matrix</option>
      </select>
      <select id="fontSelect" onchange="changeFont(this.value)">
        <option value="13px">Huruf: Kecil</option>
        <option value="14px" selected>Huruf: Sedang</option>
        <option value="16px">Huruf: Besar</option>
      </select>
    </div>

    <!-- Tombol Ringkas di HP -->
    <div class="mobile-header-btns">
      <button onclick="openProfileModal()">Profil & Tema</button>
    </div>
  </header>

  <!-- Tab Navigasi Khusus HP -->
  <nav class="mobile-tabs">
    <button id="mTabChat" class="mobile-tab-btn active" onclick="switchMobileTab('chat')">Chat</button>
    <button id="mTabDevices" class="mobile-tab-btn" onclick="switchMobileTab('devices')">Room & HP (<span id="mDevCount">0</span>)</button>
    <button id="mTabMonitor" class="mobile-tab-btn" onclick="switchMobileTab('monitor')">Layar & File</button>
  </nav>

  <div class="main-grid">
    <!-- Pane 1: Room, DM & Presence Radar -->
    <aside id="paneDevices" class="pane sidebar">
      <div>
        <div class="section-title">Ruang Obrolan</div>
        <div id="roomsList"></div>
        <div style="display:flex;gap:6px;margin-top:6px;">
          <input id="newRoomInput" type="text" placeholder="Nama room baru..." style="flex:1" />
          <button onclick="createRoom()">+ Room</button>
        </div>
      </div>

      <div>
        <div class="section-title">Perangkat Terhubung (<span id="devCount">0</span>)</div>
        <div id="devicesList" style="display:flex;flex-direction:column;gap:7px;"></div>
      </div>
    </aside>

    <!-- Pane 2: Chat Ala WhatsApp -->
    <section id="paneChat" class="pane chat-col mobile-active">
      <div class="pin-bar">
        <span id="pinText" class="pin-text">Memuat...</span>
        <button onclick="setPinFromPrompt()">Pin</button>
      </div>
      <div id="messagesList" class="messages"></div>
      <div id="replyBanner" class="reply-banner">
        <span id="replyText" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
        <button onclick="cancelReply()">Batal</button>
      </div>
      <div class="composer">
        <input id="fileInput" type="file" multiple style="display:none" onchange="handleFilePicked()" />
        <label for="fileInput" class="file-btn-label" id="fileLabel">File</label>
        <button id="uploadBtn" onclick="uploadFiles()" style="display:none;padding:8px 9px;">Kirim File</button>
        <input id="msgInput" type="text" placeholder="Ketik pesan atau /help..." onkeydown="handleKey(event)" />
        <button class="primary send-btn" onclick="sendMessage()">Kirim</button>
      </div>
    </section>

    <!-- Pane 3: Screen Share Grid & Document Preview -->
    <aside id="paneMonitor" class="pane monitor-col">
      <div>
        <div class="section-title">Screen Share & Multi-Device Grid</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;">
          <button id="shareBtn" class="primary" onclick="toggleScreenShare()">Mulai Share Layar</button>
          <select id="fpsSelect" title="Batas FPS">
            <option value="3">3 FPS (Hemat)</option>
            <option value="5" selected>5 FPS (Seimbang)</option>
            <option value="10">10 FPS (Halus)</option>
          </select>
        </div>
        <div id="screenGrid" class="grid-stage"></div>
        <video id="localVideo" autoplay muted playsinline style="display:none;"></video>
        <canvas id="captureCanvas" style="display:none;"></canvas>
      </div>

      <div>
        <div class="section-title">Preview Dokumen / Teks</div>
        <div id="docPreview" class="preview-box">Klik "Preview" pada file teks/dokumen di chat untuk melihat isinya di sini.</div>
      </div>
    </aside>
  </div>

  <footer>
    <span>{{ app_name }} — {{ app_version }}</span>
    <span>Host: {{ runtime_mode }} | Tips: ketik <code>/help</code> di kolom chat</span>
  </footer>
</div>

<!-- Modal Profil, Status, Tema & Ukuran Huruf (Praktis di HP) -->
<div id="profileModal" class="modal-backdrop" onclick="if(event.target===this)closeProfileModal()">
  <div class="modal-card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong>Pengaturan Profil & Tampilan</strong>
      <button onclick="closeProfileModal()">Tutup</button>
    </div>
    <div class="modal-row">
      <label>Nama Perangkat / Pengguna</label>
      <input id="mNickInput" type="text" />
    </div>
    <div class="modal-row">
      <label>Status Tag</label>
      <input id="mStatusInput" type="text" />
    </div>
    <div class="modal-row">
      <label>Tema Tampilan</label>
      <select id="mThemeSelect" onchange="changeTheme(this.value)">
        <option value="whatsapp">Tema: WA Dark</option>
        <option value="light">Tema: Terang</option>
        <option value="matrix">Tema: Matrix</option>
      </select>
    </div>
    <div class="modal-row">
      <label>Ukuran Huruf</label>
      <select id="mFontSelect" onchange="changeFont(this.value)">
        <option value="13px">Huruf: Kecil</option>
        <option value="14px">Huruf: Sedang</option>
        <option value="16px">Huruf: Besar</option>
      </select>
    </div>
    <button class="primary" onclick="saveProfileFromModal()">Simpan Perubahan</button>
  </div>
</div>

<script>
  const socket = io();
  let currentRoom = "Umum";
  let dmTargetIp = null;
  let replyToMsg = null;
  let myIp = "";
  let myNick = localStorage.getItem("1wys_nick") || ("HP-" + Math.floor(100 + Math.random() * 899));
  let myStatus = localStorage.getItem("1wys_status") || "Aktif";
  let currentMessages = [];
  let shareTimer = null;
  let shareStream = null;
  let isSharing = false;

  function syncInputs() {
    document.getElementById("nickInput").value = myNick;
    document.getElementById("statusTagInput").value = myStatus;
    document.getElementById("mNickInput").value = myNick;
    document.getElementById("mStatusInput").value = myStatus;
  }
  syncInputs();

  const savedTheme = localStorage.getItem("1wys_theme") || "whatsapp";
  const savedFont = localStorage.getItem("1wys_font") || "14px";
  changeTheme(savedTheme, false);
  changeFont(savedFont, false);

  function switchMobileTab(tab) {
    document.getElementById("paneChat").classList.remove("mobile-active");
    document.getElementById("paneDevices").classList.remove("mobile-active");
    document.getElementById("paneMonitor").classList.remove("mobile-active");
    document.getElementById("mTabChat").classList.remove("active");
    document.getElementById("mTabDevices").classList.remove("active");
    document.getElementById("mTabMonitor").classList.remove("active");

    if (tab === "chat") {
      document.getElementById("paneChat").classList.add("mobile-active");
      document.getElementById("mTabChat").classList.add("active");
    } else if (tab === "devices") {
      document.getElementById("paneDevices").classList.add("mobile-active");
      document.getElementById("mTabDevices").classList.add("active");
    } else if (tab === "monitor") {
      document.getElementById("paneMonitor").classList.add("mobile-active");
      document.getElementById("mTabMonitor").classList.add("active");
    }
  }

  function openProfileModal() {
    syncInputs();
    document.getElementById("profileModal").classList.add("open");
  }
  function closeProfileModal() {
    document.getElementById("profileModal").classList.remove("open");
  }

  function changeTheme(val, save=true) {
    document.documentElement.setAttribute("data-theme", val);
    document.getElementById("themeSelect").value = val;
    document.getElementById("mThemeSelect").value = val;
    if (save) localStorage.setItem("1wys_theme", val);
  }
  function changeFont(val, save=true) {
    document.documentElement.style.setProperty("--font-size", val);
    document.getElementById("fontSelect").value = val;
    document.getElementById("mFontSelect").value = val;
    if (save) localStorage.setItem("1wys_font", val);
  }

  function escapeHtml(str) {
    return String(str || "").replace(/[&<>"']/g, m => ({
      "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
    }[m]));
  }

  function formatRichText(raw) {
    let safe = escapeHtml(raw);
    safe = safe.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    safe = safe.replace(/(https?:\/\/[^\s<]+)/g, '<a class="smart-link" href="$1" target="_blank" rel="noopener">$1</a>');
    safe = safe.replace(/\b(\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?)\b/g, '<a class="smart-link" href="http://$1" target="_blank" rel="noopener">$1</a>');
    return safe;
  }

  socket.on("connect", () => {
    socket.emit("register_client", {
      name: myNick,
      status_tag: myStatus,
      ua: navigator.userAgent
    });
    loadContext();
  });

  socket.on("welcome_meta", data => {
    myIp = data.ip;
    if (data.alias) myNick = data.alias;
    if (data.status_tag) myStatus = data.status_tag;
    syncInputs();
  });

  socket.on("kicked", data => {
    alert(data.reason || "Koneksi Anda dihentikan oleh Host.");
    location.reload();
  });

  function loadContext() {
    const params = new URLSearchParams({ room: currentRoom });
    if (dmTargetIp) params.set("dm_with", dmTargetIp);
    fetch("/api/state?" + params.toString())
      .then(r => r.json())
      .then(data => {
        renderRooms(data.rooms);
        renderMessages(data.messages);
        document.getElementById("pinText").textContent = "PIN: " + (data.pin || "-");
      });
  }

  function renderRooms(rooms) {
    const box = document.getElementById("roomsList");
    box.innerHTML = "";
    rooms.forEach(r => {
      const btn = document.createElement("button");
      btn.className = "room-btn" + (!dmTargetIp && currentRoom === r ? " active" : "");
      btn.textContent = "# " + r;
      btn.onclick = () => {
        dmTargetIp = null;
        currentRoom = r;
        socket.emit("join_room_channel", { room: r });
        loadContext();
        switchMobileTab("chat");
      };
      box.appendChild(btn);
    });
    if (dmTargetIp) {
      const dmBtn = document.createElement("button");
      dmBtn.className = "room-btn active";
      dmBtn.textContent = "DM: " + dmTargetIp;
      dmBtn.onclick = () => switchMobileTab("chat");
      box.appendChild(dmBtn);
    }
  }

  function openDm(targetIp) {
    dmTargetIp = targetIp;
    loadContext();
    switchMobileTab("chat");
  }

  function createRoom() {
    const inp = document.getElementById("newRoomInput");
    const name = inp.value.trim();
    if (!name) return;
    socket.emit("create_room", { room: name });
    inp.value = "";
  }

  socket.on("room_created", data => {
    renderRooms(data.rooms);
  });

  socket.on("presence_update", data => {
    renderRooms(data.rooms);
    const list = document.getElementById("devicesList");
    document.getElementById("devCount").textContent = data.devices.length;
    document.getElementById("mDevCount").textContent = data.devices.length;
    list.innerHTML = "";
    data.devices.forEach(d => {
      const card = document.createElement("div");
      card.className = "dev-card";
      const label = d.alias || d.name;
      card.innerHTML = `
        <div class="dev-top">
          <strong>${escapeHtml(label)}</strong>
          <span class="badge">${escapeHtml(d.status_tag || "Online")}</span>
        </div>
        <div style="color:var(--muted)">IP: ${escapeHtml(d.ip)} | ${escapeHtml(d.ua_short)}</div>
        ${d.sharing ? `<div style="color:var(--accent)">Sedang share layar (${d.fps} FPS)</div>` : ""}
        <div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:3px;">
          <button onclick="openDm('${escapeHtml(d.ip)}')">DM</button>
          <button onclick="setAliasPrompt('${escapeHtml(d.ip)}', '${escapeHtml(label)}')">Alias</button>
          <button class="danger" onclick="kickIp('${escapeHtml(d.ip)}')">Kick</button>
        </div>
      `;
      list.appendChild(card);
    });
    renderShareBoxes(data.shares);
  });

  function setAliasPrompt(ip, current) {
    const alias = prompt("Set alias/label tetap untuk IP " + ip + ":", current);
    if (alias !== null && alias.trim()) {
      socket.emit("set_device_alias", { ip, alias: alias.trim() });
    }
  }

  function kickIp(ip) {
    if (confirm("Putuskan perangkat IP " + ip + "?")) {
      socket.emit("kick_device", { ip });
    }
  }

  function applyProfileValues(nickVal, statusVal) {
    myNick = (nickVal || "").trim() || myNick;
    myStatus = (statusVal || "").trim() || "Aktif";
    localStorage.setItem("1wys_nick", myNick);
    localStorage.setItem("1wys_status", myStatus);
    syncInputs();
    socket.emit("update_profile", { name: myNick, status_tag: myStatus });
  }

  function saveProfileFromDesktop() {
    applyProfileValues(document.getElementById("nickInput").value, document.getElementById("statusTagInput").value);
  }

  function saveProfileFromModal() {
    applyProfileValues(document.getElementById("mNickInput").value, document.getElementById("mStatusInput").value);
    closeProfileModal();
  }

  function setPinFromPrompt() {
    const txt = prompt("Teks pengumuman yang di-pin:", document.getElementById("pinText").textContent.replace(/^PIN:\s*/, ""));
    if (txt !== null) {
      socket.emit("set_pin", { room: currentRoom, text: txt });
    }
  }

  socket.on("pin_updated", d => {
    if (d.room === currentRoom && !dmTargetIp) {
      document.getElementById("pinText").textContent = "PIN: " + d.text;
    }
  });

  function setReply(msg) {
    replyToMsg = { id: msg.id, sender: msg.sender, text: msg.text };
    document.getElementById("replyBanner").style.display = "flex";
    document.getElementById("replyText").textContent = "Balas ke " + msg.sender + ": " + (msg.text || "[Lampiran]");
    document.getElementById("msgInput").focus();
  }

  function cancelReply() {
    replyToMsg = null;
    document.getElementById("replyBanner").style.display = "none";
  }

  function sendMessage(overrideText=null) {
    const inp = document.getElementById("msgInput");
    const text = overrideText !== null ? overrideText : inp.value.trim();
    if (!text) return;

    if (text === "/help") {
      alert("Perintah cepat:\n/who - Info IP & profil Anda\n/clear - Bersihkan tampilan lokal\n/pin <teks> - Pasang pin room\n/room <nama> - Pindah/buat room");
      if (overrideText === null) inp.value = "";
      return;
    }
    if (text === "/who") {
      alert("Nama: " + myNick + "\nIP: " + myIp + "\nStatus: " + myStatus);
      if (overrideText === null) inp.value = "";
      return;
    }
    if (text === "/clear") {
      currentMessages = [];
      renderMessages([]);
      if (overrideText === null) inp.value = "";
      return;
    }
    if (text.startsWith("/pin ")) {
      socket.emit("set_pin", { room: currentRoom, text: text.slice(5).trim() });
      if (overrideText === null) inp.value = "";
      return;
    }
    if (text.startsWith("/room ")) {
      const rname = text.slice(6).trim();
      if (rname) {
        dmTargetIp = null;
        currentRoom = rname;
        socket.emit("create_room", { room: rname });
        socket.emit("join_room_channel", { room: rname });
        loadContext();
      }
      if (overrideText === null) inp.value = "";
      return;
    }

    socket.emit("send_message", {
      room: currentRoom,
      dm_with: dmTargetIp,
      sender: myNick,
      text: text,
      reply_to: replyToMsg
    });
    cancelReply();
    if (overrideText === null) inp.value = "";
  }

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function reactMsg(msgId, emoji) {
    socket.emit("react_message", {
      room: currentRoom,
      dm_with: dmTargetIp,
      msg_id: msgId,
      emoji
    });
  }

  function editMsg(msg) {
    const next = prompt("Edit pesan:", msg.text);
    if (next !== null && next.trim()) {
      socket.emit("edit_message", {
        room: currentRoom,
        dm_with: dmTargetIp,
        msg_id: msg.id,
        text: next.trim()
      });
    }
  }

  function unsendMsg(msgId) {
    if (confirm("Tarik pesan ini untuk semua perangkat?")) {
      socket.emit("unsend_message", {
        room: currentRoom,
        dm_with: dmTargetIp,
        msg_id: msgId
      });
    }
  }

  function handleFilePicked() {
    const files = document.getElementById("fileInput").files;
    const lbl = document.getElementById("fileLabel");
    const upBtn = document.getElementById("uploadBtn");
    if (files && files.length) {
      lbl.textContent = files.length + " file";
      upBtn.style.display = "inline-block";
    } else {
      lbl.textContent = "File";
      upBtn.style.display = "none";
    }
  }

  function uploadFiles() {
    const files = document.getElementById("fileInput").files;
    if (!files || !files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    fd.append("room", currentRoom);
    if (dmTargetIp) fd.append("dm_with", dmTargetIp);
    fd.append("sender", myNick);

    fetch("/api/upload", { method: "POST", body: fd })
      .then(r => r.json())
      .then(res => {
        if (res.error) alert(res.error);
        document.getElementById("fileInput").value = "";
        handleFilePicked();
      });
  }

  function previewDoc(url, name) {
    const box = document.getElementById("docPreview");
    box.textContent = "Memuat " + name + "...";
    switchMobileTab("monitor");
    fetch(url)
      .then(r => r.text())
      .then(t => {
        box.textContent = "=== " + name + " ===\n" + t.slice(0, 8000);
      })
      .catch(() => {
        box.textContent = "File biner/media: buka tautan langsung untuk mengunduh (" + name + ").";
      });
  }

  function renderMessages(msgs) {
    currentMessages = msgs || [];
    const box = document.getElementById("messagesList");
    box.innerHTML = "";
    currentMessages.forEach(m => {
      const div = document.createElement("div");
      const isMine = !m.is_system && m.ip === myIp;
      div.className = "bubble" + (m.is_system ? " sys" : (isMine ? " mine" : ""));

      let quoteHtml = "";
      if (m.reply_to) {
        quoteHtml = `<div class="quote"><strong>${escapeHtml(m.reply_to.sender)}</strong>: ${escapeHtml(m.reply_to.text || "[Lampiran]")}</div>`;
      }

      let bodyHtml = m.deleted
        ? `<em style="color:var(--muted)">Pesan telah ditarik</em>`
        : `<div>${formatRichText(m.text || "")}${m.edited ? ' <span style="font-size:10px;color:var(--muted)">(diedit)</span>' : ""}</div>`;

      let attHtml = "";
      if (!m.deleted && m.attachments && m.attachments.length) {
        attHtml = m.attachments.map(a => {
          if (a.is_image) {
            return `<div style="margin-top:6px;"><img src="${escapeHtml(a.url)}" style="max-width:100%;max-height:220px;border-radius:8px;display:block;" /><a class="smart-link" href="${escapeHtml(a.url)}" download="${escapeHtml(a.name)}">${escapeHtml(a.name)}</a></div>`;
          }
          return `<div style="margin-top:6px;">
            <a class="smart-link" href="${escapeHtml(a.url)}" download="${escapeHtml(a.name)}">${escapeHtml(a.name)}</a> (${a.size_kb} KB)
            <button style="margin-left:4px;padding:2px 6px;font-size:11px;" onclick="previewDoc('${escapeHtml(a.url)}','${escapeHtml(a.name)}')">Preview</button>
          </div>`;
        }).join("");
      }

      let rxHtml = "";
      if (m.reactions && Object.keys(m.reactions).length) {
        rxHtml = `<div class="reactions">` + Object.entries(m.reactions).map(([em, cnt]) =>
          `<span class="rx-chip" onclick="reactMsg('${m.id}','${em}')">${em} ${cnt}</span>`
        ).join("") + `</div>`;
      }

      let actHtml = "";
      if (!m.is_system && !m.deleted) {
        actHtml = `<div class="msg-actions">
          <button onclick='setReply(${JSON.stringify(m).replace(/'/g, "&#39;")})'>Balas</button>
          <button onclick="reactMsg('${m.id}','👍')">👍</button>
          <button onclick="reactMsg('${m.id}','🔥')">🔥</button>
          <button onclick="reactMsg('${m.id}','✅')">✅</button>
          ${isMine ? `<button onclick='editMsg(${JSON.stringify(m).replace(/'/g, "&#39;")})'>Edit</button>` : ""}
          ${isMine ? `<button onclick="unsendMsg('${m.id}')">Tarik</button>` : ""}
        </div>`;
      }

      div.innerHTML = `
        ${m.is_system ? "" : `<div class="meta"><strong>${escapeHtml(m.sender)} (${escapeHtml(m.ip)})</strong><span>${escapeHtml(m.time)}</span></div>`}
        ${quoteHtml}
        ${bodyHtml}
        ${attHtml}
        ${rxHtml}
        ${actHtml}
      `;
      box.appendChild(div);
    });
    box.scrollTop = box.scrollHeight;
  }

  socket.on("new_message", msg => {
    if (dmTargetIp) {
      const relevant = (msg.is_dm && (msg.ip === dmTargetIp || msg.dm_with === dmTargetIp || msg.ip === myIp));
      if (!relevant) return;
    } else {
      if (msg.is_dm || msg.room !== currentRoom) return;
    }
    currentMessages.push(msg);
    renderMessages(currentMessages);
  });

  socket.on("message_updated", msg => {
    const idx = currentMessages.findIndex(x => x.id === msg.id);
    if (idx !== -1) {
      currentMessages[idx] = msg;
      renderMessages(currentMessages);
    }
  });

  function renderShareBoxes(shares) {
    const grid = document.getElementById("screenGrid");
    const existingIds = new Set(shares.map(s => s.sid));
    Array.from(grid.children).forEach(el => {
      if (!existingIds.has(el.dataset.sid)) el.remove();
    });
    shares.forEach(s => {
      let box = grid.querySelector(`[data-sid="${s.sid}"]`);
      if (!box) {
        box = document.createElement("div");
        box.className = "stream-box";
        box.dataset.sid = s.sid;
        box.innerHTML = `
          <div><strong>${escapeHtml(s.sender)}</strong> <span class="badge">${s.fps} FPS</span></div>
          <img id="img_${s.sid}" alt="Stream ${escapeHtml(s.sender)}" />
        `;
        grid.appendChild(box);
      } else {
        box.querySelector(".badge").textContent = s.fps + " FPS";
      }
    });
  }

  socket.on("screen_frame", data => {
    const img = document.getElementById("img_" + data.sid);
    if (img) img.src = data.frame;
  });

  async function toggleScreenShare() {
    const btn = document.getElementById("shareBtn");
    const fps = parseInt(document.getElementById("fpsSelect").value || "5", 10);
    if (!isSharing) {
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
          alert("Browser/perangkat ini tidak mendukung getDisplayMedia langsung.");
          return;
        }
        shareStream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: fps }, audio: false });
        const vid = document.getElementById("localVideo");
        const cvs = document.getElementById("captureCanvas");
        vid.srcObject = shareStream;
        isSharing = true;
        btn.textContent = "Stop Share Layar";
        socket.emit("start_screen_share", { sender: myNick, fps });

        const intervalMs = Math.max(100, Math.floor(1000 / fps));
        shareTimer = setInterval(() => {
          if (!isSharing || !vid.videoWidth) return;
          const targetW = 640;
          const ratio = vid.videoHeight / vid.videoWidth;
          cvs.width = targetW;
          cvs.height = Math.round(targetW * ratio);
          const ctx = cvs.getContext("2d");
          ctx.drawImage(vid, 0, 0, cvs.width, cvs.height);
          const dataUrl = cvs.toDataURL("image/jpeg", 0.55);
          socket.emit("screen_frame", { frame: dataUrl });
        }, intervalMs);

        shareStream.getVideoTracks()[0].onended = () => stopScreenShare();
      } catch (err) {
        alert("Gagal memulai share layar: " + err.message);
      }
    } else {
      stopScreenShare();
    }
  }

  function stopScreenShare() {
    isSharing = false;
    if (shareTimer) { clearInterval(shareTimer); shareTimer = null; }
    if (shareStream) {
      shareStream.getTracks().forEach(t => t.stop());
      shareStream = null;
    }
    document.getElementById("shareBtn").textContent = "Mulai Share Layar";
    socket.emit("stop_screen_share");
  }
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        runtime_mode=RUNTIME_MODE,
        local_ips=LOCAL_IPS,
        server_port=SERVER_PORT
    )

@app.route("/api/state")
def api_state():
    room = request.args.get("room", "Umum")
    dm_with = request.args.get("dm_with", "")
    client_ip = request.remote_addr or "0.0.0.0"
    if dm_with:
        msgs = DM_MESSAGES.get(dm_key(client_ip, dm_with), [])
        pin = f"Direct Message antara {client_ip} & {dm_with}"
    else:
        if room not in MESSAGES:
            room = "Umum"
        msgs = MESSAGES[room]
        pin = PINNED.get(room, "")
    return jsonify({
        "rooms": ROOMS,
        "messages": msgs,
        "pin": pin
    })

@app.route("/api/upload", methods=["POST"])
def api_upload():
    client_ip = request.remote_addr or "0.0.0.0"
    if client_ip in KICKED_IPS:
        return jsonify({"error": "Perangkat diblokir host"}), 403

    room = request.form.get("room", "Umum")
    dm_with = request.form.get("dm_with", "").strip()
    sender = request.form.get("sender", client_ip).strip()
    if client_ip in ALIAS_BY_IP and ALIAS_BY_IP[client_ip].get("alias"):
        sender = ALIAS_BY_IP[client_ip]["alias"]

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Tidak ada file dikirim"}), 400

    attachments = []
    for f in files:
        if not f or not f.filename:
            continue
        safe = sanitize_filename(f.filename)
        stored_name = f"{make_msg_id()}_{safe}"
        full_path = os.path.join(UPLOAD_DIR, stored_name)
        f.save(full_path)
        size_bytes = os.path.getsize(full_path)
        mime, _ = mimetypes.guess_type(safe)
        is_img = bool(mime and mime.startswith("image/"))
        attachments.append({
            "name": safe,
            "url": f"/uploads/{stored_name}",
            "size_kb": max(1, round(size_bytes / 1024)),
            "is_image": is_img
        })

    msg = {
        "id": make_msg_id(),
        "sender": sender,
        "ip": client_ip,
        "room": room,
        "dm_with": dm_with or None,
        "is_dm": bool(dm_with),
        "text": "",
        "time": now_str(),
        "reply_to": None,
        "reactions": {},
        "edited": False,
        "deleted": False,
        "attachments": attachments,
        "is_system": False
    }

    if dm_with:
        k = dm_key(client_ip, dm_with)
        DM_MESSAGES.setdefault(k, []).append(msg)
    else:
        if room not in MESSAGES:
            ROOMS.append(room)
            MESSAGES[room] = []
            PINNED[room] = ""
        MESSAGES[room].append(msg)

    socketio.emit("new_message", msg)
    return jsonify({"ok": True, "count": len(attachments)})

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@socketio.on("connect")
def on_connect():
    client_ip = request.remote_addr or "0.0.0.0"
    if client_ip in KICKED_IPS:
        emit("kicked", {"reason": "IP Anda telah di-kick oleh host."})
        disconnect()
        return

@socketio.on("register_client")
def on_register(data):
    sid = request.sid
    client_ip = request.remote_addr or "0.0.0.0"
    alias_info = ALIAS_BY_IP.get(client_ip, {})
    name = alias_info.get("alias") or (data or {}).get("name") or f"Device-{sid[:4]}"
    status_tag = alias_info.get("status_tag") or (data or {}).get("status_tag") or "Online"
    ua = (data or {}).get("ua", "")
    ua_short = ua.split(")")[0][:36] if ")" in ua else (ua[:36] or "Browser")

    DEVICES[sid] = {
        "ip": client_ip,
        "name": name,
        "alias": alias_info.get("alias", ""),
        "status_tag": status_tag,
        "ua_short": ua_short,
        "online_at": now_str()
    }
    emit("welcome_meta", {
        "ip": client_ip,
        "alias": alias_info.get("alias", ""),
        "status_tag": status_tag
    })
    broadcast_presence()

@socketio.on("update_profile")
def on_update_profile(data):
    sid = request.sid
    if sid not in DEVICES:
        return
    client_ip = DEVICES[sid]["ip"]
    name = (data or {}).get("name", "").strip()
    status_tag = (data or {}).get("status_tag", "").strip()
    if name and not DEVICES[sid].get("alias"):
        DEVICES[sid]["name"] = name
    if status_tag:
        DEVICES[sid]["status_tag"] = status_tag
        ALIAS_BY_IP.setdefault(client_ip, {})["status_tag"] = status_tag
    broadcast_presence()

@socketio.on("set_device_alias")
def on_set_alias(data):
    target_ip = (data or {}).get("ip", "").strip()
    alias = (data or {}).get("alias", "").strip()
    if not target_ip or not alias:
        return
    ALIAS_BY_IP.setdefault(target_ip, {})["alias"] = alias
    for d in DEVICES.values():
        if d["ip"] == target_ip:
            d["alias"] = alias
            d["name"] = alias
    broadcast_presence()

@socketio.on("kick_device")
def on_kick_device(data):
    target_ip = (data or {}).get("ip", "").strip()
    if not target_ip:
        return
    KICKED_IPS.add(target_ip)
    to_remove = [sid for sid, d in DEVICES.items() if d["ip"] == target_ip]
    for sid in to_remove:
        socketio.emit("kicked", {"reason": "Koneksi diputus oleh host."}, room=sid)
        DEVICES.pop(sid, None)
        ACTIVE_SHARES.pop(sid, None)
    broadcast_presence()

@socketio.on("join_room_channel")
def on_join_room(data):
    room = (data or {}).get("room", "Umum")
    if room in ROOMS:
        pass

@socketio.on("create_room")
def on_create_room(data):
    room = re.sub(r"[^A-Za-z0-9 _-]", "", (data or {}).get("room", "")).strip()[:32]
    if room and room not in ROOMS:
        ROOMS.append(room)
        MESSAGES[room] = []
        PINNED[room] = f"Room #{room} dibuat"
    emit("room_created", {"rooms": ROOMS}, broadcast=True)

@socketio.on("set_pin")
def on_set_pin(data):
    room = (data or {}).get("room", "Umum")
    text = (data or {}).get("text", "").strip()[:240]
    if room in PINNED:
        PINNED[room] = text
        emit("pin_updated", {"room": room, "text": text}, broadcast=True)

@socketio.on("send_message")
def on_send_message(data):
    sid = request.sid
    client_ip = DEVICES.get(sid, {}).get("ip") or request.remote_addr or "0.0.0.0"
    if client_ip in KICKED_IPS:
        return

    sender = DEVICES.get(sid, {}).get("alias") or DEVICES.get(sid, {}).get("name") or (data or {}).get("sender") or client_ip
    room = (data or {}).get("room", "Umum")
    dm_with = ((data or {}).get("dm_with") or "").strip()
    text = ((data or {}).get("text") or "").strip()
    reply_to = (data or {}).get("reply_to")

    if not text:
        return

    msg = {
        "id": make_msg_id(),
        "sender": sender,
        "ip": client_ip,
        "room": room,
        "dm_with": dm_with or None,
        "is_dm": bool(dm_with),
        "text": text,
        "time": now_str(),
        "reply_to": reply_to,
        "reactions": {},
        "edited": False,
        "deleted": False,
        "attachments": [],
        "is_system": False
    }

    if dm_with:
        DM_MESSAGES.setdefault(dm_key(client_ip, dm_with), []).append(msg)
    else:
        if room not in MESSAGES:
            ROOMS.append(room)
            MESSAGES[room] = []
            PINNED[room] = ""
        MESSAGES[room].append(msg)

    emit("new_message", msg, broadcast=True)

def _find_msg(room, dm_with, msg_id, client_ip):
    if dm_with:
        arr = DM_MESSAGES.get(dm_key(client_ip, dm_with), [])
    else:
        arr = MESSAGES.get(room, [])
    for m in arr:
        if m["id"] == msg_id:
            return m
    return None

@socketio.on("react_message")
def on_react(data):
    sid = request.sid
    client_ip = DEVICES.get(sid, {}).get("ip") or request.remote_addr or "0.0.0.0"
    msg = _find_msg((data or {}).get("room", "Umum"), (data or {}).get("dm_with", ""), (data or {}).get("msg_id", ""), client_ip)
    emoji = (data or {}).get("emoji", "👍")
    if msg:
        msg["reactions"][emoji] = msg["reactions"].get(emoji, 0) + 1
        emit("message_updated", msg, broadcast=True)

@socketio.on("edit_message")
def on_edit(data):
    sid = request.sid
    client_ip = DEVICES.get(sid, {}).get("ip") or request.remote_addr or "0.0.0.0"
    msg = _find_msg((data or {}).get("room", "Umum"), (data or {}).get("dm_with", ""), (data or {}).get("msg_id", ""), client_ip)
    text = ((data or {}).get("text") or "").strip()
    if msg and msg["ip"] == client_ip and text:
        msg["text"] = text
        msg["edited"] = True
        emit("message_updated", msg, broadcast=True)

@socketio.on("unsend_message")
def on_unsend(data):
    sid = request.sid
    client_ip = DEVICES.get(sid, {}).get("ip") or request.remote_addr or "0.0.0.0"
    msg = _find_msg((data or {}).get("room", "Umum"), (data or {}).get("dm_with", ""), (data or {}).get("msg_id", ""), client_ip)
    if msg and msg["ip"] == client_ip:
        msg["deleted"] = True
        msg["text"] = ""
        msg["attachments"] = []
        emit("message_updated", msg, broadcast=True)

@socketio.on("start_screen_share")
def on_start_share(data):
    sid = request.sid
    sender = DEVICES.get(sid, {}).get("name") or (data or {}).get("sender") or sid[:6]
    fps = int((data or {}).get("fps", 5))
    fps = max(1, min(15, fps))
    ACTIVE_SHARES[sid] = {"sid": sid, "sender": sender, "fps": fps}
    broadcast_presence()

@socketio.on("screen_frame")
def on_screen_frame(data):
    sid = request.sid
    frame = (data or {}).get("frame")
    if sid in ACTIVE_SHARES and frame:
        emit("screen_frame", {"sid": sid, "frame": frame}, broadcast=True)

@socketio.on("stop_screen_share")
def on_stop_share():
    sid = request.sid
    ACTIVE_SHARES.pop(sid, None)
    broadcast_presence()

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    DEVICES.pop(sid, None)
    ACTIVE_SHARES.pop(sid, None)
    broadcast_presence()

if __name__ == "__main__":
    print(f"=== {APP_NAME} ({APP_VERSION}) ===")
    print(f"Mode Host : {RUNTIME_MODE} ({platform.system()})")
    print(f"Upload Dir: {UPLOAD_DIR}")
    for ip in LOCAL_IPS:
        print(f"Akses LAN : http://{ip}:{SERVER_PORT}")
    socketio.run(app, host="0.0.0.0", port=SERVER_PORT)