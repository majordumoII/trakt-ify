"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

APPLICATION_URL = "https://trakt.tv/oauth/applications"


@dataclass(frozen=True)
class Settings:
    client_id: str
    username: str
    app_id: str | None
    data_dir: Path
    db_path: Path
    graph_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        client_id = os.environ.get("TRAKT_CLIENT_ID", "").strip()
        username = os.environ.get("TRAKT_USERNAME", "").strip()

        if not client_id:
            raise RuntimeError(
                f"TRAKT_CLIENT_ID is not set. Create an app at {APPLICATION_URL} "
                "and put the client ID in .env"
            )
        if not username:
            raise RuntimeError("TRAKT_USERNAME is not set.")

        data_dir = Path(os.environ.get("TRAKT_IFY_DATA_DIR", PROJECT_ROOT / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            client_id=client_id,
            username=username,
            app_id=os.environ.get("TRAKT_APP_ID") or None,
            data_dir=data_dir,
            db_path=data_dir / "trakt.db",
            graph_path=data_dir / "graph.json",
        )
