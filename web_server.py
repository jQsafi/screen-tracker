"""
Built-in Web Application Server for Screen Tracker.
Provides a modern, real-time web dashboard for viewing screenshots, searching OCR text,
filtering by application, and monitoring live statistics. Zero external web dependencies.
"""

from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import mimetypes
import os
from pathlib import Path
import socketserver
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

from config import Config
from database import TrackerDatabase

logger = logging.getLogger("ScreenTrackerWeb")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Screen Tracker Dashboard</title>
  <style>
    :root {
      --bg: #0f1117;
      --card-bg: #1a1d27;
      --card-hover: #222634;
      --border: #2d3345;
      --text: #e1e7f0;
      --text-muted: #8b9bb4;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --success: #10b981;
      --warning: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 60px;
    }
    header {
      background: rgba(26, 29, 39, 0.95);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 50;
      padding: 14px 24px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 1.25rem;
      font-weight: 700;
      color: #fff;
    }
    .brand-badge {
      font-size: 0.75rem;
      background: rgba(59, 130, 246, 0.2);
      color: var(--accent);
      padding: 2px 8px;
      border-radius: 9999px;
      border: 1px solid rgba(59, 130, 246, 0.3);
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .live-pill {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.8rem;
      background: rgba(16, 185, 129, 0.15);
      color: var(--success);
      padding: 4px 10px;
      border-radius: 9999px;
      border: 1px solid rgba(16, 185, 129, 0.3);
      cursor: pointer;
      user-select: none;
    }
    .live-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 8px var(--success);
      animation: pulse 2s infinite;
    }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
    .btn {
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 8px 14px;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: background 0.2s;
    }
    .btn:hover { background: var(--accent-hover); }
    .btn-secondary {
      background: #272d3f;
      color: var(--text);
      border: 1px solid var(--border);
    }
    .btn-secondary:hover { background: #32394e; }
    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 24px;
    }
    .stats-bar {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }
    .stat-label {
      font-size: 0.8rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .stat-value {
      font-size: 1.7rem;
      font-weight: 700;
      color: #fff;
      margin-top: 4px;
    }
    .controls {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-bottom: 24px;
    }
    .search-input {
      flex: 1 1 300px;
      background: #12141c;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 0.9rem;
      outline: none;
    }
    .search-input:focus { border-color: var(--accent); }
    .select-input {
      background: #12141c;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 0.9rem;
      outline: none;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
      cursor: pointer;
    }
    .card:hover {
      transform: translateY(-2px);
      border-color: #3b82f6;
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }
    .card-img-wrap {
      width: 100%;
      height: 180px;
      background: #090a0f;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      border-bottom: 1px solid var(--border);
    }
    .card-img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: top center;
    }
    .card-body {
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      flex: 1;
    }
    .card-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.75rem;
    }
    .app-tag {
      background: #2a3144;
      color: #93c5fd;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 600;
      max-width: 160px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .pushed-tag {
      font-size: 0.7rem;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .pushed-yes { background: rgba(16, 185, 129, 0.2); color: #34d399; }
    .pushed-no { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
    .window-title {
      font-size: 0.85rem;
      font-weight: 500;
      color: #fff;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .text-preview {
      font-size: 0.8rem;
      color: var(--text-muted);
      background: #13151e;
      border: 1px solid #232838;
      border-radius: 4px;
      padding: 8px;
      height: 70px;
      overflow: hidden;
      text-overflow: ellipsis;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .card-footer {
      display: flex;
      justify-content: space-between;
      font-size: 0.72rem;
      color: var(--text-muted);
      padding-top: 6px;
      border-top: 1px solid #232838;
    }
    /* Modal */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.85);
      backdrop-filter: blur(4px);
      z-index: 100;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .modal {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      max-width: 900px;
      width: 100%;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 20px 40px rgba(0,0,0,0.6);
    }
    .modal-header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-body {
      padding: 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .modal-img {
      width: 100%;
      max-height: 450px;
      object-fit: contain;
      background: #000;
      border-radius: 6px;
      border: 1px solid var(--border);
    }
    .modal-text-box {
      background: #11131a;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.85rem;
      color: #cbd5e1;
      max-height: 200px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .close-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
    }
    .close-btn:hover { color: #fff; }
    .empty-state {
      grid-column: 1 / -1;
      text-align: center;
      padding: 60px 20px;
      color: var(--text-muted);
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <span>🖥️ Screen Tracker</span>
      <span class="brand-badge">Real-time Hub</span>
    </div>
    <div class="header-actions">
      <div id="livePill" class="live-pill" onclick="toggleAutoRefresh()" title="Click to pause/resume real-time polling">
        <span class="live-dot" id="liveDot"></span>
        <span id="liveText">Live: Active (3s)</span>
      </div>
      <button class="btn" onclick="captureNow()">
        <span>📸 Capture Now</span>
      </button>
    </div>
  </header>

  <main class="container">
    <!-- Statistics Bar -->
    <div class="stats-bar">
      <div class="stat-card">
        <div class="stat-label">Total Captures</div>
        <div class="stat-value" id="statTotal">--</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Pushed to GitHub</div>
        <div class="stat-value" id="statPushed">--</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Pending Sync</div>
        <div class="stat-value" id="statPending">--</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Top Active App</div>
        <div class="stat-value" id="statTopApp" style="font-size: 1.25rem; font-weight: 600; margin-top: 8px;">--</div>
      </div>
    </div>

    <!-- Filters & Search Controls -->
    <div class="controls">
      <input type="text" id="searchInput" class="search-input" placeholder="🔍 Search extracted OCR text, window title, or app..." oninput="handleSearch()">
      <select id="appFilter" class="select-input" onchange="loadScreenshots(true)">
        <option value="">All Applications</option>
      </select>
      <button class="btn btn-secondary" onclick="loadScreenshots(true)">Refresh</button>
    </div>

    <!-- Screenshots Grid -->
    <div class="grid" id="screenshotsGrid">
      <div class="empty-state">Loading screenshots...</div>
    </div>
  </main>

  <!-- Detail Modal -->
  <div class="modal-backdrop" id="modalBackdrop" onclick="handleBackdropClick(event)">
    <div class="modal">
      <div class="modal-header">
        <div>
          <h3 id="modalApp">Application</h3>
          <p id="modalWindow" style="font-size: 0.8rem; color: var(--text-muted);"></p>
        </div>
        <button class="close-btn" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <img id="modalImg" class="modal-img" src="" alt="Screenshot Full View">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <h4 style="font-size:0.9rem;">Extracted Text (OCR)</h4>
          <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.75rem;" onclick="copyModalText()">Copy Text</button>
        </div>
        <div id="modalText" class="modal-text-box">No text detected</div>
        <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-muted);">
          <span id="modalTimestamp"></span>
          <span id="modalCommit"></span>
        </div>
      </div>
    </div>
  </div>

  <script>
    let highestId = 0;
    let autoRefreshActive = true;
    let autoRefreshInterval = null;
    let searchDebounce = null;
    let currentModalText = "";

    async function fetchStats() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('statTotal').innerText = data.total_captured;
        document.getElementById('statPushed').innerText = data.github_pushed;
        document.getElementById('statPending').innerText = data.pending_push;
        const top = data.top_apps && data.top_apps.length > 0 ? data.top_apps[0].app_name : 'None';
        document.getElementById('statTopApp').innerText = top;
      } catch (e) {
        console.error("Failed to load stats", e);
      }
    }

    async function fetchApps() {
      try {
        const res = await fetch('/api/apps');
        const apps = await res.json();
        const select = document.getElementById('appFilter');
        const currentVal = select.value;
        select.innerHTML = '<option value="">All Applications</option>';
        apps.forEach(a => {
          const opt = document.createElement('option');
          opt.value = a;
          opt.textContent = a;
          if (a === currentVal) opt.selected = true;
          select.appendChild(opt);
        });
      } catch (e) {
        console.error("Failed to load apps", e);
      }
    }

    async function loadScreenshots(reset = false) {
      const query = document.getElementById('searchInput').value.trim();
      const app = document.getElementById('appFilter').value;
      const url = `/api/screenshots?query=${encodeURIComponent(query)}&app=${encodeURIComponent(app)}&limit=40`;

      try {
        const res = await fetch(url);
        const data = await res.json();
        const container = document.getElementById('screenshotsGrid');

        if (!data.items || data.items.length === 0) {
          container.innerHTML = '<div class="empty-state">No screenshots match your search.</div>';
          return;
        }

        container.innerHTML = '';
        data.items.forEach(item => {
          if (item.id > highestId) highestId = item.id;
          const card = createCard(item);
          container.appendChild(card);
        });
      } catch (e) {
        console.error("Failed to load screenshots", e);
      }
    }

    function createCard(item) {
      const card = document.createElement('div');
      card.className = 'card';
      card.onclick = () => openModal(item);

      const pushedClass = item.github_pushed ? 'pushed-yes' : 'pushed-no';
      const pushedText = item.github_pushed ? 'Synced' : 'Pending Push';
      const textPreview = (item.extracted_text || '(No text extracted)').trim();
      const timeFormatted = new Date(item.timestamp).toLocaleTimeString();

      card.innerHTML = `
        <div class="card-img-wrap">
          <img class="card-img" src="/api/screenshot/${item.id}/image?t=${encodeURIComponent(item.timestamp)}" alt="Capture #${item.id}" loading="lazy">
        </div>
        <div class="card-body">
          <div class="card-meta">
            <span class="app-tag" title="${item.app_name}">${item.app_name || 'Unknown'}</span>
            <span class="pushed-tag ${pushedClass}">${pushedText}</span>
          </div>
          <div class="window-title" title="${item.window_title || ''}">${item.window_title || 'Untitled Window'}</div>
          <div class="text-preview">${escapeHtml(textPreview)}</div>
          <div class="card-footer">
            <span>#${item.id}</span>
            <span>${timeFormatted}</span>
          </div>
        </div>
      `;
      return card;
    }

    function escapeHtml(str) {
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function handleSearch() {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        loadScreenshots(true);
      }, 300);
    }

    async function checkRealtimeDelta() {
      if (!autoRefreshActive) return;
      const query = document.getElementById('searchInput').value.trim();
      const app = document.getElementById('appFilter').value;
      if (query !== '' || app !== '') return; // don't disrupt active search

      try {
        const res = await fetch(`/api/poll?since_id=${highestId}`);
        const data = await res.json();
        if (data.items && data.items.length > 0) {
          const container = document.getElementById('screenshotsGrid');
          data.items.forEach(item => {
            if (item.id > highestId) highestId = item.id;
            const card = createCard(item);
            container.insertBefore(card, container.firstChild);
          });
          fetchStats();
          fetchApps();
        }
      } catch (e) {
        console.debug("Poll error", e);
      }
    }

    function toggleAutoRefresh() {
      autoRefreshActive = !autoRefreshActive;
      const dot = document.getElementById('liveDot');
      const text = document.getElementById('liveText');
      if (autoRefreshActive) {
        dot.style.display = 'inline-block';
        text.innerText = 'Live: Active (3s)';
      } else {
        dot.style.display = 'none';
        text.innerText = 'Live: Paused';
      }
    }

    async function captureNow() {
      const btn = event.currentTarget;
      btn.disabled = true;
      btn.innerText = '⏳ Capturing...';
      try {
        const res = await fetch('/api/capture_now', { method: 'POST' });
        const result = await res.json();
        if (result.success) {
          await loadScreenshots(true);
          await fetchStats();
        } else {
          alert('Capture failed: ' + (result.error || 'Unknown error'));
        }
      } catch (e) {
        alert('Error triggering capture: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerText = '📸 Capture Now';
      }
    }

    function openModal(item) {
      document.getElementById('modalApp').innerText = item.app_name || 'Unknown Application';
      document.getElementById('modalWindow').innerText = item.window_title || 'Untitled Window';
      document.getElementById('modalImg').src = `/api/screenshot/${item.id}/image?t=${encodeURIComponent(item.timestamp)}`;
      currentModalText = item.extracted_text || '';
      document.getElementById('modalText').innerText = currentModalText || '(No text detected in screenshot)';
      document.getElementById('modalTimestamp').innerText = 'Timestamp: ' + item.timestamp;
      document.getElementById('modalCommit').innerText = item.commit_hash ? 'Git: ' + item.commit_hash.substring(0, 7) : 'Git: Not committed';
      document.getElementById('modalBackdrop').style.display = 'flex';
    }

    function closeModal() {
      document.getElementById('modalBackdrop').style.display = 'none';
    }

    function handleBackdropClick(e) {
      if (e.target.id === 'modalBackdrop') closeModal();
    }

    function copyModalText() {
      if (!currentModalText) return;
      navigator.clipboard.writeText(currentModalText);
      alert('OCR text copied to clipboard!');
    }

    // Initialize
    fetchStats();
    fetchApps();
    loadScreenshots(true);

    // Periodic live poller every 3s
    setInterval(checkRealtimeDelta, 3000);
    // Periodic stats update every 10s
    setInterval(fetchStats, 10000);
  </script>
</body>
</html>
"""


class TrackerRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Screen Tracker Web Dashboard and REST API."""

    def __init__(self, request, client_address, server):
        self.app = server.app_instance
        self.db = self.app.db
        super().__init__(request, client_address, server)

    def log_message(self, format, *args):
        # Override to keep logs clean
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query_params = parse_qs(parsed.query)

        # 1. Main Dashboard HTML
        if path == "/" or path == "/index.html":
            self._send_response(200, "text/html; charset=utf-8", HTML_DASHBOARD.encode("utf-8"))
            return

        # 2. API: Summary Statistics
        if path == "/api/stats":
            stats = self.db.get_stats()
            self._send_json(stats)
            return

        # 3. API: Distinct Applications List
        if path == "/api/apps":
            apps = self.db.get_unique_apps()
            self._send_json(apps)
            return

        # 4. API: Screenshots List & Search
        if path == "/api/screenshots":
            q = query_params.get("query", [""])[0]
            app = query_params.get("app", [""])[0]
            limit = int(query_params.get("limit", [50])[0])
            offset = int(query_params.get("offset", [0])[0])
            result = self.db.get_filtered(query=q, app_name=app, limit=limit, offset=offset)
            self._send_json(result)
            return

        # 5. API: Real-time Delta Poll
        if path == "/api/poll":
            since_id = int(query_params.get("since_id", [0])[0])
            result = self.db.get_filtered(since_id=since_id, limit=20)
            self._send_json(result)
            return

        # 6. API: Screenshot Image Serving
        if path.startswith("/api/screenshot/") and path.endswith("/image"):
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[2].isdigit():
                rec_id = int(parts[2])
                record = self.db.get_by_id(rec_id)
                if record:
                    # Check if blob stored in database
                    if record.get("image_blob"):
                        self._send_response(200, "image/png", record["image_blob"])
                        return

                    # Otherwise serve from file system
                    file_path = Path(record["image_path"])
                    if not file_path.is_absolute():
                        candidates = [
                            file_path,
                            self.app.config.output_dir / file_path,
                            self.app.config.git_repo_dir / file_path,
                            Path("/data/data/com.termux/files/home/screen_tracker") / file_path,
                        ]
                        for c in candidates:
                            if c.exists() and c.is_file():
                                file_path = c
                                break
                    if file_path.exists() and file_path.is_file():
                        self._serve_file(file_path)
                        return

            self._send_response(404, "text/plain", b"Screenshot Image Not Found")
            return

        # 7. Static file serving under screenshots directory
        if path.startswith("/screenshots/"):
            rel_path = path[len("/screenshots/"):]
            file_path = self.app.config.output_dir / rel_path
            if file_path.exists() and file_path.is_file():
                self._serve_file(file_path)
                return
            self._send_response(404, "text/plain", b"File Not Found")
            return

        self._send_response(404, "text/plain", b"Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # API: Trigger immediate capture cycle
        if path == "/api/capture_now":
            try:
                record_id = self.app.run_single_cycle()
                self._send_json({"success": True, "record_id": record_id})
            except Exception as e:
                logger.error("Capture trigger error: %s", e)
                self._send_json({"success": False, "error": str(e)}, status=500)
            return

        self._send_response(404, "text/plain", b"Endpoint Not Found")

    def _serve_file(self, file_path: Path):
        """Streams a local image or static file to the client."""
        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "application/octet-stream"
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self._send_response(200, mime_type, content)
        except Exception as e:
            logger.error("Error reading file %s: %s", file_path, e)
            self._send_response(500, "text/plain", b"Internal Server Error")

    def _send_json(self, data: any, status: int = 200):
        content = json.dumps(data, default=str).encode("utf-8")
        self._send_response(status, "application/json; charset=utf-8", content)

    def _send_response(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


class WebDashboard:
    """Manages the background HTTP web server thread."""

    def __init__(self, app_instance, host: str = "0.0.0.0", port: int = 8080):
        self.app_instance = app_instance
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Starts the web dashboard in a daemon thread."""
        self.server = ThreadedHTTPServer((self.host, self.port), TrackerRequestHandler)
        self.server.app_instance = self.app_instance

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info("Web Dashboard running at http://localhost:%d (and http://%s:%d)", self.port, self.host, self.port)

    def stop(self):
        """Stops the web server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Web Dashboard stopped.")
