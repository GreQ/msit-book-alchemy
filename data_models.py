from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
  pass

db = SQLAlchemy(model_class=Base)

class Author(db.Model):
    id: Mapped[int]  = mapped_column(primary_key=True, autoincrement=True) #db.Column(db.Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(nullable=False)
    birth_date: Mapped[datetime]
    date_of_death: Mapped[datetime]

    def __repr__(self):
        return f'<Author {self.name}>'

    def __str__(self):
        return f'Author: {self.name}, Birth Date: {self.birth_date}, Date of Death: {self.date_of_death}'

class Book(db.Model):
    id: Mapped[int]  = mapped_column(primary_key=True, autoincrement=True)
    isbn: Mapped[str] = mapped_column(nullable=False, unique=True)
    title: Mapped[str] = mapped_column(nullable=False)
    publication_year: Mapped[datetime]
    author_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('author.id'), nullable=False)

    #author: Mapped[Author] = db.relationship('Author', backref=db.backref('books', lazy=True))

    def __repr__(self):
        return f'<Book {self.title}>'

    def __str__(self):
        return f'Book: {self.title}, Publication Date: {self.publication_year}, Author: {self.author.name}'


print("Data models defined successfully.")