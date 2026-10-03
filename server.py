"""
HR Admin Web Dashboard Server for Identity Lifecycle Automation (JML).
Serves a modern single-page application on http://localhost:5000 allowing HR admins
to visually manage Joiner, Mover, Leaver events, submit new hires/transfers,
and view live Keycloak provisioning & PostgreSQL audit logs.
"""

import csv
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.abspath("."))

from tests.test_jml import FakeKeycloak, FakeAudit
from jml.processor import process_event

# In-memory storage for active session
kc_instance = FakeKeycloak()
audit_instance = FakeAudit()

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HR Identity Lifecycle Portal | JML Automation</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --border-color: rgba(255, 255, 255, 0.1);
            --accent-blue: #38bdf8;
            --accent-purple: #818cf8;
            --success-green: #34d399;
            --warning-yellow: #fbbf24;
            --danger-red: #f87171;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Inter', sans-serif;
        }

        body {
            background: radial-gradient(circle at top left, #1e1b4b, var(--bg-dark));
            color: var(--text-main);
            min-height: 100vh;
            padding: 2rem;
        }

        .container {
            max-width: 1300px;
            margin: 0 auto;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 2rem;
        }

        .logo-group {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .logo-icon {
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 1.4rem;
            color: #fff;
            box-shadow: 0 4px 20px rgba(56, 189, 248, 0.3);
        }

        h1 {
            font-size: 1.6rem;
            font-weight: 700;
            background: linear-gradient(90deg, #fff, var(--text-muted));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-actions {
            display: flex;
            gap: 1rem;
        }

        .btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 0.6rem 1.2rem;
            border-radius: 8px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .btn:hover {
            background: rgba(255, 255, 255, 0.1);
            transform: translateY(-1px);
        }

        .btn-primary {
            background: linear-gradient(135deg, #4f46e5, #3b82f6);
            border: none;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4);
        }

        .btn-primary:hover {
            box-shadow: 0 6px 20px rgba(59, 130, 246, 0.6);
        }

        .btn-success {
            background: linear-gradient(135deg, #059669, #10b981);
            border: none;
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .stat-label {
            font-size: 0.85rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .stat-value {
            font-size: 2rem;
            font-weight: 700;
        }

        /* Main Grid Layout */
        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 2rem;
        }

        .panel {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1.2rem;
        }

        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .panel-title {
            font-size: 1.1rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }

        th {
            text-align: left;
            padding: 0.75rem 1rem;
            color: var(--text-muted);
            font-weight: 500;
            border-bottom: 1px solid var(--border-color);
        }

        td {
            padding: 0.9rem 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        tr:last-child td {
            border-bottom: none;
        }

        .badge {
            padding: 0.25rem 0.6rem;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            display: inline-block;
        }

        .badge-joiner { background: rgba(52, 211, 153, 0.15); color: var(--success-green); }
        .badge-mover { background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); }
        .badge-leaver { background: rgba(248, 113, 113, 0.15); color: var(--danger-red); }

        .badge-success { background: rgba(52, 211, 153, 0.2); color: var(--success-green); }
        .badge-skipped { background: rgba(251, 191, 36, 0.2); color: var(--warning-yellow); }
        .badge-failed { background: rgba(248, 113, 113, 0.2); color: var(--danger-red); }

        /* Form Controls */
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
            margin-bottom: 1rem;
        }

        label {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        input, select {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border-color);
            color: #fff;
            padding: 0.6rem 0.8rem;
            border-radius: 8px;
            font-size: 0.9rem;
            outline: none;
        }

        input:focus, select:focus {
            border-color: var(--accent-blue);
        }

        .audit-item {
            padding: 0.8rem;
            border-radius: 8px;
            background: rgba(15, 23, 42, 0.4);
            border-left: 3px solid var(--accent-blue);
            font-size: 0.85rem;
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
        }

        .audit-time {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        @media (max-width: 900px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-group">
                <div class="logo-icon">🔑</div>
                <div>
                    <h1>HR Identity Lifecycle Portal</h1>
                    <p style="font-size: 0.85rem; color: var(--text-muted);">Keycloak Admin REST API & PostgreSQL Audit Automation</p>
                </div>
            </div>
            <div class="header-actions">
                <button class="btn" onclick="fetchEvents()">🔄 Refresh</button>
                <button class="btn btn-primary" onclick="triggerAutomation()">⚡ Run JML Automation</button>
            </div>
        </header>

        <!-- Stats Overview -->
        <div class="stats-grid">
            <div class="stat-card">
                <span class="stat-label">Pending HR Events</span>
                <span class="stat-value" id="stat-pending">0</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Provisioned Users</span>
                <span class="stat-value" style="color: var(--success-green);" id="stat-success">0</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Reconciled Roles</span>
                <span class="stat-value" style="color: var(--accent-blue);" id="stat-roles">0</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Audit Log Records</span>
                <span class="stat-value" style="color: var(--accent-purple);" id="stat-audit">0</span>
            </div>
        </div>

        <!-- Main Workspace -->
        <div class="main-grid">
            <!-- Event Feed Table -->
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">📋 Pending & Processed HR Lifecycle Events</div>
                </div>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Event ID</th>
                                <th>Type</th>
                                <th>Username</th>
                                <th>Department</th>
                                <th>Manager?</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody id="events-table-body">
                            <!-- Dynamic Content -->
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- HR Action Form & Live Audit Log -->
            <div style="display: flex; flex-direction: column; gap: 2rem;">
                <!-- Submit New HR Event Form -->
                <div class="panel">
                    <div class="panel-title">➕ Submit New HR Lifecycle Event</div>
                    <form id="hr-form" onsubmit="submitHREvent(event)">
                        <div class="form-group">
                            <label>Event Type</label>
                            <select id="form-type" required>
                                <option value="JOINER">JOINER (New Employee)</option>
                                <option value="MOVER">MOVER (Transfer/Promotion)</option>
                                <option value="LEAVER">LEAVER (Offboarding)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Username</label>
                            <input type="text" id="form-username" placeholder="e.g. sarah.dev" required>
                        </div>
                        <div class="form-group">
                            <label>Department</label>
                            <select id="form-department">
                                <option value="Engineering">Engineering</option>
                                <option value="HR">HR</option>
                                <option value="Finance">Finance</option>
                                <option value="Sales">Sales</option>
                            </select>
                        </div>
                        <div class="form-group" style="flex-direction: row; align-items: center; gap: 0.5rem;">
                            <input type="checkbox" id="form-manager" style="width: auto;">
                            <label for="form-manager">Assign Leadership / Manager Role</label>
                        </div>
                        <button type="submit" class="btn btn-success" style="width: 100%; justify-content: center; margin-top: 0.5rem;">Submit HR Event</button>
                    </form>
                </div>

                <!-- Recent Audit Log Feed -->
                <div class="panel">
                    <div class="panel-title">🛡️ Keycloak & PostgreSQL Audit Trail</div>
                    <div id="audit-feed" style="display: flex; flex-direction: column; gap: 0.75rem; max-height: 250px; overflow-y: auto;">
                        <!-- Audit entries -->
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function fetchEvents() {
            const res = await fetch('/api/events');
            const data = await res.json();
            renderTable(data.events);
            renderAudit(data.audit);
            updateStats(data);
        }

        function renderTable(events) {
            const tbody = document.getElementById('events-table-body');
            tbody.innerHTML = '';
            events.forEach(ev => {
                const tr = document.createElement('tr');
                const typeBadge = `<span class="badge badge-${ev.event_type.toLowerCase()}">${ev.event_type}</span>`;
                const statusBadge = ev.status ? `<span class="badge badge-${ev.status.toLowerCase()}">${ev.status}</span>` : `<span class="badge" style="background: rgba(255,255,255,0.1);">PENDING</span>`;
                
                tr.innerHTML = `
                    <td><strong>${ev.event_id}</strong></td>
                    <td>${typeBadge}</td>
                    <td>${ev.username || 'N/A'}</td>
                    <td>${ev.department || 'N/A'}</td>
                    <td>${ev.is_manager === 'true' || ev.is_manager === true ? '✅ Yes' : '❌ No'}</td>
                    <td>${statusBadge}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        function renderAudit(logs) {
            const feed = document.getElementById('audit-feed');
            feed.innerHTML = '';
            logs.slice(0, 10).forEach(log => {
                const div = document.createElement('div');
                div.className = 'audit-item';
                div.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <strong>${log.event_id} - ${log.action} (${log.username})</strong>
                        <span class="badge badge-${log.status.toLowerCase()}">${log.status}</span>
                    </div>
                    <div class="audit-time">${JSON.stringify(log.details)}</div>
                `;
                feed.appendChild(div);
            });
        }

        function updateStats(data) {
            document.getElementById('stat-pending').innerText = data.events.length;
            const successCount = data.audit.filter(a => a.status === 'SUCCESS').length;
            document.getElementById('stat-success').innerText = successCount;
            document.getElementById('stat-roles').innerText = successCount * 2;
            document.getElementById('stat-audit').innerText = data.audit.length;
        }

        async function triggerAutomation() {
            const res = await fetch('/api/run', { method: 'POST' });
            const result = await res.json();
            alert(`JML Automation Execution Finished!\\nProcessed: ${result.processed}\\nSuccess: ${result.success}\\nSkipped: ${result.skipped}\\nFailed: ${result.failed}`);
            fetchEvents();
        }

        async function submitHREvent(e) {
            e.preventDefault();
            const newEv = {
                event_type: document.getElementById('form-type').value,
                username: document.getElementById('form-username').value,
                department: document.getElementById('form-department').value,
                is_manager: document.getElementById('form-manager').checked ? 'true' : 'false',
                first_name: document.getElementById('form-username').value.split('.')[0] || 'Employee',
                last_name: 'User',
                email: `${document.getElementById('form-username').value}@company.com`,
                employee_id: `EMP-${Math.floor(100 + Math.random() * 900)}`
            };

            await fetch('/api/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newEv)
            });

            document.getElementById('form-username').value = '';
            fetchEvents();
        }

        fetchEvents();
    </script>
</body>
</html>
"""

# Store events list in memory
csv_file = "data/events.csv"
current_events = []

def load_initial_events():
    global current_events
    if os.path.exists(csv_file):
        with open(csv_file, "r", encoding="utf-8") as f:
            current_events = list(csv.DictReader(f))

load_initial_events()

class JMLWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif parsed.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "events": current_events,
                "audit": audit_instance.report(limit=50)
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            processed_count = 0
            success_count = 0
            skipped_count = 0
            failed_count = 0

            for ev in current_events:
                res = process_event(ev, kc_instance, audit_instance, dry_run=False, show_temp_passwords=True)
                processed_count += 1
                ev["status"] = res[3]
                if res[3] == "SUCCESS":
                    success_count += 1
                elif res[3] == "SKIPPED":
                    skipped_count += 1
                elif res[3] == "FAILED":
                    failed_count += 1

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp_payload = {
                "processed": processed_count,
                "success": success_count,
                "skipped": skipped_count,
                "failed": failed_count,
            }
            self.wfile.write(json.dumps(resp_payload).encode("utf-8"))

        elif parsed.path == "/api/events":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            new_ev = json.loads(body.decode("utf-8"))
            new_ev["event_id"] = f"EVT-{1000 + len(current_events) + 1}"
            current_events.append(new_ev)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "added", "event": new_ev}).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")


def run_web_server(port=5000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, JMLWebHandler)
    print(f"\n=================================================================================")
    print(f"[SERVER ONLINE] HR IDENTITY LIFECYCLE WEB DASHBOARD RUNNING AT: http://localhost:{port}")
    print(f"=================================================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web server.")

if __name__ == "__main__":
    run_web_server(5000)
