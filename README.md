# BookRAG — Full-Stack RAG Chatbot

Upload a book (PDF, DOCX, EPUB, TXT, HTML) and ask questions about it. Answers are sourced **exclusively** from the book's content with inline citations.

---

## Tech Stack

| Layer          | Technology                                    |
| -------------- | --------------------------------------------- |
| Backend        | Python, FastAPI, LangChain                    |
| Embeddings     | OpenAI `text-embedding-3-small`               |
| Vector DB      | ChromaDB (persistent, local)                  |
| LLM            | OpenAI GPT-4o (swap to Anthropic via config)  |
| Parsers        | PyMuPDF, python-docx, ebooklib, BS4           |
| Frontend       | React + Vite + Tailwind CSS                   |

---

## Project Structure

```
bookRAG/
├── backend/
│   ├── main.py            # FastAPI server
│   ├── ingestion.py       # File parsing, chunking, embedding
│   ├── retriever.py       # Semantic search over ChromaDB
│   ├── chat.py            # LLM prompt + answer generation
│   ├── requirements.txt   # Python dependencies
│   └── .env.example       # Environment variable template
├── frontend/
│   ├── src/
│   │   └── App.jsx        # Single-file React UI
│   ├── package.json
│   └── vite.config.js
└── README.md
```

---

## Setup Instructions

### 1. Backend

```bash
cd backend

# Create and activate a virtual environment (optional but recommended)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux

# Edit .env and set your OpenAI API key
# OPENAI_API_KEY=sk-...


# Start the server
uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server (runs on http://localhost:3000)
npm run dev
```

### 3. Use the App

1. Open **http://localhost:3000** in your browser
2. Drag & drop (or click to browse) a book file
3. Wait for ingestion to complete
4. Ask questions in the chat — answers include inline citations

---

## Environment Variables

| Variable           | Required | Default           | Description                              |
| ------------------ | -------- | ----------------- | ---------------------------------------- |
| `OPENAI_API_KEY`   | ✅       | —                 | Your OpenAI API key                      |
| `CHROMA_PERSIST_DIR` | ❌     | `./chroma_store`  | Path for ChromaDB persistent storage     |
| `USE_ANTHROPIC`    | ❌       | `false`           | Set to `true` to use Claude instead      |
| `ANTHROPIC_API_KEY`| ❌       | —                 | Required if `USE_ANTHROPIC=true`         |

---

## API Endpoints

### `POST /upload`
Upload a book file for ingestion.

- **Body**: `multipart/form-data` with field `file`
- **Response**: `{ collection_id, book_title, chunk_count, already_existed }`

### `POST /chat`
Ask a question about an uploaded book.

- **Body**: `{ question, collection_id, book_title }`
- **Response**: `{ answer }`

### `GET /health`
Health check → `{ status: "ok" }`

---

## Key Design Decisions

- **No re-embedding**: If a book collection already exists in ChromaDB, it's reused instead of re-processed
- **Persistent vectors**: ChromaDB persists to disk so embeddings survive server restarts
- **Strict citation**: The system prompt enforces citation-only answers — the LLM cannot use outside knowledge
- **Chunk metadata**: Every chunk stores `book_title`, `page_number`, `chapter`, and `chunk_index` for traceable citations
