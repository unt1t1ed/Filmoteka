import sqlite3
from typing import Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS films (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            title TEXT NOT NULL,
            year INTEGER,
            genres TEXT,
            description TEXT,
            poster_url TEXT,
            watch_url TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_films_code
        ON films(code)
        """
    )

    conn.commit()
    conn.close()


def generate_film_code(film_id: int) -> str:
    return f"FM-{film_id:04d}"


def add_film(
    db_path: str,
    title: str,
    year: Optional[int],
    genres: str,
    description: str,
    poster_url: str,
    watch_url: str,
) -> str:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO films (
            title,
            year,
            genres,
            description,
            poster_url,
            watch_url
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            title.strip(),
            year,
            genres.strip(),
            description.strip(),
            poster_url.strip(),
            watch_url.strip(),
        ),
    )

    film_id = cur.lastrowid
    code = generate_film_code(film_id)

    cur.execute(
        """
        UPDATE films
        SET code = ?
        WHERE id = ?
        """,
        (code, film_id),
    )

    conn.commit()
    conn.close()
    return code


def get_film_by_code(db_path: str, code: str) -> Optional[dict]:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            code,
            title,
            year,
            genres,
            description,
            poster_url,
            watch_url,
            created_at
        FROM films
        WHERE UPPER(code) = UPPER(?)
        """,
        (code.strip(),),
    )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    return dict(row)


def get_recent_films(db_path: str, limit: int = 10) -> list[dict]:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            code,
            title,
            year,
            genres,
            description,
            poster_url,
            watch_url,
            created_at
        FROM films
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]