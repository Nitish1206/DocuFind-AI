# DocuFind AI

A small, runnable retrieval-augmented Q&A demo for approved company documents. It indexes `.txt` and `.md` files from `documents/`, retrieves relevant passages, and shows those passages with every answer. With no API key it uses a local extractive answer mode; optionally set an OpenAI key to generate a synthesized answer grounded in the same retrieved passages.

## Run it

Requires Python 3.10 or newer. No dependencies are needed.

**Windows PowerShell**

```powershell
cd C:\Users\Nandini\Nitish\DocuFind-AI
python app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Ask the sample questions or upload `.txt` / `.md` files in the page. Files are saved in `documents/` and available on the next run.

To use OpenAI-generated answers, set `OPENAI_API_KEY` in the environment before starting the server. You can also set `OPENAI_MODEL` (defaults to `gpt-4o-mini`). The API key stays on the server and is never sent to the browser.

## How it works

1. Reads approved Markdown and plain text files in `documents/`.
2. Splits content into paragraph-sized passages.
3. Ranks passages by query term overlap.
4. Produces a local extractive response or asks the configured LLM to answer from retrieved context.
5. Displays source filenames, passage numbers, and retrieved text.

This is a demo, not a production document security system. It supports local `.txt` and `.md` files and basic lexical retrieval; production use should add authentication, access controls, durable indexing, richer file parsing, and retrieval evaluation.
