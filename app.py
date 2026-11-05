from flask import Flask, render_template, request, jsonify
from data_models import db, Author, Book
from os import path
from datetime import date
import re

DB_NAME = "library.sqlite"
DB_PATH = path.join(path.dirname(__file__), "data", DB_NAME)

app = Flask(__name__)
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
    books = db.session.execute(db.select(Book).order_by(Book.title)).scalars()
    return render_template("home.html", books=books)

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
