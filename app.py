from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from data_models import db, Author, Book
from os import getenv, path
from datetime import date
import re
from secrets import token_hex

DB_NAME = "library.sqlite"
DB_PATH = path.join(path.dirname(__file__), "data", DB_NAME)

app = Flask(__name__)
app.config["SECRET_KEY"] = getenv("SECRET_KEY") or token_hex(32)
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
    return render_template(
        "home.html", books=books, sort_by=sort_by, query=query
    )

@app.route("/book/<int:book_id>/delete", methods=["POST"])
def delete_book(book_id):
    book = db.get_or_404(Book, book_id)
    author = book.author
    title = book.title

    db.session.delete(book)
    db.session.flush()
    if db.session.execute(
        db.select(Book.id).where(Book.author_id == author.id).limit(1)
    ).first() is None:
        db.session.delete(author)

    db.session.commit()
    flash(f'"{title}" was deleted successfully.', "success")
    return redirect(
        url_for(
            "index",
            q=request.form.get("q", ""),
            sort=request.form.get("sort", "title"),
        )
    )

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
