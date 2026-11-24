from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class Author(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(nullable=False, unique=True)
    birth_date: Mapped[datetime] = mapped_column(nullable=False)
    date_of_death: Mapped[datetime | None] = mapped_column(nullable=True)

    books: Mapped[list["Book"]] = db.relationship(
        "Book",
        back_populates="author",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f'<Author {self.name}>'

    def __str__(self):
        return (
            f'Author: {self.name}, '
            f'Birth Date: {self.birth_date}, '
            f'Date of Death: {self.date_of_death}'
        )


class Book(db.Model):
    __table_args__ = (
        db.CheckConstraint(
            "rating IS NULL OR rating BETWEEN 1 AND 10",
            name="ck_book_rating_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    isbn: Mapped[str] = mapped_column(
        db.String(10), nullable=False, unique=True
    )
    title: Mapped[str] = mapped_column(nullable=False)
    publication_year: Mapped[datetime]
    author_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey('author.id'), nullable=False
    )
    rating: Mapped[int | None] = mapped_column(db.Integer, nullable=True)

    author: Mapped[Author] = db.relationship(
        "Author",
        back_populates="books",
    )

    def __repr__(self):
        return f'<Book {self.title}>'

    def __str__(self):
        return (
            f'Book: {self.title}, '
            f'Publication Date: {self.publication_year}, '
            f'Author: {self.author.name}'
        )


print("Data models defined successfully.")
