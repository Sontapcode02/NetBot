# utils.py
import logging
from typing import List

def setup_logging():
    fmt = "%(asctime)s %(levelname)s %(name)s - %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

import logging
logger = logging.getLogger("netbot")

def is_admin(user_id: int) -> bool:
    import os
    admins = os.getenv("ADMIN_USERS", "")
    if not admins:
        return False
    try:
        admin_list = [int(x.strip()) for x in admins.split(",") if x.strip()]
        return int(user_id) in admin_list
    except Exception:
        return False

def split_text(text: str, limit: int = 1900) -> List[str]:
    chunks = []
    while len(text) > limit:
        idx = text.rfind("\n", 0, limit)
        if idx == -1:
            idx = text.rfind(" ", 0, limit)
        if idx == -1:
            idx = limit
        chunks.append(text[:idx].strip())
        text = text[idx:].strip()
    if text:
        chunks.append(text)
    return chunks
