# Sample library data

The app seeds ten sample books by five authors using data from the Open Library API
when the database has no books. To add any missing sample books to an existing
database, run:

```powershell
uv run python seed_data.py
```

The seeder preserves existing records and stores ISBN-10 values as strings.

## Run the application

This project runs directly from `app.py` rather than as an installed Python
package. Install dependencies with `uv sync`, then start Flask with:

```bash
uv run flask --app app run --host 0.0.0.0 --port 5000
```

In Codio, open the preview for port `5000`.

## Ratings and recommendations

Books can be rated from 1 to 10. Existing SQLite databases are updated at app
startup to add the nullable `rating` column without removing existing records.

To enable AI book recommendations, configure an OpenAI API key:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
```

The app uses `gpt-4o-mini` and OpenAI's chat-completions endpoint by default.
For an OpenAI-compatible provider, optionally set `OPENAI_BASE_URL` and
`OPENAI_MODEL`. Book titles, authors, and ratings are sent to that provider only
when a user submits the recommendation form.
