"""
chat.py — LLM answer generation with strict citation-driven system prompt.

Uses Groq's free API tier with Llama 3 for answer generation.
"""

import os
from typing import List, Dict, Any

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings

SYSTEM_PROMPT_TEMPLATE = """You are a precise, citation-driven assistant for the book: "{book_title}".
Your ONLY knowledge source is the [CONTEXT PASSAGES] below, retrieved from this book.
You have no access to outside knowledge and must not use any.

RULES:
1. Answer ONLY from the provided context passages.
   If the answer is not present, respond EXACTLY with:
   "I couldn't find an answer to that in '{book_title}'. The book may not cover this topic, or it may be phrased differently."
2. Cite the page number as: (Page Y). If missing, use: (Chapter X).
3. Do NOT repeat the same page citation consecutively. If multiple consecutive sentences or bullet points come from the same page, only cite the page ONCE at the end of the block or sentence.
4. Do NOT cite passages by number (e.g. avoid saying Passage 1).
5. Paraphrase over quoting. Direct quotes must be under 20 words.
6. Never infer, speculate, or use outside knowledge.
7. No filler phrases. Be direct.

[CONTEXT PASSAGES]
{retrieved_chunks}

User Question: {user_question}"""


# --------------------------------------------------------------------------
# LLM setup — lazy init so server starts even if GROQ_API_KEY isn't set yet
# --------------------------------------------------------------------------
_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGroq(
            model=settings.GROQ_MODEL,
            temperature=0,
            api_key=settings.GROQ_API_KEY,
        )
    return _llm


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def generate_answer(
    user_question: str,
    retrieved_chunks: List[Dict[str, Any]],
    book_title: str,
) -> str:
    """
    Build the citation-driven prompt from *retrieved_chunks* and call the LLM.
    Returns the answer string.
    """
    formatted_chunks = []
    for chunk in retrieved_chunks:
        chapter = chunk.get("chapter", "Unknown")
        page = chunk.get("page_number", "N/A")
        text = chunk.get("text", "")
        formatted_chunks.append(
            f"(Source - Chapter: {chapter}, Page: {page})\n{text}"
        )

    chunks_text = "\n\n".join(formatted_chunks)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        book_title=book_title,
        retrieved_chunks=chunks_text,
        user_question=user_question,
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_question),
    ]

    response = _get_llm().invoke(messages)
    return response.content
