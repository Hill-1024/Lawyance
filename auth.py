import os
import json
import time
import hmac
import hashlib
import base64

SECRET_KEY = os.environ.get("SECRET_KEY", "gdut-lawyer-secret-key")

DATA_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)
ACCOUNT_FILE = os.path.join(DATA_DIR, "account.json")
LOCKOUT_FILE = os.path.join(DATA_DIR, "lockout.json")

# Ensure account file exists
if not os.path.exists(ACCOUNT_FILE):
    with open(ACCOUNT_FILE, "w") as f:
        # Default user: admin, password: password
        f.write('{\n    "admin": {"hash": "cf632ecdd2c9b4e67cd76de4db6b785d$12b8bd1ec5414d7a46abf6b92a4bc0319ca7b9662bba71bc9776dcbefc4c0177", "role": "admin"}\n}')

def get_accounts_data():
    try:
        with open(ACCOUNT_FILE, "r") as f:
            accounts = json.load(f)
    except Exception:
        return {}
        
    # migrate old format
    dirty = False
    for k, v in accounts.items():
        if isinstance(v, str):
            role = "admin" if k == "admin" else "user"
            accounts[k] = {"hash": v, "role": role}
            dirty = True
            
    if dirty:
        with open(ACCOUNT_FILE, "w") as f:
            json.dump(accounts, f, indent=4)
            
    return accounts

def get_user_role(username: str) -> str:
    accounts = get_accounts_data()
    user_data = accounts.get(username)
    if user_data:
        return user_data.get("role", "user")
    return "user"

def list_accounts() -> list:
    accounts = get_accounts_data()
    return [{"username": k, "role": v.get("role", "user")} for k, v in accounts.items()]

def add_or_update_account(username: str, password: str, role: str = "user") -> tuple[bool, str]:
    if len(password) < 6:
        return False, "密码长度不能小于6位"
        
    accounts = get_accounts_data()
    
    salt = os.urandom(16).hex()
    actual_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    hashed_password = f"{salt}${actual_hash}"
    
    if username in accounts and accounts[username].get("role") == "admin":
        role = "admin"
        
    accounts[username] = {"hash": hashed_password, "role": role}
    
    try:
        with open(ACCOUNT_FILE, "w") as f:
            json.dump(accounts, f, indent=4)
        return True, "操作成功"
    except Exception as e:
        return False, f"保存失败: {str(e)}"
def delete_account(username: str) -> tuple[bool, str]:
    if username == "admin":
        return False, "不能删除系统管理员账号"
        
    accounts = get_accounts_data()
    if username not in accounts:
        return False, "账号不存在"
        
    try:
        del accounts[username]
        with open(ACCOUNT_FILE, "w") as f:
            json.dump(accounts, f, indent=4)
        return True, "账号已删除"
    except Exception as e:
        return False, f"删除失败: {str(e)}"

def verify_password(password: str, hashed_password: str) -> bool:
    try:
        salt, expected_hash = hashed_password.split('$')
        actual_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
        return hmac.compare_digest(actual_hash, expected_hash)
    except ValueError:
        return False

def create_token(username: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode('utf-8').rstrip('=')
    payload_dict = {"sub": username, "exp": int(time.time()) + 7 * 24 * 3600} # 7 days
    payload = base64.urlsafe_b64encode(json.dumps(payload_dict).encode('utf-8')).decode('utf-8').rstrip('=')
    signature = base64.urlsafe_b64encode(
        hmac.new(SECRET_KEY.encode('utf-8'), f"{header}.{payload}".encode('utf-8'), hashlib.sha256).digest()
    ).decode('utf-8').rstrip('=')
    return f"{header}.{payload}.{signature}"

def verify_token(token: str) -> str:
    if not token:
        return None
    try:
        header, payload, signature = token.split('.')
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(SECRET_KEY.encode('utf-8'), f"{header}.{payload}".encode('utf-8'), hashlib.sha256).digest()
        ).decode('utf-8').rstrip('=')
        if not hmac.compare_digest(signature, expected_signature):
            return None
        # Add padding back
        payload += '=' * (-len(payload) % 4)
        payload_dict = json.loads(base64.urlsafe_b64decode(payload.encode('utf-8')))
        if payload_dict["exp"] < time.time():
            return None
        return payload_dict["sub"]
    except Exception:
        return None

def check_lockout(username: str) -> str:
    # returns error message if locked, else None
    if not os.path.exists(LOCKOUT_FILE):
        return None
    try:
        with open(LOCKOUT_FILE, "r") as f:
            lockouts = json.load(f)
        record = lockouts.get(username)
        if not record:
            return None
        if record.get("locked_until", 0) > time.time():
            remain = int((record["locked_until"] - time.time()) / 60) + 1
            return f"账户已被锁定，请 {remain} 分钟后再试。"
        return None
    except Exception:
        return None

def record_login_attempt(username: str, success: bool):
    try:
        if os.path.exists(LOCKOUT_FILE):
            with open(LOCKOUT_FILE, "r") as f:
                lockouts = json.load(f)
        else:
            lockouts = {}
            
        if success:
            if username in lockouts:
                del lockouts[username]
        else:
            record = lockouts.get(username, {"fails": 0, "locked_until": 0})
            if record["locked_until"] <= time.time():
                if record["locked_until"] > 0:
                    record["fails"] = 0
                    record["locked_until"] = 0
                record["fails"] += 1
                if record["fails"] >= 3:
                    record["locked_until"] = int(time.time() + 2 * 3600) # 2 hours
            lockouts[username] = record
            
        with open(LOCKOUT_FILE, "w") as f:
            json.dump(lockouts, f)
    except Exception as e:
        print(f"Error recording login attempt: {e}")

def authenticate_user(username, password):
    lock_msg = check_lockout(username)
    if lock_msg:
        return False, lock_msg
        
    accounts = get_accounts_data()
    if not accounts:
        return False, "账号系统配置错误，请联系管理员"
        
    user_data = accounts.get(username)
    if not user_data:
        record_login_attempt(username, False)
        return False, "用户名或密码错误"
        
    hashed = user_data.get("hash")
    if verify_password(password, hashed):
        record_login_attempt(username, True)
        return True, "登录成功"
    else:
        record_login_attempt(username, False)
        return False, "用户名或密码错误"
