"""Persistent single-purpose worker for author-owned V-click import jobs."""

from __future__ import annotations

import os
import socket
import time

from pixiv_yuri.jjwxc.author_v_jobs import process_next_author_v_job
from pixiv_yuri.shared.database import build_engine, build_session_factory


def main() -> int:
    database_url = os.environ.get("PYURI_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("database_url_required")
    factory = build_session_factory(build_engine(database_url))
    worker_id = f"author-v-{socket.gethostname()}"
    while True:
        with factory() as session:
            processed = process_next_author_v_job(session, worker_id=worker_id)
        if not processed:
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
