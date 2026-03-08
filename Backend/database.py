from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    VARCHAR,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

_DB_PATH = Path(__file__).resolve().parent.parent / "resona.db"
engine = create_engine(f"sqlite:///{_DB_PATH}", echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_ROOT = PROJECT_ROOT / "storage"
CHUNKS_ROOT = STORAGE_ROOT / "audio" / "chunks"
FINAL_AUDIO_ROOT = STORAGE_ROOT / "audio" / "final"
SCRIPT_ROOT = STORAGE_ROOT / "scripts"

class User(Base):
    __tablename__ = "User"
    id = Column(Integer, Identity(), primary_key=True)
    name = Column(VARCHAR(255), nullable=False)
    password = Column(LargeBinary, nullable=True)
    email = Column(VARCHAR(255), unique=True)
    provider = Column(VARCHAR(10), nullable=False)
    provider_id = Column(VARCHAR(255), unique=True, nullable=True)

    def __repr__(self):
        return f"<User {self.id}>"

class Keys(Base):
    __tablename__ = "Keys"
    id = Column(Integer, Identity(), primary_key=True)
    useremail = Column(VARCHAR(255), unique=True, nullable=False)
    openrouterApi = Column(VARCHAR(255), nullable=False, unique=True)
    grokApi = Column(VARCHAR(255), nullable=False, unique=True)

    def __repr__(self):
        return f"Key openrouter : {self.openrouterApi}"

class Podcasts(Base):
    __tablename__ = "Podcasts"
    id = Column(Integer, Identity(), primary_key=True)
    userid = Column(Integer, ForeignKey(User.id), nullable=True)
    status = Column(VARCHAR(32), nullable=False, default="queued", server_default="queued")
    source_url = Column(VARCHAR(2048), nullable=False)
    style = Column(VARCHAR(100), nullable=False)
    exchanges = Column(Integer, nullable=False)
    script_text = Column(Text, nullable=True)
    script_location = Column(VARCHAR(255), nullable=True)
    audio_location = Column(VARCHAR(255), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self):
        return f"<Podcast {self.id}>"


class PodcastTurns(Base):
    __tablename__ = "PodcastTurns"
    __table_args__ = (UniqueConstraint("podcast_id", "turn_index", name="uq_podcast_turn"),)

    id = Column(Integer, Identity(), primary_key=True)
    podcast_id = Column(Integer, ForeignKey("Podcasts.id"), nullable=False)
    turn_index = Column(Integer, nullable=False)
    speaker = Column(VARCHAR(64), nullable=False)
    text = Column(Text, nullable=False)
    audio_chunk_location = Column(VARCHAR(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self):
        return f"<PodcastTurn podcast_id={self.podcast_id} turn={self.turn_index}>"


def prepare_storage_paths() -> None:
    CHUNKS_ROOT.mkdir(parents=True, exist_ok=True)
    FINAL_AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    SCRIPT_ROOT.mkdir(parents=True, exist_ok=True)


def chunks_dir_for_job(job_id: int) -> Path:
    path = CHUNKS_ROOT / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _migrate_legacy_podcasts_table() -> None:
    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Podcasts'")
        ).scalar()
        if not table_exists:
            return

        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('Podcasts')")).fetchall()
        }
        if {"status", "source_url", "script_text", "error_message", "created_at", "updated_at"}.issubset(columns):
            return

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS Podcasts_new (
                    id INTEGER PRIMARY KEY,
                    userid INTEGER NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    source_url VARCHAR(2048) NOT NULL,
                    style VARCHAR(100) NOT NULL,
                    exchanges INTEGER NOT NULL,
                    script_text TEXT NULL,
                    script_location VARCHAR(255) NULL,
                    audio_location VARCHAR(255) NULL,
                    error_message TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(userid) REFERENCES User(id)
                )
                """
            )
        )

        source_url_expr = "url" if "url" in columns else "''"
        style_expr = "style" if "style" in columns else "''"
        exchanges_expr = "exchanges" if "exchanges" in columns else "0"
        script_location_expr = "script_location" if "script_location" in columns else "NULL"
        audio_location_expr = "audio_location" if "audio_location" in columns else "NULL"
        userid_expr = "userid" if "userid" in columns else "NULL"

        conn.execute(
            text(
                f"""
                INSERT INTO Podcasts_new (
                    id, userid, status, source_url, style, exchanges, script_text,
                    script_location, audio_location, error_message, created_at, updated_at
                )
                SELECT
                    id,
                    {userid_expr},
                    CASE
                        WHEN {script_location_expr} IS NOT NULL OR {audio_location_expr} IS NOT NULL
                        THEN 'completed'
                        ELSE 'queued'
                    END,
                    {source_url_expr},
                    {style_expr},
                    {exchanges_expr},
                    NULL,
                    {script_location_expr},
                    {audio_location_expr},
                    NULL,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM Podcasts
                """
            )
        )

        conn.execute(text("DROP TABLE Podcasts"))
        conn.execute(text("ALTER TABLE Podcasts_new RENAME TO Podcasts"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _migrate_keys_table() -> None:
    """Add grokApi column to Keys if it was created before this field existed."""
    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Keys'")
        ).scalar()
        if not table_exists:
            return  # create_all will build the full schema

        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('Keys')")).fetchall()
        }
        if "grokApi" not in columns:
            conn.execute(text("ALTER TABLE Keys ADD COLUMN grokApi VARCHAR(255) NOT NULL DEFAULT ''"))


def init_db() -> None:
    prepare_storage_paths()
    _migrate_legacy_podcasts_table()
    _migrate_keys_table()
    Base.metadata.create_all(engine)

if __name__ == "__main__":
    init_db()
