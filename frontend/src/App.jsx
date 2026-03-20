import { useState, useRef, useEffect, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ── Helpers ──────────────────────────────────────────────────────────────────
function cls(...c) { return c.filter(Boolean).join(" "); }
const NOT_FOUND_MARKER = "I couldn't find an answer";

function formatAnswer(text) {
  return text.replace(/([\(\[](?:Page|Chapter):?\s*[^\)\]]+[\)\]])/gi, "**$1**");
}

function renderMd(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} className="text-indigo-300 font-semibold">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>
  );
}

// ── Token storage ─────────────────────────────────────────────────────────────
const TOKEN_KEY = "bookrag_token";
const USER_KEY  = "bookrag_user";
function saveAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
function loadAuth() {
  const token = localStorage.getItem(TOKEN_KEY);
  const user  = JSON.parse(localStorage.getItem(USER_KEY) || "null");
  return { token, user };
}

// Wrapper that injects the Bearer token automatically
async function apiFetch(path, opts = {}, token = null) {
  const headers = { ...(opts.headers || {}), };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    opts = { ...opts, body: JSON.stringify(opts.body) };
  }
  return fetch(`${API}${path}`, { ...opts, headers });
}

// ── Spinner ───────────────────────────────────────────────────────────────────
function Spinner({ size = "h-5 w-5" }) {
  return (
    <svg className={`animate-spin ${size} text-indigo-400`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

// ── Auth Form (Login + Register) ──────────────────────────────────────────────
function AuthScreen({ onAuth }) {
  const [tab, setTab]         = useState("login");
  const [email, setEmail]     = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const path = tab === "login" ? "/auth/login" : "/auth/register";
      const res  = await apiFetch(path, { method: "POST", body: { email, password } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Something went wrong.");
      saveAuth(data.access_token, data.user);
      onAuth(data.access_token, data.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-700/50 backdrop-blur-lg bg-slate-900/60">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center text-lg shadow-lg shadow-indigo-500/25">📖</div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-white">BookRAG</h1>
            <p className="text-xs text-slate-400">Upload a book. Ask anything. Get cited answers.</p>
          </div>
        </div>
      </header>

      {/* Auth Card */}
      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          {/* Card */}
          <div className="bg-slate-900/80 backdrop-blur-sm border border-slate-700/60 rounded-2xl shadow-2xl shadow-indigo-500/5 overflow-hidden">
            {/* Tabs */}
            <div className="flex border-b border-slate-700/60">
              {["login", "register"].map((t) => (
                <button
                  key={t}
                  onClick={() => { setTab(t); setError(null); }}
                  className={cls(
                    "flex-1 py-3.5 text-sm font-medium transition-colors capitalize",
                    tab === t
                      ? "text-indigo-300 bg-indigo-500/10 border-b-2 border-indigo-500"
                      : "text-slate-400 hover:text-slate-200"
                  )}
                >
                  {t === "login" ? "Sign In" : "Create Account"}
                </button>
              ))}
            </div>

            <form onSubmit={submit} className="p-6 space-y-4">
              {/* Welcome text */}
              <div className="text-center mb-2">
                <p className="text-slate-400 text-sm">
                  {tab === "login" ? "Welcome back! Sign in to your library." : "Create your account to get started."}
                </p>
              </div>

              <div className="space-y-1">
                <label className="text-xs text-slate-400 font-medium">Email</label>
                <input
                  type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full bg-slate-800/60 border border-slate-700/60 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-indigo-500/70 focus:ring-1 focus:ring-indigo-500/40 transition-all"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs text-slate-400 font-medium">Password</label>
                <input
                  type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-slate-800/60 border border-slate-700/60 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-indigo-500/70 focus:ring-1 focus:ring-indigo-500/40 transition-all"
                />
                {tab === "register" && (
                  <p className="text-xs text-slate-500 mt-1">Minimum 6 characters.</p>
                )}
              </div>

              {error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-2.5 text-xs text-red-300">
                  ⚠ {error}
                </div>
              )}

              <button
                type="submit" disabled={loading}
                className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors shadow-lg shadow-indigo-500/25 flex items-center justify-center gap-2 mt-2"
              >
                {loading ? <><Spinner size="h-4 w-4" /> Processing…</> : (tab === "login" ? "Sign In" : "Create Account")}
              </button>
            </form>
          </div>

          <p className="text-center text-xs text-slate-600 mt-4">
            {tab === "login"
              ? <span>No account? <button onClick={() => setTab("register")} className="text-indigo-400 hover:underline">Create one</button></span>
              : <span>Already have one? <button onClick={() => setTab("login")} className="text-indigo-400 hover:underline">Sign in</button></span>
            }
          </p>
        </div>
      </main>
    </div>
  );
}

// ── Progress Bar ───────────────────────────────────────────────────────────────
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

// ── File Upload ────────────────────────────────────────────────────────────────
const ACCEPT = ".pdf,.docx,.epub,.txt,.html,.htm";

function FileUpload({ onUploaded, disabled, token }) {
  const [dragging, setDragging]   = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress]   = useState(0);
  const [progressMsg, setProgressMsg] = useState("Starting…");
  const [error, setError]         = useState(null);
  const inputRef = useRef();
  const pollRef  = useRef(null);

  const stopPolling = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

  const pollProgress = useCallback((jobId) => {
    pollRef.current = setInterval(async () => {
      try {
        const res  = await apiFetch(`/progress/${jobId}`, {}, token);
        const data = await res.json();
        setProgress(data.progress ?? 0);
        setProgressMsg(data.message ?? "Processing…");
        if (data.status === "done")        { stopPolling(); setUploading(false); onUploaded(data.result); }
        else if (data.status === "error")  { stopPolling(); setUploading(false); setError(data.error || "Ingestion failed."); }
      } catch { /* network hiccup — keep polling */ }
    }, 800);
  }, [onUploaded, token]);

  async function handleFiles(fileList) {
    const file = fileList[0];
    if (!file) return;
    setError(null); setProgress(0); setProgressMsg("Uploading file…"); setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiFetch("/upload", { method: "POST", body: form }, token);
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.statusText); }
      const { job_id } = await res.json();
      pollProgress(job_id);
    } catch (e) { setUploading(false); setError(e.message); }
  }

  useEffect(() => () => stopPolling(), []);

  return (
    <div
      onClick={() => !disabled && !uploading && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}
      className={cls(
        "relative border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all duration-300",
        dragging ? "border-indigo-400 bg-indigo-500/10" : "border-slate-600 hover:border-indigo-500/60 hover:bg-slate-800/60",
        disabled && "opacity-50 pointer-events-none"
      )}
    >
      <input ref={inputRef} type="file" accept={ACCEPT} className="hidden" onChange={(e) => handleFiles(e.target.files)} />
      {uploading ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-center gap-2 text-slate-300">
            <Spinner /> <span className="text-sm font-medium">Processing your book…</span>
          </div>
          <ProgressBar progress={progress} message={progressMsg} />
        </div>
      ) : (
        <>
          <div className="mx-auto w-14 h-14 rounded-full bg-indigo-500/20 flex items-center justify-center mb-4">
            <svg className="w-7 h-7 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
          </div>
          <p className="text-slate-200 font-medium">Drag & drop your book, or <span className="text-indigo-400 underline">browse</span></p>
          <p className="text-slate-400 text-sm mt-1">PDF · DOCX · EPUB · TXT · HTML</p>
        </>
      )}
      {error && <p className="text-red-400 text-sm mt-3">⚠ {error}</p>}
    </div>
  );
}

// ── Chat Bubble ────────────────────────────────────────────────────────────────
function ChatBubble({ role, text }) {
  const isUser     = role === "user";
  const isNotFound = !isUser && text.includes(NOT_FOUND_MARKER);
  return (
    <div className={cls("flex", isUser ? "justify-end" : "justify-start")}>
      <div className={cls(
        "max-w-[80%] md:max-w-[70%] rounded-2xl px-5 py-3 text-sm leading-relaxed whitespace-pre-wrap shadow-lg",
        isUser     ? "bg-indigo-600 text-white rounded-br-none"
        : isNotFound ? "bg-amber-500/20 border border-amber-500/40 text-amber-200 rounded-bl-none"
                     : "bg-slate-700/80 text-slate-100 rounded-bl-none"
      )}>
        {isUser ? text : renderMd(formatAnswer(text))}
      </div>
    </div>
  );
}

// ── Main App (authenticated) ──────────────────────────────────────────────────
function MainApp({ token, user, onLogout }) {
  const [book, setBook]       = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput]     = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef();

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  async function sendMessage(e) {
    e?.preventDefault();
    const q = input.trim();
    if (!q || !book) return;
    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setInput(""); setLoading(true);
    try {
      const res = await apiFetch("/chat", {
        method: "POST",
        body: { question: q, collection_id: book.collection_id, book_title: book.book_title },
      }, token);
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.statusText); }
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "bot", text: data.answer }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "bot", text: `Error: ${err.message}` }]);
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-700/50 backdrop-blur-lg bg-slate-900/60 sticky top-0 z-20">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center text-lg font-bold shadow-lg shadow-indigo-500/25">📖</div>
          <div className="flex-1 min-w-0">
            <h1 className="text-base font-semibold tracking-tight">BookRAG</h1>
            <p className="text-xs text-slate-400 truncate">{user.email}</p>
          </div>
          <button
            onClick={onLogout}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-red-400 transition-colors px-3 py-1.5 rounded-lg hover:bg-red-500/10"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Sign Out
          </button>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-6 flex flex-col gap-6 overflow-hidden">
        <FileUpload
          token={token}
          onUploaded={(data) => { setBook(data); setMessages([]); }}
          disabled={loading}
        />

        {book && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-3 py-1 text-xs text-emerald-300">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" /> Ready to chat
            </span>
            <span className="text-sm text-slate-300 font-medium truncate">{book.book_title}</span>
            <span className="text-xs text-slate-500">· {book.chunk_count} chunks{book.already_existed && " (cached)"}</span>
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
                    <Spinner /> <span className="text-sm">Thinking…</span>
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
                value={input} onChange={(e) => setInput(e.target.value)}
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

// ── Root ───────────────────────────────────────────────────────────────────────
export default function App() {
  const [auth, setAuth] = useState(() => loadAuth());   // { token, user }

  function handleAuth(token, user) { setAuth({ token, user }); }
  function handleLogout() { clearAuth(); setAuth({ token: null, user: null }); }

  if (!auth.token || !auth.user) {
    return <AuthScreen onAuth={handleAuth} />;
  }
  return <MainApp token={auth.token} user={auth.user} onLogout={handleLogout} />;
}
