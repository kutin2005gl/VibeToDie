"""Load the policy chunks and their embeddings into Postgres: `cd ai && .venv/Scripts/python scripts/ingest_knowledge.py`
(`--dry-run` only reports). Needs AI_DATABASE_URL and EMBEDDING_URL; see app/knowledge/ingest.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.ingest import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
