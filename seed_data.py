import json
import re
from datetime import date
from typing import TypedDict
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from data_models import Author, Book, db


class OpenLibraryAuthor(TypedDict):
    name: str


class OpenLibraryBook(TypedDict, total=False):
    title: str
    authors: list[OpenLibraryAuthor]
    publish_date: str


BOOK_AUTHORS = {
    "0141439513": "Jane Austen",
    "0141439661": "Jane Austen",
    "0451526341": "George Orwell",
    "0451524934": "George Orwell",
    "0345339681": "J.R.R. Tolkien",
    "0345339703": "J.R.R. Tolkien",
    "0062073486": "Agatha Christie",
    "0062073508": "Agatha Christie",
    "0743273567": "F. Scott Fitzgerald",
    "0375759646": "F. Scott Fitzgerald",
}

OPEN_LIBRARY_API = "https://openlibrary.org/api/books"
AUTHOR_DATES = {
    "Jane Austen": (date(1775, 12, 16), date(1817, 7, 18)),
    "George Orwell": (date(1903, 6, 25), date(1950, 1, 21)),
    "J.R.R. Tolkien": (date(1892, 1, 3), date(1973, 9, 2)),
    "Agatha Christie": (date(1890, 9, 15), date(1976, 1, 12)),
    "F. Scott Fitzgerald": (date(1896, 9, 24), date(1940, 12, 21)),
}


def fetch_book_metadata() -> dict[str, OpenLibraryBook]:
    params = {
        "bibkeys": ",".join(f"ISBN:{isbn}" for isbn in BOOK_AUTHORS),
        "format": "json",
        "jscmd": "data",
    }
    request = Request(
        f"{OPEN_LIBRARY_API}?{urlencode(params)}",
        headers={"User-Agent": "MSITBookAlchemy/1.0 (sample data seeder)"},
    )

    try:
        with urlopen(request, timeout=20) as response:
            response_data = json.load(response)
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not retrieve sample books from Open Library") from error

    metadata: dict[str, OpenLibraryBook] = {}
    for isbn, expected_author in BOOK_AUTHORS.items():
        book = response_data.get(f"ISBN:{isbn}")
        if not book or not book.get("title"):
            raise RuntimeError(f"Open Library returned no book data for ISBN {isbn}")

        authors = book.get("authors", [])
        if not any(author.get("name") == expected_author for author in authors):
            raise RuntimeError(
                f"Open Library returned an unexpected author for ISBN {isbn}"
            )
        metadata[isbn] = book

    return metadata


def _publication_date(book: OpenLibraryBook) -> date | None:
    publish_date = book.get("publish_date")
    if not isinstance(publish_date, str):
        return None

    year_match = re.match(r"^(\d{4})", publish_date)
    return date(int(year_match.group(1)), 1, 1) if year_match else None


def seed_database() -> int:
    existing_isbns = set(
        db.session.execute(
            db.select(Book.isbn).where(Book.isbn.in_(BOOK_AUTHORS))
        ).scalars()
    )
    missing_isbns = set(BOOK_AUTHORS) - existing_isbns
    if not missing_isbns:
        return 0

    metadata = fetch_book_metadata()
    authors_by_name: dict[str, Author] = {}

    for isbn, expected_author in BOOK_AUTHORS.items():
        if isbn in existing_isbns:
            continue

        author = authors_by_name.get(expected_author)
        if author is None:
            author = db.session.execute(
                db.select(Author).where(Author.name == expected_author)
            ).scalars().first()
            if author is None:
                birth_date, date_of_death = AUTHOR_DATES[expected_author]
                author = Author(
                    name=expected_author,
                    birth_date=birth_date,
                    date_of_death=date_of_death,
                )
                db.session.add(author)
                db.session.flush()
            authors_by_name[expected_author] = author

        book_data = metadata[isbn]
        db.session.add(
            Book(
                title=book_data["title"],
                isbn=isbn,
                publication_year=_publication_date(book_data),
                author_id=author.id,
            )
        )

    db.session.commit()
    return len(missing_isbns)


if __name__ == "__main__":
    from app import app

    with app.app_context():
        seeded_count = seed_database()
        print(f"Added {seeded_count} sample books.")
