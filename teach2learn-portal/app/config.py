from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    transcript_dir: Path
    logging_enabled: bool
    log_level: str
    log_file: Path | None
    evaluation_enabled: bool
    student_questionnaire_enabled: bool = False
    default_language: str = "en"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("T2L_DATA_DIR", "data")).expanduser().resolve()
        log_file_value = os.getenv("T2L_LOG_FILE", "").strip()
        return cls(
            data_dir=data_dir,
            database_path=Path(os.getenv("T2L_DATABASE_PATH", data_dir / "portal.sqlite3")).expanduser().resolve(),
            transcript_dir=Path(os.getenv("T2L_TRANSCRIPT_DIR", data_dir / "transcripts")).expanduser().resolve(),
            logging_enabled=_boolean("T2L_LOGGING_ENABLED", True),
            log_level=os.getenv("T2L_LOG_LEVEL", "INFO").upper(),
            log_file=Path(log_file_value).expanduser().resolve() if log_file_value else None,
            evaluation_enabled=_boolean("T2L_EVALUATION_ENABLED", False),
            student_questionnaire_enabled=_boolean("T2L_STUDENT_QUESTIONNAIRE_ENABLED", False),
            default_language=os.getenv("T2L_DEFAULT_LANGUAGE", "en").strip().lower()[:5],
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.transcript_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        self.database_path.parent.chmod(0o700)
        self.transcript_dir.chmod(0o700)
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.log_file.parent.chmod(0o700)


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    if not settings.logging_enabled:
        logging.disable(logging.CRITICAL)
        return
    logging.disable(logging.NOTSET)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log_file:
        settings.ensure_directories()
        handlers.append(logging.FileHandler(settings.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


settings = Settings.from_env()
