from typing import List, cast, Any, Dict

import json
import re
import chainlit as cl
import yaml
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage
from autogen_core import CancellationToken
from autogen_core.models import ChatCompletionClient
from dotenv import dotenv_values

config = dotenv_values("../.env")


@cl.set_starters  # type: ignore
async def set_starts() -> List[cl.Starter]:
    return [
        cl.Starter(
            label="Greetings",
            message="Hello! What can you help me with today?",
        ),
        cl.Starter(
            label="Summarize",
            message="Summarize the key points from the most recent conversation.",
        ),
    ]


def _clean_sql(sql_text: str) -> str:
    """Normalize model output to a bare SQL string."""
    # Strip code fences
    sql = sql_text.strip()
    sql = re.sub(r"^```sql\s*|^```\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"```\s*$", "", sql)
    sql = re.sub(r"\n", " ", sql)
    # Remove surrounding quotes if any
    sql = sql.strip().strip("\"").strip("'")
    # Keep only the first statement if multiple
    if ";" in sql:
        parts = [p.strip() for p in sql.split(";") if p.strip()]
        if parts:
            sql = parts[0]
    # Ensure it's a SELECT
    return sql


@cl.step(type="tool")  # type: ignore
async def run_postgres_query(sql: str, max_rows: int = 100) -> str:
    """Execute a read-only Postgres query and return JSON string of results.

    The connection string is taken from DB_* env vars.
    Only SELECT queries are allowed. Results are truncated to `max_rows`.
    """
    # Lazy import to avoid hard dependency when not used
    try:
        import asyncpg  # type: ignore
    except Exception as e:  # pragma: no cover - import-time error path
        raise RuntimeError(
            "The 'asyncpg' package is required. Install it in your environment."
        ) from e

    sql_clean = _clean_sql(sql)
    if not re.match(r"^\s*select\b", sql_clean, flags=re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")

    # Execute query
    conn = await asyncpg.connect(
        host=config["DB_HOST"],
        port=config["DB_PORT"],
        database=config["DB_NAME"],
        user=config["DB_USER"],
        password=config["DB_PASS"],
    )
    try:
        rows = await conn.fetch(sql_clean)
        # Convert records to list of dicts
        list_rows: List[Dict[str, Any]] = [dict(r) for r in rows[:max_rows]]
        # Truncate each cell string to avoid huge payloads
        def _truncate_val(v: Any, max_len: int = 2000) -> Any:
            if isinstance(v, str) and len(v) > max_len:
                return v[: max_len - 3] + "..."
            return v

        list_rows = [
            {k: _truncate_val(v) for k, v in row.items()} for row in list_rows
        ]

        payload = {
            "row_count": len(rows),
            "returned_rows": len(list_rows),
            "columns": list(list_rows[0].keys()) if list_rows else [],
            "rows": list_rows,
        }
        # Compact JSON to reduce socket size
        return json.dumps(payload, default=str, separators=(",", ":"))
    finally:
        await conn.close()


@cl.on_chat_start  # type: ignore
async def start_chat() -> None:
    # Load model configuration and create the model client.
    with open("model_config.yaml", "r") as f:
        model_config = yaml.safe_load(f)
    model_client = ChatCompletionClient.load_component(model_config)

    # Agent 1: SQL generator
    sql_agent = AssistantAgent(
        name="sql_agent",
        tools=[run_postgres_query],
        model_client=model_client,
        system_message=(
            """You are a senior data analyst who writes Postgres SQL and can execute it via the tool run_postgres_query(sql: str, max_rows: int = 100).

Decide first if the user is asking to retrieve or analyze database data. If YES:
- Produce a single valid Postgres SELECT (read-only), then CALL the tool run_postgres_query with that SQL.
- In your final assistant message, include exactly two lines in addition to any brief context:
    SQL: <the exact SQL you used>
    RESULT_JSON: <the compact JSON returned by the tool>

If NO (not a data request):
- Do NOT call any tools. Briefly answer why no data fetch is needed.
- Include the same two lines with empty values:
    SQL:
    RESULT_JSON: {}

Schema:
- Table: conversations
  - conversationid UUID PRIMARY KEY: unique conversation identifier
  - userid TEXT: user identifier
  - transcript TEXT: full conversation text
  - customer_sentiment VARCHAR(50): e.g., positive/neutral/negative
  - dominant_customer_emotion VARCHAR(50): e.g., joy/anger/fear/sadness
  - customer_sentiment_confidence DECIMAL(5,4): confidence score in [0,1]
  - date DATE: conversation date (YYYY-MM-DD)
  - notes TEXT: analyst notes
  - topics TEXT[]: array of topic strings
  - keywords TEXT[]: array of keyword strings

Guidelines:
- Only read from conversations using Postgres syntax.
- Use ILIKE for case-insensitive search in transcript or notes.
- Filter arrays:
  - Single value membership: 'value' = ANY(topics) or 'value' = ANY(keywords)
  - Any overlap with a set: topics && ARRAY['a','b'] or keywords && ARRAY['x','y']
  - Aggregations by array values: SELECT unnest(topics) AS topic, COUNT(*) ... GROUP BY topic
- Date filtering and grouping:
  - Ranges: WHERE date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
  - Grouping: date_trunc('day'|'week'|'month', date) AS period
- Aggregations:
  - Use COUNT(*), COUNT(DISTINCT ...), AVG(customer_sentiment_confidence), etc.
  - Group by selected dimensions and order by metrics as appropriate.
- Return only relevant columns; include ORDER BY and LIMIT when returning raw rows.
- If the request is ambiguous, make the most reasonable assumption and produce the best single SELECT accordingly."""
        ),
        model_client_stream=True,
        reflect_on_tool_use=True,
    )

    # Agent 2: Summarizer
    summarizer_agent = AssistantAgent(
        name="summarizer_agent",
        tools=[],
        model_client=model_client,
        system_message=(
            "You summarize SQL query results for business users. "
            "Explain findings clearly, include key metrics and trends, and mention row counts. "
            "Be concise and avoid technical jargon."
        ),
        model_client_stream=True,
        reflect_on_tool_use=False,
    )

    # Agent 3: General assistant (fallback for non-analytics requests)
    general_agent = AssistantAgent(
        name="general_agent",
        tools=[],
        model_client=model_client,
        system_message=(
            "You are a helpful assistant for general questions. Answer clearly and concisely."
        ),
        model_client_stream=True,
        reflect_on_tool_use=False,
    )

    # Agent 4: Router that decides whether to use SQL flow or general assistant
    router_agent = AssistantAgent(
        name="router_agent",
        tools=[],
        model_client=model_client,
        system_message=(
            "You are a router. Decide if the user's request is about conversation data or analytics "
            "related to the 'conversations' database/table (queries, metrics, summaries, trends, topics, sentiments).\n"
            "If YES, reply exactly: ROUTE: SQL\n"
            "If NO, reply exactly: ROUTE: GENERAL\n"
            "No extra text."
        ),
        model_client_stream=True,
        reflect_on_tool_use=False,
    )

    # Save agents in session
    cl.user_session.set("sql_agent", sql_agent)  # type: ignore
    cl.user_session.set("summarizer_agent", summarizer_agent)  # type: ignore
    cl.user_session.set("general_agent", general_agent)  # type: ignore
    cl.user_session.set("router_agent", router_agent)  # type: ignore


@cl.on_message  # type: ignore
async def chat(message: cl.Message) -> None:
    # Orchestration: Route to SQL analytics flow or general assistant.
    sql_agent = cast(AssistantAgent, cl.user_session.get("sql_agent"))  # type: ignore
    summarizer_agent = cast(AssistantAgent, cl.user_session.get("summarizer_agent"))  # type: ignore
    general_agent = cast(AssistantAgent, cl.user_session.get("general_agent"))  # type: ignore
    router_agent = cast(AssistantAgent, cl.user_session.get("router_agent"))  # type: ignore

    # Step 0: Route
    route_text = ""
    async for msg in router_agent.on_messages_stream(
        messages=[TextMessage(content=message.content, source="user")],
        cancellation_token=CancellationToken(),
    ):
        if isinstance(msg, ModelClientStreamingChunkEvent):
            route_text += msg.content
        elif isinstance(msg, Response):
            route_text = route_text.strip()

    route = "GENERAL"
    if re.search(r"ROUTE:\s*SQL", route_text, flags=re.IGNORECASE):
        route = "SQL"

    if route == "GENERAL":
        # Stream the general assistant response
        response = cl.Message(content="")
        async for msg in general_agent.on_messages_stream(
            messages=[TextMessage(content=message.content, source="user")],
            cancellation_token=CancellationToken(),
        ):
            if isinstance(msg, ModelClientStreamingChunkEvent):
                await response.stream_token(msg.content)
            elif isinstance(msg, Response):
                await response.send()
        return

    # SQL route: let the SQL agent reason and (optionally) call the tool, then summarize
    agent_output: str = ""
    async for msg in sql_agent.on_messages_stream(
        messages=[
            TextMessage(
                content=(
                    "Determine if this is a data request. If yes, write a single SELECT and call run_postgres_query, "
                    "then include 'SQL:' and 'RESULT_JSON:' lines in your final answer. If no, do not call tools and include empty JSON.\n\n"
                    + "User request: "
                    + message.content
                ),
                source="user",
            )
        ],
        cancellation_token=CancellationToken(),
    ):
        if isinstance(msg, ModelClientStreamingChunkEvent):
            # Buffer tokens only (avoid many socket packets)
            agent_output += msg.content
        elif isinstance(msg, Response):
            agent_output = agent_output.strip()

    # Extract SQL and RESULT_JSON from the agent output
    sql_match = re.search(r"SQL:\s*(.*)", agent_output)
    generated_sql = _clean_sql(sql_match.group(1)) if sql_match else ""
    json_match = re.search(r"RESULT_JSON:\s*(\{.*\})", agent_output, flags=re.DOTALL)
    results_json = json_match.group(1) if json_match else "{}"

    if generated_sql and generated_sql != "RESULT_JSON: {}":
        await cl.Message(content=f"Generated SQL:\n{generated_sql}").send()

    # Optional meta preview
    meta = ""
    try:
        preview = json.loads(results_json)
        meta = f"Rows returned: {preview.get('returned_rows', 0)} (of {preview.get('row_count', 0)})"
    except Exception:
        pass
    if meta:
        await cl.Message(content=f"Executed query. {meta}").send()

    # Step 2: Summarize results (send once to avoid too many socket packets)
    summary_prompt = (
        "User request: "
        + message.content
        + "\n\nSQL used:\n"
        + (generated_sql or "")
        + "\n\nResults (JSON):\n"
        + results_json
        + "\n\nSummarize the results clearly for a business user."
    )
    summary_text = ""
    async for msg in summarizer_agent.on_messages_stream(
        messages=[TextMessage(content=summary_prompt, source="user")],
        cancellation_token=CancellationToken(),
    ):
        if isinstance(msg, ModelClientStreamingChunkEvent):
            summary_text += msg.content
        elif isinstance(msg, Response):
            await cl.Message(content=summary_text.strip()).send()