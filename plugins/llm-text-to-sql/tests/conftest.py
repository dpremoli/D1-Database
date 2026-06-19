"""pytest configuration — add plugin root to sys.path and set safe defaults."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Safe defaults so importing the app needs no running stack.
os.environ.setdefault("LLM_DATABASE_URL", "postgres://x:x@localhost:5432/x")
os.environ.setdefault("OLLAMA_URL", "http://ollama:11434")
