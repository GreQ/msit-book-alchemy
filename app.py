import json
import re
from datetime import date
from os import getenv, path
from secrets import token_hex
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from data_models import db, Author, Book

DB_NAME = "library.sqlite"
DB_PATH = path.join(path.dirname(__file__), "data", DB_NAME)

app = Flask(__name__)
app.config["SECRET_KEY"] = getenv("SECRET_KEY") or token_hex(32)
app.config["OPENAI_API_KEY"] = getenv("OPENAI_API_KEY")
app.config["OPENAI_BASE_URL"] = getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
app.config["OPENAI_MODEL"] = getenv("OPENAI_MODEL", "gpt-4o-mini")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
db.init_app(app)

with app.app_context():
    print("Creating database tables...")
    db.create_all()
    book_columns = {column["name"] for column in db.inspect(db.engine).get_columns("book")}
    if "rating" not in book_columns:
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE book ADD COLUMN rating INTEGER "
                "CHECK (rating IS NULL OR rating BETWEEN 1 AND 10)"
            )
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
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(Book.title.ilike(f"%{escaped_query}%", escape="\\"))

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
    flash(f'{name} and all of their books were deleted successfully.', "success")
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
                "Set OPENAI_API_KEY to enable recommendations. You can also set "
                "OPENAI_BASE_URL and OPENAI_MODEL for an OpenAI-compatible provider."
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
                            "Recommend one book the reader has not already read. "
                            "Use their library and optional ratings to tailor your "
                            "choice. Briefly explain why it suits them."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(library, ensure_ascii=False),
                    },
                ],
            }
            api_request = Request(
                f'{app.config["OPENAI_BASE_URL"].rstrip("/")}/chat/completions',
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
                recommendation_text = result["choices"][0]["message"]["content"]
                if not isinstance(recommendation_text, str) or not recommendation_text.strip():
                    raise ValueError("The recommendation provider returned empty text.")
            except HTTPError as error:
                error_message = (
                    f"The recommendation provider returned HTTP {error.code}."
                )
            except (URLError, TimeoutError) as error:
                error_message = f"Could not reach the recommendation provider: {error.reason if isinstance(error, URLError) else 'request timed out'}."
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
                error_message = "The recommendation provider returned an invalid response."

    return render_template(
        "recommendation.html",
        recommendation_text=recommendation_text,
        error_message=error_message,
        api_configured=bool(app.config["OPENAI_API_KEY"]),
    ), 502 if error_message and app.config["OPENAI_API_KEY"] else 200

@app.route("/add_book", methods=["GET", "POST"])
def add_book():
    if request.method == "POST":
        data = request.form
        title = data.get("title")
        isbn = data.get("isbn", "").replace("-", "")
        publication_year = date.fromisoformat(data.get("publication_year")) if data.get("publication_year") else None
        author_id = data.get("author_id")

        if not all([title, isbn, publication_year, author_id]):
            return jsonify({"error": "Missing required fields"}), 400

        if not re.fullmatch(r"[0-9]{10}", isbn):
            return jsonify({"error": "ISBN must contain exactly 10 digits; hyphens are allowed"}), 400

        new_book = Book(title=title, isbn=isbn, publication_year=publication_year, author_id=author_id)
        db.session.add(new_book)
        db.session.commit()

        return jsonify({"message": "Book added successfully"}), 201

    authors = db.session.execute(db.select(Author).order_by(Author.name)).scalars()
    return render_template("add_book.html", authors=authors)

@app.route("/add_author", methods=["GET", "POST"])
def add_author():
    if request.method == "POST":
        name = request.form.get("name")
        birth_date_str = request.form.get("birthdate")
        date_of_death_str = request.form.get("date_of_death")
        birth_date_ = date.fromisoformat(birth_date_str) if birth_date_str else None
        date_of_death_ = date.fromisoformat(date_of_death_str) if date_of_death_str else None

        if not name:
            return jsonify({"error": "Missing required field: name"}), 400

        new_author = Author(name=name, birth_date=birth_date_, date_of_death=date_of_death_)
        db.session.add(new_author)
        db.session.commit()

        return jsonify({"message": "Author added successfully"}), 201
        #return redirect(url_for("user_detail", id=user.id))

    return render_template("add_author.html")

if __name__ == "__main__":
    app.run(debug=True)
