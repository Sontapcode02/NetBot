# knowledge.py
from typing import List, Optional
import json
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import pyodbc
from utils import logger

EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")

def create_embedding(text: str) -> Optional[List[float]]:
    """Return embedding vector list or None on failure."""
    try:
        emb = EMBED_MODEL.encode([text])[0].tolist()
        return emb
    except Exception:
        logger.exception("Failed to create embedding")
        return None

def ensure_kb_table(conn):
    cur = conn.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='KnowledgeBase' AND xtype='U')
    CREATE TABLE KnowledgeBase (
        Id INT IDENTITY(1,1) PRIMARY KEY,
        Category NVARCHAR(100),
        Text NVARCHAR(MAX),
        Embedding NVARCHAR(MAX),
        CreatedAt DATETIME DEFAULT GETDATE()
    )
    """)
    conn.commit()

def save_knowledge(category: str, text: str, conn_str: str):
    emb = create_embedding(text)
    if emb is None:
        raise RuntimeError("Embedding failed")
    conn = pyodbc.connect(conn_str)
    ensure_kb_table(conn)
    cur = conn.cursor()
    cur.execute("INSERT INTO KnowledgeBase (Category, Text, Embedding) VALUES (?, ?, ?)",
                (category, text, json.dumps(emb)))
    conn.commit()
    conn.close()
    logger.info("Saved knowledge chunk: %s", text[:60])

def search_knowledge(query: str, conn_str: str, top_k: int = 3) -> List[str]:
    q_emb = create_embedding(query)
    if q_emb is None:
        return []
    conn = pyodbc.connect(conn_str)
    cur = conn.cursor()
    cur.execute("SELECT Text, Embedding FROM KnowledgeBase")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return []

    texts, embs = [], []
    for text, emb_json in rows:
        try:
            emb = json.loads(emb_json)
            if isinstance(emb, list) and len(emb):
                texts.append(text)
                embs.append(emb)
        except Exception:
            continue

    if not embs:
        return []

    sims = cosine_similarity(np.array([q_emb]), np.array(embs))[0]
    idx = sims.argsort()[::-1][:top_k]
    return [texts[i] for i in idx]

def learn_file_to_db(filename: str, db_server: str, db_name: str, chunk_size: int = 500) -> int:
    conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={db_server};DATABASE={db_name};Trusted_Connection=yes;"
    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    conn = pyodbc.connect(conn_str)
    ensure_kb_table(conn)
    cur = conn.cursor()
    for chunk in chunks:
        emb = create_embedding(chunk)
        if emb:
            cur.execute("INSERT INTO KnowledgeBase (Category, Text, Embedding) VALUES (?, ?, ?)",
                        ("learned", chunk, json.dumps(emb)))
    conn.commit()
    conn.close()
    logger.info("Learned %d chunks from %s", len(chunks), filename)
    return len(chunks)
