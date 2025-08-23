# Support Call Sentiment & Quality Analyzer

Analyze customer support transcripts for sentiment, emotions, tone, events, and resolution using Azure OpenAI, then store key fields in PostgreSQL. This folder contains a runnable Jupyter notebook plus the system prompt and a sample TSV (tab‑separated) dataset.

## What's here

- `Analysis.ipynb` — end‑to‑end pipeline: load transcripts, call Azure OpenAI with a strict JSON schema, parse results, and insert into Postgres.
- `instructions.md` — the system prompt defining the JSON schema, scoring rules, and heuristics.
- `transcripts.csv` — sample dataset (TSV: tab‑separated) with multi‑line transcripts.

## Requirements

- Python 3.10+
- A PostgreSQL instance you can write to
- Azure OpenAI resource and model deployment

Python packages (install in your environment):

- jupyter
- python-dotenv
- openai (1.x, includes `AzureOpenAI`)
- requests
- psycopg2-binary

Optional, copyable install commands (PowerShell):

```powershell
pip install jupyter python-dotenv openai requests psycopg2-binary
```

## Configuration

Create a `.env` file at the repository root (one level up from this folder) with these keys:

```ini
AZURE_OPENAI_BASE_URL=https://<your-openai-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_VERSION=2024-02-01
AZURE_OPENAI_MODEL_NAME=<your-deployment-name>

DB_HOST=<postgres-host>
DB_PORT=5432
DB_NAME=<database>
DB_USER=<user>
DB_PASS=<password>
```

The notebook loads this via `dotenv_values("../.env")`.

## Database schema

The notebook inserts a subset of the model output into a `conversations` table. Create a table that matches the fields used:

```sql
CREATE TABLE IF NOT EXISTS conversations (
	conversationID UUID PRIMARY KEY,
	userID TEXT,
	transcript TEXT,
	customer_sentiment TEXT,
	dominant_customer_emotion TEXT,
	customer_sentiment_confidence NUMERIC,
	date TEXT, -- or DATE if you normalize the source format
	notes TEXT,
	topics TEXT[],     -- from completion.topics[*].label
	keywords TEXT[]     -- flattened completion.topics[*].keywords_detected
);
```

If you prefer, you can store the full JSON response as a `JSONB` column in an additional field.

## Data format

`transcripts.csv` is actually TSV (tab‑separated) and read with `delimiter='\t'`. Columns:

- `conversationId`, `userId`, `date`, `time`, `transcript`
- `transcript` contains multi‑line content wrapped in quotes.

## How it works

1. Loads `.env` and database credentials.
2. Reads `transcripts.csv` (TSV) into memory.
3. Reads `instructions.md` as the system prompt, which enforces a strict JSON output schema.
4. Calls Azure OpenAI Chat Completions (`AzureOpenAI`) for each transcript.
5. Parses the model's JSON string into a Python object.
6. Maps selected fields into a row and inserts into Postgres.
7. Sleeps 10 seconds between calls to be gentle on rate limits.

## Run the analysis

1. Ensure Postgres is reachable and the `conversations` table exists.
2. Ensure `.env` is populated (see Configuration).
3. Start Jupyter and open the notebook:

```powershell
jupyter notebook
```

4. Run all cells in `Analysis.ipynb`.

## Notes and guardrails

- PII: The prompt forbids inventing/exposing PII; keep redactions like `[REDACTED]` intact.
- JSON: The model must return valid JSON (no commentary). If you see JSON decode errors, re‑run the cell; consider adding defensive validation if needed.
- Types: `topics`/`keywords` are arrays; ensure your table uses `TEXT[]` (or adapt the insert to cast appropriately).
- Rate limits: The notebook uses `time.sleep(10)` between requests; adjust if your quota allows.

## Troubleshooting

- Auth errors to Azure OpenAI: verify `AZURE_OPENAI_BASE_URL`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_VERSION`, and deployment name.
- psycopg2 build issues: use `psycopg2-binary` (already listed above).
- CSV parsing: ensure the file remains tab‑separated; do not convert to comma‑separated.

## Extending

- Store full JSON responses for richer analytics (segments, events, quality flags).
- Add a small CLI or batch script to run outside Jupyter.
- Create dashboards on top of the `conversations` table.

