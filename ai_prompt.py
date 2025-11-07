# ai_prompt.py
from typing import List
from utils import logger
from knowledge import search_knowledge
import pyodbc
import os
import json

# NOTE: keep DB_SERVER/DB_NAME in env or pass them in; here we read env
DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
CONN_STR = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={DB_SERVER};DATABASE={DB_NAME};Trusted_Connection=yes;"

def get_user_history(user_id: int, limit: int = 10):
    """
    Fetch recent chat history for user from ChatHistory table.
    Returns list of {"role": "user"/"assistant", "content": "..."}.
    """
    try:
        conn = pyodbc.connect(CONN_STR)
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ChatHistory' AND xtype='U')
            CREATE TABLE ChatHistory (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                UserId BIGINT,
                Message NVARCHAR(MAX),
                Response NVARCHAR(MAX),
                Timestamp DATETIME DEFAULT GETDATE()
            )
        """)
        conn.commit()

        cur.execute("SELECT TOP (?) Message, Response FROM ChatHistory WHERE UserId=? ORDER BY Timestamp DESC", limit, user_id)
        rows = cur.fetchall()
        conn.close()
        history = []
        for row in reversed(rows):
            history.append({"role": "user", "content": row[0]})
            history.append({"role": "assistant", "content": row[1]})
        return history
    except Exception:
        logger.exception("Failed fetching user history")
        return []

async def build_prompt(user_id: int, question: str) -> str:
    """
    Build prompt text for the AI:
    - recent conversation history
    - top-k relevant knowledge search results
    """
    history = get_user_history(user_id, limit=10)
    history_text = "\n".join(f"{h['role'].capitalize()}: {h['content']}" for h in history)

    # search knowledge using DB env
    kb_results = search_knowledge(question, CONN_STR, top_k=3)
    kb_text = "\n".join(f"- {r}" for r in kb_results)

    prompt = f"""Relevant knowledge:
{kb_text}

Recent conversation:
{history_text}

User question: {question}

Answer clearly, concisely, and in a friendly tone. Prefer knowledge base information if available."""
    return prompt
