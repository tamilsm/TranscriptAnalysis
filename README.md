# TranscriptAnalysis

Analyze support call transcripts end-to-end: first generate structured insights with Azure OpenAI, store them in PostgreSQL, and then explore the results with a chat agent that answers analytics questions using safe SQL.

## Projects in this repo

- SentimentAnalysis — Jupyter notebook pipeline that calls Azure OpenAI to analyze transcripts and writes key fields to Postgres. See `SentimentAnalysis/README.md` for configuration and running the notebook.

- AnalyticsChatAgent — Chainlit app with an agentic router that:
	- detects conversation analytics requests and runs safe, read-only SQL against your `conversations` table
	- summarizes results in plain English
	- falls back to a general assistant for non-analytics questions
	See `AnalyticsChatAgent/README.md` for setup and run instructions.

## End-to-end setup (recommended order)

1) Install PostgreSQL and prepare the database

- Install PostgreSQL locally (or use a managed Postgres). Create a database and user you can connect with.
- Create the `conversations` table used by both projects:

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

2) Create Azure resources for the model

- Provision an Azure OpenAI resource and deploy a suitable chat model.
- Collect: endpoint URL, API key (or configure AAD), API version, and deployment name.

3) Configure environment variables

Create a `.env` file at the repository root with DB and Azure OpenAI values:

```ini
DB_HOST=<postgres-host>
DB_PORT=5432
DB_NAME=<database>
DB_USER=<user>
DB_PASS=<password>

# Used by SentimentAnalysis notebook
AZURE_OPENAI_BASE_URL=https://<your-openai-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_VERSION=2024-02-01
AZURE_OPENAI_MODEL_NAME=<your-deployment-name>
```

Do not commit real secrets. Prefer environment variables or a secret manager for production.

4) Run Sentiment Analysis (populate Postgres)

From `SentimentAnalysis/`:

```powershell
pip install jupyter python-dotenv openai requests psycopg2-binary
jupyter notebook
```

Open `Analysis.ipynb`, ensure your `.env` is loaded, and run all cells to generate and insert analytics into the `conversations` table.

5) Run the Analytics Chat Agent (explore insights)

From `AnalyticsChatAgent/`:

```powershell
# optional: create a virtual env
# python -m venv .venv; .\.venv\Scripts\Activate.ps1

pip install chainlit autogen-agentchat autogen-core autogen-ext asyncpg python-dotenv pyyaml
python -m chainlit run agent.py
```

Then open the local URL printed by Chainlit (e.g., http://localhost:8000). Example questions:
- "Top topics in the last 30 days"
- "Weekly trend of negative sentiment in Q2"
- "Conversations mentioning refund with date and sentiment"

Configure the model in `AnalyticsChatAgent/model_config.yaml` (Azure OpenAI or OpenAI). Keep keys out of source control.

## License

MIT (unless otherwise noted).
