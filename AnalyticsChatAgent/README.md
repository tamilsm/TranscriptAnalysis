# Analytics Chat Agent

A Chainlit-powered assistant that routes user requests to the right capability:

- SQL analytics for conversation data in Postgres (via a tool-enabled SQL agent)
- Clear, plain-language summaries of query results
- A general assistant fallback for non-analytics questions

This agent is optimized for exploring a `conversations` table created by the Sentiment & Quality analysis pipeline in `SentimentAnalysis/`.

## What it does

- Routes: A lightweight router decides if a request is about conversation data/analytics. If yes, it invokes the SQL flow; otherwise it answers generally.
- SQL generation and execution: The SQL agent generates a single, safe Postgres SELECT and executes it using a tool (`run_postgres_query`). Only read-only queries are allowed.
- Summarization: A summarizer agent explains the results in business-friendly language.
- Streaming UI: Responses are streamed in the Chainlit web app.

## Architecture

Agents (all in `agent.py`):
- router_agent: returns `ROUTE: SQL` or `ROUTE: GENERAL`
- sql_agent: writes Postgres SQL and calls the tool to run it
- summarizer_agent: turns raw results into concise insights
- general_agent: answers non-analytics questions

Tool:
- run_postgres_query(sql: str, max_rows: int = 100) -> JSON string
  - Only executes read-only SELECTs
  - Returns a compact JSON payload with columns, rows, and counts

## Requirements

- Python 3.10+
- A PostgreSQL database reachable from your machine
- Credentials for your model provider (Azure OpenAI or OpenAI)

Python packages (install in your environment):
- chainlit
- autogen-agentchat
- autogen-core
- autogen-ext
- asyncpg
- python-dotenv
- pyyaml

Optional, copyable install command (PowerShell):

```powershell
pip install chainlit autogen-agentchat autogen-core autogen-ext asyncpg python-dotenv pyyaml
```

## Configuration

1) Database credentials

Create a `.env` file at the repository root (one level up from this folder) with:

```ini
DB_HOST=<postgres-host>
DB_PORT=5432
DB_NAME=<database>
DB_USER=<user>
DB_PASS=<password>
```

The app loads this with `dotenv_values("../.env")`.

2) Model configuration

Edit `AnalyticsChatAgent/model_config.yaml` and choose one of:
- Azure OpenAI with API key
- Azure OpenAI with Azure AD token provider
- OpenAI with API key

The file already contains commented examples for each. Replace placeholders with your values. Do not commit real secrets.

3) Table schema (expected)

The SQL agent expects a `conversations` table similar to:

```sql
CREATE TABLE IF NOT EXISTS conversations (
  conversationid UUID PRIMARY KEY,
  userid TEXT,
  transcript TEXT,
  customer_sentiment VARCHAR(50),
  dominant_customer_emotion VARCHAR(50),
  customer_sentiment_confidence DECIMAL(5,4),
  date DATE,
  notes TEXT,
  topics TEXT[],
  keywords TEXT[]
);
```

This is compatible with the pipeline in `SentimentAnalysis/`.

## Run the app

From this folder (`AnalyticsChatAgent/`):

```powershell
# optional: create a virtual env first
# python -m venv .venv; .\.venv\Scripts\Activate.ps1

# install dependencies
pip install chainlit autogen-agentchat autogen-core autogen-ext asyncpg python-dotenv pyyaml

# launch the UI
python -m chainlit run agent.py
```

Chainlit will print a local URL (typically http://localhost:8000).

## Usage examples

Ask analytics questions (routes to SQL):
- "Show the top 10 topics in the last 30 days."
- "Trend of negative sentiment by week for Q2."
- "List 20 conversations mentioning 'refund' with date and sentiment."
- "Average customer_sentiment_confidence by topic."

Ask general questions (routes to general assistant):
- "What's a good way to phrase a follow-up email?"
- "Explain the difference between sentiment and emotion."

## How routing works

- The router inspects the user’s message. If it’s about querying, analyzing, or summarizing conversation data (metrics, trends, topics, sentiments), it replies `ROUTE: SQL`, else `ROUTE: GENERAL`.
- SQL route: The SQL agent generates one SELECT and calls `run_postgres_query`. It includes exactly two lines at the end of its final message:
  - `SQL: <the exact SQL>`
  - `RESULT_JSON: <the tool’s compact JSON>`
- The summarizer then turns that into a short, useful narrative.

## Contract of the SQL tool

- Input: a single Postgres SELECT statement
- Output: JSON string with keys: `row_count`, `returned_rows`, `columns`, `rows`
- Safety: non-SELECT queries are rejected
- Limits: results truncated to `max_rows` (default 100); long strings truncated per-cell

## Troubleshooting

- Chainlit not found: ensure it’s installed and the right Python is active
- Model auth errors: verify `model_config.yaml` values (endpoint, deployment/model, API version, and credentials)
- Postgres connect errors: verify `.env` is present at repo root and that your network/firewall allows access
- Missing packages: re-run the pip install line shown above

## Notes

- Keep API keys out of source control. Prefer secrets managers where possible.
- If your table uses slightly different field names/types, adjust queries or the summarization accordingly.
- You can switch models by editing `model_config.yaml` without changing code.
