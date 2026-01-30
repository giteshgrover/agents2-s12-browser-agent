# Agentic Browser Automation System

An intelligent agent system that autonomously interacts with web browsers and other tools through the Model Context Protocol (MCP). The system uses a Perception-Decision-Action loop to understand user queries, plan multi-step actions, execute them safely, and learn from past sessions.

## 🏗️ Architecture Overview

The system follows a modular architecture with the following key components:

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interface (CLI)                      │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Agent Loop (Core)                         │
│                                                               │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ Perception  │───▶│  Decision   │───▶│   Action    │     │
│  │             │    │             │    │             │     │
│  │ • Analyze   │    │ • Plan      │    │ • Execute   │     │
│  │   state     │    │   steps     │    │   code      │     │
│  │ • Check     │    │ • Generate  │    │ • Call MCP  │     │
│  │   progress  │    │   variants  │    │   tools     │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│         │                  │                  │             │
│         └──────────────────┴──────────────────┘             │
│                            │                                  │
│                            ▼                                  │
│                   ┌─────────────┐                            │
│                   │ Summarizer  │                            │
│                   └─────────────┘                            │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              MultiMCP Dispatcher                             │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Browser    │  │  Documents   │  │   Other      │       │
│  │   MCP Server │  │  MCP Server  │  │   MCP        │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

1. **Agent Loop** - Orchestrates the Perception-Decision-Action cycle
2. **Perception** - Analyzes current state and determines goal progress
3. **Decision** - Plans next steps and generates executable code
4. **Action** - Executes code in a sandboxed environment with MCP tools
5. **MultiMCP** - Manages multiple MCP servers (browser, documents, etc.)
6. **Context Manager** - Maintains execution state and step graph
7. **Memory System** - Searches past sessions for relevant context
8. **Summarizer** - Generates final summaries when goals are achieved

## 📋 Detailed Architecture

For a comprehensive architecture documentation with detailed diagrams, component descriptions, data flows, and extension points, see [ARCHITECTURE.md](./ARCHITECTURE.md).

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- `uv` package manager
- Ollama models installed (if using local models)
- Spacy model: `en_core_web_sm`

### Setup

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Install Spacy model:**
   ```bash
   uv run python -m spacy download en_core_web_sm
   ```

3. **Configure environment:**
   - Create `.env` file with required API keys
   - Update `config/mcp_server_config.yaml` with your MCP server configurations

4. **Start Browser MCP Server** (in a separate terminal):
   ```bash
   uv run browserMCP/browser_mcp_sse.py
   ```

5. **Run the main application:**
   ```bash
   uv run main.py
   ```

## 📖 Usage

The system runs in an interactive CLI mode. Simply type your query and the agent will:

1. Search memory for relevant past sessions
2. Analyze your query and current context
3. Plan and execute multi-step actions
4. Monitor progress and adapt as needed
5. Return a comprehensive summary

### Example Queries

- "Open https://www.example.com and click on the Demo button"
- "Find the main differences between BMW 7 and 5 series online"
- "Search local documents for information about DLF"
- "Summarize this page: https://theschoolof.ai/"

## 🔧 Configuration

### MCP Server Configuration

Edit `config/mcp_server_config.yaml` to add or modify MCP servers:

```yaml
mcp_servers:
  - id: webbrowsing
    script: http://localhost:8100/sse
    transport: sse
    description: "Full Browser Access (persistent)"
  
  - id: documents
    script: mcp_server_2.py
    cwd: /path/to/mcp_servers
    transport: stdio
    description: "Document search and extraction"
```

### Model Configuration

Configure LLM models in `config/models.json` and set API keys in `.env`.

## 📁 Project Structure

```
agents2-s12-browser-agent/
├── agent/              # Core agent logic
│   ├── agent_loop3.py  # Main orchestration loop
│   ├── contextManager.py
│   └── agentSession.py
├── perception/         # State analysis module
├── decision/          # Planning module
├── action/            # Code execution module
├── memory/            # Session memory and search
├── summarization/     # Final summary generation
├── browserMCP/        # Browser MCP server
├── mcp_servers/       # MCP server implementations
├── config/            # Configuration files
└── main.py            # Entry point
```

## 🔄 Execution Flow

```
User Query
    │
    ▼
Memory Search → Find relevant past sessions
    │
    ▼
Perception → Analyze query and context
    │
    ▼
Decision → Plan steps and generate code
    │
    ▼
Action → Execute code and call MCP tools
    │
    ▼
Perception → Analyze results
    │
    ├─ Goal Met? → Summarize → Return
    └─ Continue? → Back to Decision
```

## 🛡️ Safety Features

- **Sandboxed Execution**: Code runs in a restricted environment
- **AST Transformations**: Automatic safety transformations
- **Tool Access Control**: Only MCP tools are accessible
- **Timeout Protection**: Prevents infinite loops
- **Error Recovery**: Automatic retries with fallback variants

## 📊 State Management

The system maintains:
- **Execution Graph**: Tracks step dependencies and status
- **Session State**: Variables accessible across steps
- **Memory Index**: Searchable index of past sessions
- **Perception History**: Record of all state analyses

## 🔍 Memory System

The memory system:
- Indexes past session summaries
- Uses fuzzy matching and NER for search
- Retrieves relevant context automatically
- Improves with each session

## 🐛 Troubleshooting

See [HOWTORUN.md](./HOWTORUN.md) for common issues and solutions.

### Common Issues

1. **MCP Server Connection**: Ensure browser MCP server is running
2. **LLM API Errors**: Check API keys and rate limits
3. **Memory Search**: Rebuild index if needed
4. **Code Execution**: Verify tool availability and arguments

## 📚 Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - Detailed architecture documentation
- [HOWTORUN.md](./HOWTORUN.md) - Setup and troubleshooting guide

## 🤝 Contributing

When extending the system:
- Add new MCP servers via configuration
- Implement custom tools in MCP servers
- Extend perception/decision logic as needed
- Follow existing patterns for consistency

## 📝 License

[Add your license information here]

## 🙏 Acknowledgments

Built with:
- Model Context Protocol (MCP)
- Playwright for browser automation
- Gemini API for LLM capabilities
- NetworkX for graph management
