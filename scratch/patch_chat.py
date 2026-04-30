"""Patch chat.py: CQ-07 (history error detail) + PC-02 (sentence-chunk SSE)."""
from pathlib import Path

FILE = Path(r"src\api\routes\chat.py")
content = FILE.read_text(encoding="utf-8")

# CQ-07: sanitize /history exception detail
OLD_HISTORY_ERR = "        raise HTTPException(status_code=500, detail=str(e)) from e"
NEW_HISTORY_ERR = (
    "        # CQ-07: Never expose raw exception messages to clients (may leak DB schema / paths).\n"
    "        raise HTTPException(status_code=500, detail=\"An internal error occurred\") from e"
)
if OLD_HISTORY_ERR in content:
    content = content.replace(OLD_HISTORY_ERR, NEW_HISTORY_ERR, 1)
    print("CQ-07 applied")
else:
    print("WARNING: CQ-07 target not found")

# PC-02: replace word-by-word SSE with sentence-chunk SSE
OLD_SSE = (
    "            words = response_text.split(\" \")\n"
    "            for i, word in enumerate(words):\n"
    "                chunk = word + (\" \" if i < len(words) - 1 else \"\")\n"
    "                yield f\"data: {json.dumps({'delta': chunk})}\\n\\n\"\n"
    "                await asyncio.sleep(0.01)"
)
NEW_SSE = '''\
            # PC-02: Chunk by sentence boundaries instead of word-by-word.
            # Reduces asyncio.sleep() calls from ~500 to ~25 per average response,
            # cutting artificial latency from ~5s to ~1.25s.
            import re as _re
            sentences = _re.split(r"(?<=[.!?])\\s+", response_text.strip())
            chunks: list[str] = []
            current_chunk: list[str] = []
            current_words = 0
            for sentence in sentences:
                words_in_sentence = len(sentence.split())
                if current_words + words_in_sentence > 15 and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [sentence]
                    current_words = words_in_sentence
                else:
                    current_chunk.append(sentence)
                    current_words += words_in_sentence
            if current_chunk:
                chunks.append(" ".join(current_chunk))

            for i, chunk in enumerate(chunks):
                text = chunk + (" " if i < len(chunks) - 1 else "")
                yield f"data: {json.dumps({'delta': text})}\\n\\n"
                await asyncio.sleep(0.05)'''

# Try both line ending styles
OLD_SSE_WIN = OLD_SSE.replace("\n", "\r\n")
if OLD_SSE_WIN in content:
    content = content.replace(OLD_SSE_WIN, NEW_SSE.replace("\n", "\r\n"), 1)
    print("PC-02 applied (CRLF)")
elif OLD_SSE in content:
    content = content.replace(OLD_SSE, NEW_SSE, 1)
    print("PC-02 applied (LF)")
else:
    print("WARNING: PC-02 target not found")

FILE.write_text(content, encoding="utf-8")
print("Done. chat.py patched.")
