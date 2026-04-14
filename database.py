import re
import sqlite3
from typing import Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_code(code: str) -> str:
    raw = (code or "").strip().upper()
    raw = re.sub(r"[^A-Z0-9]", "", raw)

    if raw.startswith("FM"):
        digits = raw[2:]
        if digits.isdigit() and digits:
            return f"FM-{int(digits):04d}"

    return raw


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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_unlocked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT NOT NULL,
            channel_title TEXT NOT NULL,
            channel_url TEXT NOT NULL,
            button_text TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute("PRAGMA table_info(required_channels)")
    columns = {row["name"] for row in cur.fetchall()}

    if "button_text" not in columns:
        cur.execute(
            """
            ALTER TABLE required_channels
            ADD COLUMN button_text TEXT NOT NULL DEFAULT ''
            """
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_channel_clicks (
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            clicked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, channel_id)
        )
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
    normalized = normalize_code(code)

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
        WHERE code = ?
        """,
        (normalized,),
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


def upsert_user(
    db_path: str,
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO users (user_id, username, first_name, is_unlocked)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_seen_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            (username or "").strip(),
            (first_name or "").strip(),
        ),
    )

    conn.commit()
    conn.close()


def get_user(db_path: str, user_id: int) -> Optional[dict]:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT user_id, username, first_name, is_unlocked, created_at, last_seen_at
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    return dict(row)


def set_user_unlocked(db_path: str, user_id: int, is_unlocked: bool) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET is_unlocked = ?
        WHERE user_id = ?
        """,
        (1 if is_unlocked else 0, user_id),
    )

    conn.commit()
    conn.close()


def get_active_required_channels(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            channel_username,
            channel_title,
            channel_url,
            button_text,
            is_active,
            sort_order,
            created_at
        FROM required_channels
        WHERE is_active = 1
        ORDER BY sort_order ASC, id ASC
        """
    )

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_all_required_channels(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            channel_username,
            channel_title,
            channel_url,
            button_text,
            is_active,
            sort_order,
            created_at
        FROM required_channels
        ORDER BY sort_order ASC, id ASC
        """
    )

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def add_required_channel(
    db_path: str,
    channel_username: str,
    channel_title: str,
    channel_url: str,
    sort_order: int = 0,
    button_text: str = "",
) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    final_button_text = (button_text or "").strip()
    if not final_button_text:
        final_button_text = f"Перейти в {channel_title.strip()}"

    cur.execute(
        """
        INSERT INTO required_channels (
            channel_username,
            channel_title,
            channel_url,
            button_text,
            is_active,
            sort_order
        )
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            channel_username.strip(),
            channel_title.strip(),
            channel_url.strip(),
            final_button_text,
            sort_order,
        ),
    )

    conn.commit()
    conn.close()


def delete_required_channel(db_path: str, channel_id: int) -> bool:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM user_channel_clicks
        WHERE channel_id = ?
        """,
        (channel_id,),
    )

    cur.execute(
        """
        DELETE FROM required_channels
        WHERE id = ?
        """,
        (channel_id,),
    )

    deleted = cur.rowcount > 0

    conn.commit()
    conn.close()
    return deleted


def has_access(db_path: str, user_id: int) -> bool:
    active_channels = get_active_required_channels(db_path)

    if not active_channels:
        return True

    user = get_user(db_path, user_id)
    if user is None:
        return False

    return bool(user.get("is_unlocked"))


def register_channel_click(db_path: str, user_id: int, channel_id: int) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR REPLACE INTO user_channel_clicks (user_id, channel_id, clicked_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
        (user_id, channel_id),
    )

    conn.commit()
    conn.close()


def get_user_clicked_channel_ids(db_path: str, user_id: int) -> set[int]:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT channel_id
        FROM user_channel_clicks
        WHERE user_id = ?
        """,
        (user_id,),
    )

    rows = cur.fetchall()
    conn.close()

    return {int(row["channel_id"]) for row in rows}


def has_clicked_all_required_channels(db_path: str, user_id: int) -> bool:
    channels = get_active_required_channels(db_path)

    if not channels:
        return True

    clicked_ids = get_user_clicked_channel_ids(db_path, user_id)
    required_ids = {int(channel["id"]) for channel in channels}

    return required_ids.issubset(clicked_ids)


def get_missing_click_channels(db_path: str, user_id: int) -> list[dict]:
    channels = get_active_required_channels(db_path)

    if not channels:
        return []

    clicked_ids = get_user_clicked_channel_ids(db_path, user_id)
    return [channel for channel in channels if int(channel["id"]) not in clicked_ids]


def reset_user_access(db_path: str, user_id: int) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET is_unlocked = 0
        WHERE user_id = ?
        """,
        (user_id,),
    )

    cur.execute(
        """
        DELETE FROM user_channel_clicks
        WHERE user_id = ?
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()