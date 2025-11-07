# hosts.py
import json
import os
from typing import Dict
from utils import logger

HOSTS_FILE = "hosts.json"


def load_hosts() -> Dict[str, str]:
    """Return mapping nickname -> ip"""
    if not os.path.exists(HOSTS_FILE):
        return {}
    try:
        with open(HOSTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load hosts.json")
        return {}


def save_hosts(hosts: Dict[str, str]) -> None:
    """Persist hosts mapping to disk"""
    try:
        with open(HOSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(hosts, f, indent=2, ensure_ascii=False)
        logger.info("hosts.json updated")
    except Exception:
        logger.exception("Failed to save hosts.json")
