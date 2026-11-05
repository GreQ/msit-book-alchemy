# Sample library data

The app seeds ten sample books by five authors using data from the Open Library API
when the database has no books. To add any missing sample books to an existing
database, run:

```powershell
uv run python seed_data.py
```

The seeder preserves existing records and stores ISBN-10 values as strings.
