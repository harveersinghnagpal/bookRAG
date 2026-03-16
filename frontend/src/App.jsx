import { useState, useRef, useEffect, useCallback } from "react";

const API = "http://localhost:8000";

function classNames(...cls) {
  return cls.filter(Boolean).join(" ");
}

function formatAnswer(text) {
  return text.replace(
    /(\((?:Page|Chapter):?\s*[^)]+\)|\(Passage\s*\d+\))/gi,
    "**$1**"
  );
}

function renderMarkdownLite(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="text-indigo-300 font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

const NOT_FOUND_MARKER = "I couldn't find an answer";

/* ── Spinner ── */
function Spinner({ size = "h-5 w-5" }) {
  return (
    <svg className={`animate-spin ${size} text-indigo-400`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

/* ── Progress Bar ── */
function ProgressBar({ progress, message }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-between text-xs text-slate-400">
        <span>{message}</span>
        <span className="font-mono text-indigo-300">{progress}%</span>
      </div>
      <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 rounded-full transition-all duration-500 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

/* ── File Upload ── */
const ACCEPT = ".pdf,.docx,.epub,.txt,.html,.htm";

function FileUpload({ onUploaded, disabled }) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState("Starting…");
  const [error, setError] = useState(null);
  const inputRef = useRef();
  const pollRef = useRef(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const pollProgress = useCallback((jobId) => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/progress/${jobId}`);
        const data = await res.json();

        setProgress(data.progress ?? 0);
        setProgressMsg(data.message ?? "Processing…");

        if (data.status === "done") {
          stopPolling();
          setUploading(false);
          onUploaded(data.result);
        } else if (data.status === "error") {
          stopPolling();
          setUploading(false);
          setError(data.error || "Ingestion failed.");
        }
      } catch {
        // network hiccup — keep polling
      }
    }, 800);
  }, [onUploaded]);

  async function handleFiles(fileList) {
    const file = fileList[0];
    if (!file) return;
    setError(null);
    setProgress(0);
    setProgressMsg("Uploading file…");
    setUploading(true);

    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API}/upload`, { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const { job_id } = await res.json();
      pollProgress(job_id);
    } catch (e) {
      setUploading(false);
      setError(e.message);
    }
  }

  useEffect(() => () => stopPolling(), []);

  return (
    <div
      onClick={() => !disabled && !uploading && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}
      className={classNames(
        "relative border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all duration-300",
        dragging ? "border-indigo-400 bg-indigo-500/10" : "border-slate-600 hover:border-indigo-500/60 hover:bg-slate-800/60",
        disabled && "opacity-50 pointer-events-none"
      )}
    >
      <input ref={inputRef} type="file" accept={ACCEPT} className="hidden" onChange={(e) => handleFiles(e.target.files)} />

      {uploading ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-center gap-2 text-slate-300">
            <Spinner />
            <span className="text-sm font-medium">Processing your book…</span>
          </div>
          <ProgressBar progress={progress} message={progressMsg} />
        </div>
      ) : (
        <>
          <div className="mx-auto w-14 h-14 rounded-full bg-indigo-500/20 flex items-center justify-center mb-4">
            <svg className="w-7 h-7 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
          </div>
          <p className="text-slate-200 font-medium">
            Drag & drop your book here, or{" "}
            <span className="text-indigo-400 underline">browse</span>
          </p>
          <p className="text-slate-400 text-sm mt-1">PDF · DOCX · EPUB · TXT · HTML</p>
        </>
      )}
      {error && <p className="text-red-400 text-sm mt-3">⚠ {error}</p>}
    </div>
  );
}

/* ── Chat Bubble ── */
function ChatBubble({ role, text }) {
  const isUser = role === "user";
  const isNotFound = !isUser && text.includes(NOT_FOUND_MARKER);
  return (
    <div className={classNames("flex", isUser ? "justify-end" : "justify-start")}>
      <div className={classNames(
        "max-w-[80%] md:max-w-[70%] rounded-2xl px-5 py-3 text-sm leading-relaxed whitespace-pre-wrap shadow-lg",
        isUser ? "bg-indigo-600 text-white rounded-br-none"
          : isNotFound ? "bg-amber-500/20 border border-amber-500/40 text-amber-200 rounded-bl-none"
            : "bg-slate-700/80 text-slate-100 rounded-bl-none"
      )}>
        {isUser ? text : renderMarkdownLite(formatAnswer(text))}
      </div>
    </div>
  );
}

/* ── Main App ── */
export default function App() {
  const [book, setBook] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage(e) {
    e?.preventDefault();
    const q = input.trim();
    if (!q || !book) return;
    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, collection_id: book.collection_id, book_title: book.book_title }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "bot", text: data.answer }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "bot", text: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-700/50 backdrop-blur-lg bg-slate-900/60 sticky top-0 z-20">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center text-lg font-bold shadow-lg shadow-indigo-500/25">
            📖
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">BookRAG</h1>
            <p className="text-xs text-slate-400">Upload a book. Ask anything. Get cited answers.</p>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-6 flex flex-col gap-6 overflow-hidden">
        <FileUpload onUploaded={(data) => { setBook(data); setMessages([]); }} disabled={loading} />

        {book && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-3 py-1 text-xs text-emerald-300">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              Ready to chat
            </span>
            <span className="text-sm text-slate-300 font-medium truncate">{book.book_title}</span>
            <span className="text-xs text-slate-500">
              · {book.chunk_count} chunks{book.already_existed && " (cached)"}
            </span>
          </div>
        )}

        {book && (
          <div className="flex-1 flex flex-col min-h-0">
            <div className="flex-1 overflow-y-auto space-y-4 pr-1 pb-2">
              {messages.length === 0 && (
                <p className="text-center text-slate-500 text-sm mt-10">
                  Ask a question about <span className="text-slate-300 font-medium">{book.book_title}</span>
                </p>
              )}
              {messages.map((m, i) => <ChatBubble key={i} role={m.role} text={m.text} />)}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-slate-700/80 rounded-2xl rounded-bl-none px-5 py-3 shadow-lg flex items-center gap-2 text-slate-400">
                    <Spinner />
                    <span className="text-sm">Thinking…</span>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            <form onSubmit={sendMessage}
              className="mt-3 flex items-center gap-2 bg-slate-800/70 border border-slate-700/60 rounded-2xl px-4 py-2 focus-within:border-indigo-500/60 transition-colors">
              <input
                className="flex-1 bg-transparent outline-none text-sm text-slate-100 placeholder-slate-500"
                placeholder="Ask a question about the book…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={loading}
              />
              <button type="submit" disabled={loading || !input.trim()}
                className="w-9 h-9 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors shadow-md shadow-indigo-500/20">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              </button>
            </form>
          </div>
        )}
      </main>

      <footer className="border-t border-slate-800/50 py-3 text-center text-xs text-slate-600">
        BookRAG — Answers sourced exclusively from your uploaded book
      </footer>
    </div>
  );
}
