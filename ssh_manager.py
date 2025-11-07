# ssh_manager.py
import json
import os
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
import paramiko
from utils import logger

CREDENTIALS_FILE = "SSH_CREDENTIALS.json"
SECRET_KEY_FILE = "secret.key"


def _ensure_fernet() -> Optional[Fernet]:
    """
    Load or generate a Fernet key file and return Fernet instance.
    """
    try:
        if not os.path.exists(SECRET_KEY_FILE):
            key = Fernet.generate_key()
            with open(SECRET_KEY_FILE, "wb") as f:
                f.write(key)
            logger.info("Generated new Fernet key")
        with open(SECRET_KEY_FILE, "rb") as f:
            key = f.read().strip()
        return Fernet(key)
    except Exception:
        logger.exception("Failed to initialize Fernet")
        return None


def load_ssh_credentials() -> Dict[str, Dict[str, str]]:
    """
    Load credentials JSON and decrypt passwords.
    Returns: { "ip": {"username": "...", "password": "..."}, ...}
    """
    if not os.path.exists(CREDENTIALS_FILE):
        return {}
    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        logger.exception("Failed to read credentials file")
        return {}

    fernet = _ensure_fernet()
    if not fernet:
        return {}

    out = {}
    for host, creds in raw.items():
        user = creds.get("username", "")
        pw_enc = creds.get("password", "")
        pw = ""
        if pw_enc:
            try:
                pw = fernet.decrypt(pw_enc.encode()).decode()
            except Exception:
                logger.warning("Failed to decrypt password for %s", host)
                pw = ""
        out[host] = {"username": user, "password": pw}
    return out


def save_ssh_credentials(creds: Dict[str, Dict[str, str]]) -> None:
    """
    Encrypt passwords and write credentials JSON.
    Input: same structure as load_ssh_credentials returns (passwords plain).
    """
    fernet = _ensure_fernet()
    if not fernet:
        raise RuntimeError("No Fernet available")

    # load existing to merge
    existing = {}
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    for host, data in creds.items():
        username = data.get("username", "")
        password = data.get("password", "")
        enc_pw = fernet.encrypt(password.encode()).decode() if password else ""
        existing[host] = {"username": username, "password": enc_pw}

    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    logger.info("Saved encrypted credentials to %s", CREDENTIALS_FILE)


def run_ssh_command(host: str, username: str, password: str, command: str, timeout: int = 10) -> str:
    """
    Execute command via SSH using paramiko and return combined stdout/stderr.
    """
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=host, username=username, password=password, timeout=timeout,
                       look_for_keys=False, allow_agent=False)
        stdin, stdout, stderr = client.exec_command(command)
        out = stdout.read().decode()
        err = stderr.read().decode()
        client.close()
        if err.strip():
            return f"ERROR:\n{err.strip()}"
        return out.strip() or "OK (no output)"
    except Exception as e:
        logger.exception("SSH error")
        return f"SSH error: {e}"
