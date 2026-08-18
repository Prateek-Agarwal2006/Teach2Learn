from pathlib import Path

from app.config import Settings


def test_settings_read_paths_and_switches_from_environment(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "state"
    monkeypatch.setenv("T2L_DATA_DIR", str(data_dir))
    monkeypatch.setenv("T2L_DATABASE_PATH", str(data_dir / "db" / "portal.sqlite3"))
    monkeypatch.setenv("T2L_TRANSCRIPT_DIR", str(data_dir / "turns"))
    monkeypatch.setenv("T2L_LOGGING_ENABLED", "off")
    monkeypatch.setenv("T2L_LOG_LEVEL", "debug")
    monkeypatch.setenv("T2L_LOG_FILE", str(data_dir / "logs" / "portal.log"))
    monkeypatch.setenv("T2L_EVALUATION_ENABLED", "yes")
    monkeypatch.setenv("T2L_STUDENT_QUESTIONNAIRE_ENABLED", "yes")

    settings = Settings.from_env()

    assert settings.data_dir == data_dir.resolve()
    assert settings.database_path == (data_dir / "db" / "portal.sqlite3").resolve()
    assert settings.transcript_dir == (data_dir / "turns").resolve()
    assert settings.logging_enabled is False
    assert settings.log_level == "DEBUG"
    assert settings.log_file == (data_dir / "logs" / "portal.log").resolve()
    assert settings.evaluation_enabled is True
    assert settings.student_questionnaire_enabled is True


def test_ensure_directories_creates_only_runtime_parents(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "state",
        database_path=tmp_path / "state" / "db" / "portal.sqlite3",
        transcript_dir=tmp_path / "state" / "transcripts",
        logging_enabled=True,
        log_level="INFO",
        log_file=tmp_path / "logs" / "portal.log",
        evaluation_enabled=False,
    )

    settings.ensure_directories()

    assert settings.database_path.parent.is_dir()
    assert settings.transcript_dir.is_dir()
    assert settings.log_file is not None
    assert settings.log_file.parent.is_dir()
    assert not settings.database_path.exists()
    assert not settings.log_file.exists()


def test_student_questionnaire_is_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("T2L_STUDENT_QUESTIONNAIRE_ENABLED", raising=False)
    monkeypatch.setenv("T2L_DATA_DIR", str(tmp_path))

    assert Settings.from_env().student_questionnaire_enabled is False
