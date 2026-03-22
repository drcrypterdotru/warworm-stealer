"""
Process Manager Module - Collects all running processes on Windows
Uses threading for concurrent collection (3-5x faster)
"""

import os
import sys
import json
import psutil
import ctypes
import socket
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes

class ProcessManager:
    def __init__(self):
        self.processes = []
        self.errors = []
        self.lock = threading.Lock()
        self.collected_count = 0
        self.total_count = 0
        
    def get_process_details(self, proc_pid): # Extract detailed information from a process (thread-safe)
        try:
            proc = psutil.Process(proc_pid)
            
            # Quick check if process still exists
            if not proc.is_running():
                return None
                
            pinfo = {
                'pid': proc_pid,
                'name': proc.name(),
                'status': proc.status(),
                'created': datetime.fromtimestamp(proc.create_time()).strftime('%Y-%m-%d %H:%M:%S'),
                'cpu_percent': proc.cpu_percent(interval=0.05),  # Reduced interval for speed
                'memory_percent': round(proc.memory_percent(), 2),
                'memory_mb': round(proc.memory_info().rss / (1024 * 1024), 2),
                'threads': proc.num_threads(),
                'username': None,
                'exe': None,
                'cmdline': None,
                'cwd': None,
                'connections': [],
                'is_system': False,
                'is_admin': False
            }
            
            # Try to get username
            try:
                pinfo['username'] = proc.username()
                pinfo['is_system'] = 'SYSTEM' in pinfo['username'] or 'NT AUTHORITY' in pinfo['username']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pinfo['username'] = 'System/Protected'
                pinfo['is_system'] = True
            
            # Try to get executable path
            try:
                pinfo['exe'] = proc.exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pinfo['exe'] = 'Protected'
            
            # Try to get command line
            try:
                cmdline = proc.cmdline()
                pinfo['cmdline'] = ' '.join(cmdline) if cmdline else 'N/A'
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pinfo['cmdline'] = 'Protected'
            
            # Try to get current working directory
            try:
                pinfo['cwd'] = proc.cwd()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pinfo['cwd'] = 'Protected'
            
            
            try:
                # Get network connections
                connections = proc.net_connections(kind='inet')
                pinfo['connections'] = [{
                    'local': f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "N/A",
                    'remote': f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "N/A",
                    'status': c.status,
                    'type': 'TCP' if c.type == socket.SOCK_STREAM else 'UDP'
                } for c in connections[:3]]  # Reduced to 3 for speed
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
            
            return pinfo
            
        except psutil.NoSuchProcess:
            return None
        except Exception:
            return None
    
    def collect_all_processes(self, max_workers=20): # Collect all running processes using threading 
        print("[*] Collecting process information with threading...")
        
        # Get all PIDs first
        all_pids = psutil.pids()
        self.total_count = len(all_pids)
        print(f"    [*] Found {self.total_count} processes, scanning with {max_workers} threads...")
        
        # Use ThreadPoolExecutor for concurrent processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_pid = {executor.submit(self.get_process_details, pid): pid for pid in all_pids}
            
            # Process completed tasks as they finish
            for future in as_completed(future_to_pid):
                try:
                    result = future.result()
                    if result:
                        with self.lock:
                            self.processes.append(result)
                            self.collected_count += 1
                            
                            # Progress indicator every 50 processes
                            if self.collected_count % 50 == 0:
                                print(f"    [*] Collected {self.collected_count}/{self.total_count} processes...")
                                
                except Exception:
                    continue
        
        print(f"    [+] Successfully collected {self.collected_count} accessible processes")
        return self.processes
    
    def get_system_processes(self):
        # Get only system processes 
        return [p for p in self.processes if p.get('is_system', False)]
    
    def get_user_processes(self):
        # Get only user processes 
        return [p for p in self.processes if not p.get('is_system', False)]
    
    def get_high_resource_processes(self):
        # Get processes using high CPU or Memory 
        return [p for p in self.processes if p.get('cpu_percent', 0) > 5 or p.get('memory_percent', 0) > 2]
    
    def save_to_file(self, output_dir):
        #Save process list to formatted text file 
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        filepath = os.path.join(output_dir, "process_list.txt")
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                # Header
                f.write("=" * 100 + "\n")
                f.write(" " * 35 + "PROCESS MANAGER REPORT\n")
                f.write("=" * 100 + "\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total Processes: {len(self.processes)}\n")
                f.write(f"System Processes: {len(self.get_system_processes())}\n")
                f.write(f"User Processes: {len(self.get_user_processes())}\n")
                f.write("=" * 100 + "\n\n")
                
                # Summary Table
                f.write("SUMMARY:\n")
                f.write("-" * 100 + "\n")
                f.write(f"{'PID':<10} {'Name':<30} {'Status':<12} {'CPU%':<8} {'Memory MB':<12} {'User':<20}\n")
                f.write("-" * 100 + "\n")
                
                # Sort by memory usage
                sorted_procs = sorted(self.processes, key=lambda x: x.get('memory_mb', 0), reverse=True)
                
                for proc in sorted_procs:
                    name = proc['name'][:28] if len(proc['name']) > 28 else proc['name']
                    user = (proc['username'] or 'Unknown')[:18]
                    f.write(f"{proc['pid']:<10} {name:<30} {proc['status']:<12} "
                           f"{proc['cpu_percent']:<8} {proc['memory_mb']:<12} {user:<20}\n")
                
                # Detailed Section (Top 50 only to keep file size reasonable)
                f.write("\n\n" + "=" * 100 + "\n")
                f.write("DETAILED PROCESS INFORMATION (Top 50 by Memory)\n")
                f.write("=" * 100 + "\n\n")
                
                for proc in sorted_procs[:50]:
                    f.write(f"Process: {proc['name']} (PID: {proc['pid']})\n")
                    f.write("-" * 50 + "\n")
                    f.write(f"  Executable: {proc.get('exe', 'N/A')}\n")
                    f.write(f"  Command Line: {proc.get('cmdline', 'N/A')[:80]}...\n" if len(str(proc.get('cmdline', ''))) > 80 else f"  Command Line: {proc.get('cmdline', 'N/A')}\n")
                    f.write(f"  Working Dir: {proc.get('cwd', 'N/A')}\n")
                    f.write(f"  Started: {proc.get('created', 'Unknown')}\n")
                    f.write(f"  Status: {proc.get('status', 'Unknown')}\n")
                    f.write(f"  CPU Usage: {proc.get('cpu_percent', 0)}%\n")
                    f.write(f"  Memory: {proc.get('memory_mb', 0)} MB ({proc.get('memory_percent', 0)}%)\n")
                    f.write(f"  Threads: {proc.get('threads', 0)}\n")
                    f.write(f"  User: {proc.get('username', 'Unknown')}\n")
                    f.write(f"  System Process: {'Yes' if proc.get('is_system') else 'No'}\n")
                    
                    if proc.get('connections'):
                        f.write(f"  Network Connections:\n")
                        for conn in proc['connections']:
                            f.write(f"    - {conn['type']} {conn['local']} -> {conn['remote']} ({conn['status']})\n")
                    
                    f.write("\n")
                
                # High Resource Usage Section
                high_res = self.get_high_resource_processes()
                if high_res:
                    f.write("\n\n" + "=" * 100 + "\n")
                    f.write("HIGH RESOURCE USAGE PROCESSES (CPU > 5% OR Memory > 2%)\n")
                    f.write("=" * 100 + "\n\n")
                    
                    for proc in sorted(high_res, key=lambda x: x.get('memory_percent', 0), reverse=True):
                        f.write(f"[!] {proc['name']} (PID: {proc['pid']}) - "
                               f"CPU: {proc['cpu_percent']}% | Memory: {proc['memory_mb']} MB\n")
            
            print(f"    [+] Process list saved: {filepath}")
            
            # Also save as JSON for structured data
            json_path = os.path.join(output_dir, "process_list.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'metadata': {
                        'timestamp': datetime.now().isoformat(),
                        'total_processes': len(self.processes),
                        'system_processes': len(self.get_system_processes()),
                        'user_processes': len(self.get_user_processes())
                    },
                    'processes': self.processes
                }, f, indent=2, default=str)
            
            print(f"    [+] Process JSON saved: {json_path}")
            return filepath
            
        except Exception as e:
            print(f"    [!] Error saving process list: {e}")
            return None
    
    def get_summary(self):
        # Get quick summary for report generation 
        return {
            'total': len(self.processes),
            'system': len(self.get_system_processes()),
            'user': len(self.get_user_processes()),
            'high_resource': len(self.get_high_resource_processes())
        }

# Main function for standalone usage
def collect_processes(output_dir, max_workers=20):
    # Main entry point for process collection with threading 
    try:
        pm = ProcessManager()
        pm.collect_all_processes(max_workers=max_workers)
        filepath = pm.save_to_file(output_dir)
        return pm.get_summary()
    except Exception as e:
        print(f"[!] Process manager error: {e}")
        return {'error': str(e)}

# if __name__ == "__main__":
#     # Test mode with timing
#     import tempfile
#     import time
    
#     test_dir = tempfile.mkdtemp()
#     print(f"[*] Testing Process Manager in: {test_dir}")
    
#     start_time = time.time()
#     result = collect_processes(test_dir)
#     elapsed = time.time() - start_time
    
#     print(f"[*] Result: {result}")
#     print(f"[*] Time elapsed: {elapsed:.2f} seconds")