# Logix: Data Analysis Engine

Logix is a multi-agent AI system that lets you talk to your data in plain English. You ask a question, and Logix decides whether it needs to **query a database (SQL)** or **extract and transform data (ETL)**, and then hands the work to a specialist agent.

> Example: *"name all the payment methods in my database"* → Logix reads the database schema, writes a safe SQL query, runs it on PostgreSQL and returns a readable answer.

---

## Features

- **Natural language to SQL:** ask questions in plain English, no SQL knowledge needed.
- **Smart routing:** a Data Agent (router) sends each request to the right specialist agent.
- **Safe by design:** every generated SQL query is checked by a safety judge before it runs. Unsafe queries are cancelled.
- **ETL agent:** pulls data from an API, transforms it with Pandas and saves it to a destination folder, using a Reason → Act → Observe (ReAct) loop.
- **Stateful orchestration:** one shared state is passed through every node, so no information is lost between steps.
- **Model tiers:** light steps use a fast model, and harder steps (such as the ETL agent) use a larger model.

---

## How It Works

### 1. Data Agent (Router)
The user's question enters the Data Agent. An LLM classifies it as `sql` or `etl` and routes it to the matching analyst.

### 2. SQL Analyst (fixed pipeline)
1. **Curate Question:** cleans up and rewrites the question.
2. **Add Context:** fetches the table schema and sample rows from PostgreSQL.
3. **Generate SQL:** the LLM writes the SQL query.
4. **Safety Judge:** checks whether the query is safe. If not, the request is cancelled.
5. **Execute SQL:** runs the query on PostgreSQL.
6. **Represent Answer:** turns the result rows into a readable answer.

### 3. ETL Analyst (ReAct loop)
- **Reason:** the LLM reads the messages and decides what to do.
- **Act:** the tool node runs a tool (`extract_load`, `transform_load_context` or `execute_code`).
- **Observe:** the result goes back into the messages, and the loop repeats until no more tool calls are needed.

---

## Diagrams

Add the diagram images to a `docs/` folder and they will show up here.

| Diagram | Preview |
|---|---|
| Block diagram | ![Block diagram](docs/logix_block_diagram.png) |
| Flowchart | ![Flowchart](docs/logix_flowchart_color.png) |
| Workflow diagram | ![Workflow](docs/logix_workflow_simple.png) |
| Data Flow Diagram (Level 1) | ![DFD](docs/logix_dfd_color.png) |
| ER diagram (sample database) | ![ER diagram](docs/logix_database_er.png) |

---

## Tech Stack

| Part | Technology |
|---|---|
| Language | Python |
| Agent orchestration | LangGraph |
| LLM framework | LangChain |
| LLM provider | Groq (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`) |
| Database | PostgreSQL (`psycopg2`) |
| Data processing | Pandas |
| Configuration | python-dotenv |

---

## Project Structure

```
Data_Agent/
├── agents/
│   ├── data_agent.py        # Router: sends the question to SQL or ETL
│   ├── sql_analyst.py       # SQL pipeline (curate, context, generate, judge, run, represent)
│   └── etl_analyst.py       # ETL agent (ReAct loop with tools)
├── Models/
│   └── schema.py            # State schemas (DataAgentSchema, RouterSchema, ...)
├── utils/
│   ├── llm_pick.py          # Picks the LLM by tier: low / medium / high
│   ├── etl_tools.py         # ETL tools: extract_load, transform_load_context, execute_code
│   └── database.py          # PostgreSQL connection and schema helpers
├── data/                    # CSV files for the sample database
├── feed_db.py               # Creates the tables and loads the sample data
├── docs/                    # Diagrams
├── .env                     # Your secrets (never upload this)
├── .gitignore
└── README.md
```

> Adjust the file names above if yours are different.

---

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/<your-username>/<your-repo-name>.git
cd <your-repo-name>
```

### 2. Create a virtual environment (recommended)
```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac / Linux
```

### 3. Install the packages
```bash
pip install langgraph langchain langchain-core langchain-groq psycopg2-binary pandas requests python-dotenv
```

### 4. Create a `.env` file
Create a file named `.env` in the project folder:

```
GROQ_API_KEY=your_groq_api_key
host=localhost
port=5432
user=your_postgres_user
password=your_postgres_password
database=your_database_name
```

> **Never upload `.env` to GitHub.** Add it to `.gitignore`.

### 5. Load the sample database (optional)
Make sure PostgreSQL is running and the database exists, then run:
```bash
python feed_db.py
```
This creates the tables and loads the CSV files from the `data/` folder.

---

## Usage

Run the data agent:
```bash
python agents/data_agent.py
```

Inside the file, the question is passed like this:

```python
response = data_agent.invoke(
    {"messages": [HumanMessage(content="name all the payment methods in my database")],
     "route_response": ""}
)
print(response)
```

Change the text inside `HumanMessage` to ask your own question.

---

## Sample Database

The project includes a ride-sharing database for testing. It has five tables:

| Table | Purpose |
|---|---|
| `users` | Riders and drivers (`user_type` tells them apart) |
| `vehicles` | Vehicles owned by drivers |
| `rides` | Trips, with `rider_id` and `driver_id` pointing to `users` |
| `payments` | Payments for rides |
| `ratings` | Ratings given and received for rides |

Logix is not tied to this database. It reads the schema of whichever PostgreSQL database you connect it to.

---

## Security Notes

- API keys and database passwords stay in `.env` and are never committed.
- Generated SQL passes through a safety judge before execution.
- Use a database user with limited permissions when connecting Logix to real data.

---

## Author

**Khushi Singh**
