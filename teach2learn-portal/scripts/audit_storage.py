from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.db import Database
from app.services.transcripts import TranscriptStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Teach2Learn storage without exposing participant data.")
    parser.add_argument(
        "--repair-mirrors",
        action="store_true",
        help="Rebuild private JSONL mirrors from the authoritative SQLite messages table.",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    database = Database(settings.database_path)
    transcripts = TranscriptStore(settings.transcript_dir, database)
    sync = transcripts.synchronize() if args.repair_mirrors else None
    database_report = database.storage_report()
    mirror_report = transcripts.mirror_report()
    wal_path = settings.database_path.with_name(settings.database_path.name + "-wal")
    report = {
        "status": "ok"
        if database_report["status"] == "ok" and mirror_report["status"] == "ok"
        else "error",
        "database": database_report,
        "transcript_mirrors": mirror_report,
        "database_bytes": settings.database_path.stat().st_size,
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
    }
    if sync is not None:
        report["synchronization"] = sync
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
