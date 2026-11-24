"""Upgrade existing SQLite databases to the current schema."""

import shutil

from sqlalchemy import Connection

from data_models import db


def run_migrations() -> None:
    """Apply every outstanding schema change to the current database."""
    _add_book_rating()
    _update_author_constraints()


def _add_book_rating() -> None:
    columns = db.inspect(db.engine).get_columns("book")
    if any(column["name"] == "rating" for column in columns):
        return

    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE book ADD COLUMN rating INTEGER "
            "CHECK (rating IS NULL OR rating BETWEEN 1 AND 10)"
        )


def _update_author_constraints() -> None:
    """Make author names unique and the date of death optional."""
    inspector = db.inspect(db.engine)
    has_unique_name = any(
        constraint["column_names"] == ["name"]
        for constraint in inspector.get_unique_constraints("author")
    )
    death_is_nullable = any(
        column["name"] == "date_of_death" and column["nullable"]
        for column in inspector.get_columns("author")
    )
    if has_unique_name and death_is_nullable:
        return

    _backup_database()
    with db.engine.connect() as connection:
        # SQLite cannot alter constraints, so the table has to be rebuilt.
        # The explicit BEGIN makes the whole rebuild a single transaction.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        _resolve_duplicate_authors(connection)
        connection.exec_driver_sql(
            "CREATE TABLE author_new ("
            "id INTEGER NOT NULL, "
            "name VARCHAR NOT NULL, "
            "birth_date DATETIME NOT NULL, "
            "date_of_death DATETIME, "
            "PRIMARY KEY (id), "
            "UNIQUE (name))"
        )
        connection.exec_driver_sql(
            "INSERT INTO author_new (id, name, birth_date, date_of_death) "
            "SELECT id, name, birth_date, date_of_death FROM author"
        )
        connection.exec_driver_sql("DROP TABLE author")
        connection.exec_driver_sql("ALTER TABLE author_new RENAME TO author")
        connection.commit()


def _backup_database() -> None:
    database_path = db.engine.url.database
    shutil.copy2(database_path, f"{database_path}.bak")


def _resolve_duplicate_authors(connection: Connection) -> None:
    """Merge identical authors; rename different authors sharing a name."""
    rows = connection.exec_driver_sql(
        "SELECT id, name, birth_date, date_of_death FROM author ORDER BY id"
    ).all()
    kept_ids: dict[tuple, int] = {}
    used_names = {row.name for row in rows}
    seen_names: set[str] = set()

    for author_id, name, birth_date, date_of_death in rows:
        identity = (name, birth_date, date_of_death)
        if identity in kept_ids:
            connection.exec_driver_sql(
                "UPDATE book SET author_id = ? WHERE author_id = ?",
                (kept_ids[identity], author_id),
            )
            connection.exec_driver_sql(
                "DELETE FROM author WHERE id = ?", (author_id,)
            )
            continue

        kept_ids[identity] = author_id
        if name in seen_names:
            number = 2
            while f"{name} ({number})" in used_names:
                number += 1
            unique_name = f"{name} ({number})"
            used_names.add(unique_name)
            connection.exec_driver_sql(
                "UPDATE author SET name = ? WHERE id = ?",
                (unique_name, author_id),
            )
        seen_names.add(name)
