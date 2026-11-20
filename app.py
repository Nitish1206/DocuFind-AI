from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
DOCS = ROOT / "documents"
WEB = ROOT / "web"
SUPPORTED = {".txt", ".md"}
STOP = set("a an and are as at be by for from has have how i in is it of on or our that the this to we what when where which who why with your you".split())


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower()) if w not in STOP]


def passages(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    chunks = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 30]
    out = []
    for index, chunk in enumerate(chunks):
        # Keep retrieved context readable and bounded.
        for start in range(0, len(chunk), 1000):
            part = chunk[start:start + 1000].strip()
            if part:
                out.append({"source": path.name, "passage": index + 1, "text": part})
    return out


def retrieve(question: str, limit: int = 4) -> list[dict]:
    query = set(words(question))
    if not query:
        return []
    ranked = []
    for path in sorted(DOCS.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            for item in passages(path):
                body = set(words(item["text"]))
                overlap = query & body
                if overlap:
                    # Favor passages covering more distinct query terms.
                    score = sum(1 + min(item["text"].lower().count(term), 3) * 0.12 for term in overlap) / len(query)
                    ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [dict(item, score=round(score, 3)) for score, item in ranked[:limit] if score >= 0.08]


def local_answer(question: str, sources: list[dict]) -> str:
    if not sources:
        return "I couldn't find a matching passage in the approved documents. Try different keywords or add the relevant document to the library."
    query = set(words(question))
    candidates = []
    for source in sources:
        for sentence in re.split(r"(?<=[.!?])\s+", source["text"].replace("\n", " ")):
            sentence = sentence.strip()
            overlap = query & set(words(sentence))
            if len(sentence) > 30 and overlap:
                candidates.append((len(overlap) / max(len(query), 1), sentence, source["source"], source["passage"]))
    candidates.sort(reverse=True)
    chosen, seen = [], set()
    for _, sentence, source, passage in candidates:
        if sentence not in seen:
            chosen.append(f"{sentence} [{source}, passage {passage}]")
            seen.add(sentence)
        if len(chosen) == 3:
            break
    if not chosen:
        return "I found related material, but it doesn't state a direct answer. Review the cited passages below."
    return " ".join(chosen)


def answer(question: str) -> dict:
    sources = retrieve(question)
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    response = None
    if api_key and sources:
        context = "\n\n".join(f"[{s['source']}, passage {s['passage']}]\n{s['text']}" for s in sources)
        payload = {"model": model, "messages": [
            {"role": "system", "content": "Answer using only the supplied company document passages. If they do not answer the question, say so. Cite claims with the exact source labels in square brackets."},
            {"role": "user", "content": f"Question: {question}\n\nApproved document passages:\n{context}"}], "temperature": 0.2}
        try:
            req = Request("https://api.openai.com/v1/chat/completions", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
            with urlopen(req, timeout=45) as res:
                response = json.loads(res.read())["choices"][0]["message"]["content"]
        except (URLError, TimeoutError, KeyError, ValueError) as exc:
            response = None
            error = f"LLM unavailable; using local answer ({type(exc).__name__})."
        else:
            error = None
    else:
        error = None
    return {"answer": response or local_answer(question, sources), "sources": sources, "mode": "openai" if response else "local", "notice": error}


class Handler(BaseHTTPRequestHandler):
    def respond(self, code: int, payload: object, content_type: str = "application/json") -> None:
        data = payload if isinstance(payload, bytes) else (json.dumps(payload).encode() if content_type == "application/json" else str(payload).encode())
        self.send_response(code)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if "charset" not in content_type else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/api/documents":
            items = [{"name": p.name, "size": p.stat().st_size} for p in sorted(DOCS.iterdir()) if p.is_file() and p.suffix.lower() in SUPPORTED]
            return self.respond(200, {"documents": items})
        if self.path == "/api/health":
            return self.respond(200, {"ok": True, "llm_enabled": bool(os.getenv("OPENAI_API_KEY"))})
        if self.path in ("/", "/index.html"):
            return self.respond(200, (WEB / "index.html").read_bytes(), "text/html")
        return self.respond(404, {"error": "Not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            return self.respond(413, {"error": "Request too large"})
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.respond(400, {"error": "Invalid JSON"})
        if self.path == "/api/ask":
            question = str(data.get("question", "")).strip()[:1000]
            return self.respond(200, answer(question)) if question else self.respond(400, {"error": "Enter a question"})
        if self.path == "/api/upload":
            name = Path(str(data.get("name", ""))).name
            content = str(data.get("content", ""))
            if Path(name).suffix.lower() not in SUPPORTED:
                return self.respond(400, {"error": "Upload a .txt or .md file"})
            if not content.strip() or len(content.encode("utf-8")) > 1_000_000:
                return self.respond(400, {"error": "File is empty or exceeds 1 MB"})
            safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:120]
            (DOCS / safe_name).write_text(content, encoding="utf-8")
            return self.respond(201, {"name": safe_name})
        return self.respond(404, {"error": "Not found"})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[DocuFind] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    DOCS.mkdir(exist_ok=True)
    host, port = os.getenv("DOCUFIND_HOST", "127.0.0.1"), int(os.getenv("PORT", "8000"))
    print(f"DocuFind AI is ready at http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
