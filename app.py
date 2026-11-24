import json
import re
from datetime import date
from os import getenv, path
from secrets import token_hex
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from data_models import Author, Book, db


DB_NAME = "library.sqlite"
DB_PATH = path.join(path.dirname(__file__), "data", DB_NAME)

app = Flask(__name__)
app.config["SECRET_KEY"] = getenv("SECRET_KEY") or token_hex(32)
app.config["OPENAI_API_KEY"] = getenv("OPENAI_API_KEY")
app.config["OPENAI_BASE_URL"] = getenv(
    "OPENAI_BASE_URL", "https://api.openai.com/v1"
)
app.config["OPENAI_MODEL"] = getenv("OPENAI_MODEL", "gpt-4o-mini")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
db.init_app(app)

with app.app_context():
    print("Creating database tables...")
    db.create_all()
    if db.session.execute(db.select(Book.id).limit(1)).first() is None:
        from seed_data import seed_database
        print(f"Added {seed_database()} sample books.")


@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    sort_by = request.args.get("sort", "title")
    sort_columns = {
        "title": Book.title,
        "year": Book.publication_year,
    }

    statement = db.select(Book)
    if query:
        escaped_query = (
            query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        statement = statement.where(
            Book.title.ilike(f"%{escaped_query}%", escape="\\")
        )

    if sort_by == "author":
        statement = statement.join(Book.author).order_by(
            db.func.lower(Author.name), db.func.lower(Book.title)
        )
    else:
        sort_by = sort_by if sort_by in sort_columns else "title"
        if sort_by == "year":
            statement = statement.order_by(
                sort_columns[sort_by], db.func.lower(Book.title)
            )
        else:
            statement = statement.order_by(db.func.lower(Book.title))

    books = db.session.execute(statement).scalars().all()
    authors = db.session.execute(
        db.select(Author)
        .join(Author.books)
        .distinct()
        .order_by(db.func.lower(Author.name))
    ).scalars().all()
    return render_template(
        "home.html", books=books, authors=authors, sort_by=sort_by, query=query
    )


def _library_redirect():
    return redirect(
        url_for(
            "index",
            q=request.form.get("q", ""),
            sort=request.form.get("sort", "title"),
        )
    )


@app.route("/book/<int:book_id>/delete", methods=["POST"])
def delete_book(book_id):
    book = db.get_or_404(Book, book_id)
    author = book.author
    title = book.title
    has_other_books = db.session.execute(
        db.select(Book.id)
        .where(Book.author_id == author.id, Book.id != book.id)
        .limit(1)
    ).first() is not None

    db.session.delete(book)
    if not has_other_books:
        db.session.delete(author)
    db.session.commit()
    flash(f'"{title}" was deleted successfully.', "success")
    return _library_redirect()


@app.route("/author/<int:author_id>/delete", methods=["POST"])
def delete_author(author_id):
    author = db.get_or_404(Author, author_id)
    name = author.name

    db.session.delete(author)
    db.session.commit()
    flash(
        f'{name} and all of their books were deleted successfully.',
        "success",
    )
    return _library_redirect()


@app.route("/book/<int:book_id>")
def book_detail(book_id):
    book = db.get_or_404(Book, book_id)
    return render_template("book_detail.html", book=book)


@app.route("/author/<int:author_id>")
def author_detail(author_id):
    author = db.get_or_404(Author, author_id)
    books = db.session.execute(
        db.select(Book).where(Book.author_id == author_id).order_by(Book.title)
    ).scalars().all()
    return render_template("author_detail.html", author=author, books=books)


@app.route("/book/<int:book_id>/rate", methods=["POST"])
def rate_book(book_id):
    book = db.get_or_404(Book, book_id)
    rating_value = request.form.get("rating", "")
    if not re.fullmatch(r"(?:[1-9]|10)", rating_value):
        flash("Choose a rating from 1 to 10.", "error")
        if request.form.get("next") == "home":
            return _library_redirect()
        return redirect(url_for("book_detail", book_id=book_id))

    book.rating = int(rating_value)
    db.session.commit()
    flash(f'Your rating for "{book.title}" was saved.', "success")
    if request.form.get("next") == "home":
        return _library_redirect()
    return redirect(url_for("book_detail", book_id=book_id))


@app.route("/recommendation", methods=["GET", "POST"])
def recommendation():
    recommendation_text = None
    error_message = None

    if request.method == "POST":
        api_key = app.config["OPENAI_API_KEY"]
        if not api_key:
            error_message = (
                "Set OPENAI_API_KEY to enable recommendations. You can also "
                "set OPENAI_BASE_URL and OPENAI_MODEL for an "
                "OpenAI-compatible provider."
            )
        else:
            books = db.session.execute(
                db.select(Book).join(Book.author).order_by(Book.title)
            ).scalars().all()
            library = [
                {
                    "title": book.title,
                    "author": book.author.name,
                    "rating": book.rating,
                }
                for book in books
            ]
            payload = {
                "model": app.config["OPENAI_MODEL"],
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Recommend one book the reader has not "
                            "already read. Use their library and optional "
                            "ratings to tailor your choice. Briefly explain "
                            "why it suits them."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(library, ensure_ascii=False),
                    },
                ],
            }
            api_request = Request(
                app.config["OPENAI_BASE_URL"].rstrip("/")
                + "/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(api_request, timeout=30) as response:
                    result = json.load(response)
                message = result["choices"][0]["message"]
                recommendation_text = message["content"]
                if (
                    not isinstance(recommendation_text, str)
                    or not recommendation_text.strip()
                ):
                    raise ValueError(
                        "The recommendation provider returned empty text."
                    )
            except HTTPError as error:
                error_message = (
                    f"The recommendation provider returned HTTP {error.code}."
                )
            except (URLError, TimeoutError) as error:
                reason = getattr(error, "reason", "request timed out")
                error_message = (
                    f"Could not reach the recommendation provider: {reason}."
                )
            except (
                json.JSONDecodeError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
            ):
                error_message = (
                    "The recommendation provider returned an invalid response."
                )

    return render_template(
        "recommendation.html",
        recommendation_text=recommendation_text,
        error_message=error_message,
        api_configured=bool(app.config["OPENAI_API_KEY"]),
    ), 502 if error_message and app.config["OPENAI_API_KEY"] else 200


def _parse_date(value):
    """Return an ISO date string as a date, or None if it is not valid."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _validate_book_form(form):
    """Return the cleaned book fields and a list of validation errors."""
    errors = []
    title = form.get("title", "").strip()
    isbn = form.get("isbn", "").strip().replace("-", "")
    publication_year = _parse_date(form.get("publication_year", ""))
    author_id = form.get("author_id", type=int)

    if not title:
        errors.append("Title is required.")
    if not re.fullmatch(r"[0-9]{10}", isbn):
        errors.append(
            "ISBN must contain exactly 10 digits; hyphens are allowed."
        )
    if publication_year is None:
        errors.append("A valid publication date is required.")
    if author_id is None or db.session.get(Author, author_id) is None:
        errors.append("Choose an existing author.")

    fields = {
        "title": title,
        "isbn": isbn,
        "publication_year": publication_year,
        "author_id": author_id,
    }
    return fields, errors


def _isbn_exists(isbn):
    return db.session.execute(
        db.select(Book.id).where(Book.isbn == isbn)
    ).first() is not None


def _render_book_form(status=200):
    authors = db.session.execute(
        db.select(Author).order_by(db.func.lower(Author.name))
    ).scalars().all()
    return render_template(
        "add_book.html", authors=authors, form=request.form
    ), status


def _duplicate_isbn_response(isbn):
    flash(f"A book with ISBN {isbn} is already in the library.", "error")
    return _render_book_form(409)


@app.route("/add_book", methods=["GET", "POST"])
def add_book():
    if request.method == "GET":
        return _render_book_form()

    fields, errors = _validate_book_form(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        return _render_book_form(400)

    if _isbn_exists(fields["isbn"]):
        return _duplicate_isbn_response(fields["isbn"])

    db.session.add(Book(**fields))
    try:
        db.session.commit()
    except IntegrityError:
        # Another request may have added the same ISBN after the check above.
        db.session.rollback()
        return _duplicate_isbn_response(fields["isbn"])

    flash(f'"{fields["title"]}" was added successfully.', "success")
    return redirect(url_for("add_book"))


def _validate_author_form(form):
    """Return the cleaned author fields and a list of validation errors."""
    errors = []
    name = form.get("name", "").strip()
    birth_date = _parse_date(form.get("birthdate", ""))
    date_of_death_value = form.get("date_of_death", "")
    date_of_death = _parse_date(date_of_death_value)

    if not name:
        errors.append("Author name is required.")
    if birth_date is None:
        errors.append("A valid birthdate is required.")
    if date_of_death_value and date_of_death is None:
        errors.append("Date of death must be a valid date or left empty.")

    fields = {
        "name": name,
        "birth_date": birth_date,
        "date_of_death": date_of_death,
    }
    return fields, errors


def _author_exists(name):
    return db.session.execute(
        db.select(Author.id).where(
            db.func.lower(Author.name) == db.func.lower(name)
        )
    ).first() is not None


def _render_author_form(status=200):
    return render_template("add_author.html", form=request.form), status


def _duplicate_author_response(name):
    flash(f'An author named "{name}" already exists.', "error")
    return _render_author_form(409)


@app.route("/add_author", methods=["GET", "POST"])
def add_author():
    if request.method == "GET":
        return _render_author_form()

    fields, errors = _validate_author_form(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        return _render_author_form(400)

    if _author_exists(fields["name"]):
        return _duplicate_author_response(fields["name"])

    db.session.add(Author(**fields))
    try:
        db.session.commit()
    except IntegrityError:
        # Another request may have added the same name after the check above.
        db.session.rollback()
        return _duplicate_author_response(fields["name"])

    flash(f'{fields["name"]} was added successfully.', "success")
    return redirect(url_for("add_author"))


if __name__ == "__main__":
    app.run(debug=True)
