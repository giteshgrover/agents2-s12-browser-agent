# Architecture Documentation

## Overview

This is an **Agentic Browser Automation System** that uses a Perception-Decision-Action loop to autonomously interact with web browsers and other tools through the Model Context Protocol (MCP). The system can understand user queries, plan multi-step actions, execute them, and learn from past sessions.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Interface                          │
│                      (Interactive CLI Loop)                     │
└────────────────────────────┬──────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Main Entry Point                         │
│                            main.py                               │
│  • Initializes MultiMCP                                          │
│  • Creates AgentLoop instance                                    │
│  • Manages conversation history                                  │
└────────────────────────────┬──────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Loop (Core)                         │
│                      agent/agent_loop3.py                        │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Perception  │→ │   Decision   │→ │    Action    │          │
│  │              │  │              │  │              │          │
│  │ • Analyzes   │  │ • Plans next │  │ • Executes   │          │
│  │   state      │  │   steps      │  │   code       │          │
│  │ • Checks if  │  │ • Generates   │  │ • Calls MCP  │          │
│  │   goal met   │  │   variants   │  │   tools      │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                  │
│         └─────────────────┴──────────────────┘                  │
│                          │                                       │
│                          ▼                                       │
│                  ┌──────────────┐                               │
│                  │  Summarizer  │                               │
│                  │  (on success)│                               │
│                  └──────────────┘                               │
└────────────────────────────┬──────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Supporting Components                       │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Context    │  │    Memory    │  │   Model      │          │
│  │   Manager    │  │    Search    │  │   Manager    │          │
│  │              │  │              │  │              │          │
│  │ • Execution  │  │ • Searches   │  │ • LLM API    │          │
│  │   graph      │  │   past       │  │   calls      │          │
│  │ • State      │  │   sessions   │  │ • Gemini     │          │
│  │   tracking   │  │ • NER-based  │  │   integration│          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└────────────────────────────┬──────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MultiMCP Dispatcher                         │
│                    mcp_servers/multiMCP.py                       │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Browser    │  │  Documents   │  │   Other      │          │
│  │   MCP Server │  │  MCP Server  │  │   MCP        │          │
│  │   (SSE)      │  │  (stdio)    │  │   Servers    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Agent Loop (`agent/agent_loop3.py`)

The central orchestrator that implements the Perception-Decision-Action cycle.

**Key Responsibilities:**
- Manages the execution lifecycle
- Coordinates Perception, Decision, and Action modules
- Handles retries and error recovery
- Tracks execution state through ContextManager

**Execution Flow:**
```
User Query
    │
    ▼
┌─────────────────┐
│ Initial         │
│ Perception      │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Goal Met?  Route?
    │         │
    │         ▼
    │    ┌──────────┐
    │    │ Decision │
    │    └────┬─────┘
    │         │
    │         ▼
    │    ┌──────────┐
    │    │  Action  │
    │    │ Execute  │
    │    └────┬─────┘
    │         │
    │         ▼
    │    ┌──────────┐
    │    │Perception│
    │    │ (after)  │
    │    └────┬─────┘
    │         │
    └─────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Goal Met?  Continue?
    │         │
    ▼         │
┌──────────┐  │
│Summarizer│  │
└──────────┘  │
    │         │
    └─────────┘
```

### 2. Perception Module (`perception/perception.py`)

Analyzes the current state and determines progress toward the goal.

**Input:**
- Original query
- Current execution context
- Completed/failed steps
- Global variables
- Memory excerpts

**Output:**
- `entities`: Extracted entities from context
- `original_goal_achieved`: Boolean indicating if main goal is met
- `local_goal_achieved`: Boolean for current step goal
- `route`: Either "decision" (continue) or "summarize" (done)
- `confidence`: Confidence score
- `reasoning`: Explanation of analysis

**Key Features:**
- Uses LLM (Gemini) for intelligent state analysis
- Tracks both global and local goals
- Provides structured reasoning

### 3. Decision Module (`decision/decision.py`)

Plans the next steps and generates executable code variants.

**Input:**
- Current perception output
- Execution context
- Available tools (from MultiMCP)
- Completed/failed steps

**Output:**
- `plan_graph`: Graph of planned steps
- `next_step_id`: ID of next step to execute
- `code_variants`: Dictionary of code variants for each step

**Key Features:**
- Generates multiple code variants for robustness
- Creates a plan graph for multi-step tasks
- Considers available MCP tools
- Adapts based on execution history

### 4. Action/Execution Module (`action/executor.py`)

Executes code in a sandboxed environment with access to MCP tools.

**Key Features:**
- **Sandboxed Execution**: Safe Python execution environment
- **AST Transformations**: 
  - Converts keyword arguments to positional
  - Auto-awaits async MCP tool calls
  - Handles return value extraction
- **Tool Integration**: Wraps MCP tools as callable functions
- **Error Handling**: Captures and reports execution errors
- **Session State**: Persists variables across steps

**Execution Process:**
```
Code Variant
    │
    ▼
┌─────────────────┐
│ AST Parse       │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Transform  Build
AST        Safe
           Globals
    │         │
    └────┬────┘
         │
         ▼
┌─────────────────┐
│ Compile &       │
│ Execute         │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Success?   Error?
    │         │
    ▼         ▼
Save      Report
Result    Error
```

### 5. MultiMCP Dispatcher (`mcp_servers/multiMCP.py`)

Manages multiple MCP servers and provides a unified interface.

**Architecture:**
```
MultiMCP
    │
    ├─── MCP Client (Browser - SSE)
    │    └─── Tools: navigate, click, type, etc.
    │
    ├─── MCP Client (Documents - stdio)
    │    └─── Tools: search_documents, extract_text, etc.
    │
    └─── MCP Client (Other - stdio/SSE)
         └─── Tools: various
```

**Key Features:**
- **Unified Tool Registry**: Maps all tools from all servers
- **Transport Abstraction**: Supports both stdio and SSE transports
- **Function Wrapper**: Converts tool calls to function calls
- **Tool Discovery**: Automatically discovers tools from all servers

### 6. Context Manager (`agent/contextManager.py`)

Maintains execution state and step graph.

**Data Structures:**
- **Graph**: NetworkX DiGraph tracking step dependencies
- **Globals**: Dictionary of variables accessible across steps
- **Failed Nodes**: List of failed step IDs
- **Session Memory**: List of execution snapshots

**Key Operations:**
- `add_step()`: Add new step to graph
- `mark_step_completed()`: Mark step as done
- `mark_step_failed()`: Record step failure
- `attach_perception()`: Attach perception results to step
- `get_context_snapshot()`: Serialize current state

**Graph Structure:**
```
ROOT (initial query)
  │
  ├─── Step 1 (code execution)
  │    │
  │    ├─── Step 1A (retry variant)
  │    └─── Step 1B (retry variant)
  │
  ├─── Step 2 (code execution)
  │
  └─── Step 3 (code execution)
```

### 7. Memory System (`memory/`)

Searches past sessions for relevant context.

**Components:**
- **Memory Indexer** (`memory_indexer.py`): Builds searchable index
- **Memory Search** (`memory_search.py`): Performs semantic search

**Search Strategy:**
- **Fuzzy Matching**: Uses RapidFuzz for text similarity
- **NER Boost**: Prioritizes matches with overlapping named entities
- **Hybrid Scoring**: Combines text similarity and entity overlap

**Index Structure:**
```
session_logs/
  └─── YYYY/
       └─── MM/
            └─── session_*.json

session_summaries_index/
  └─── memory_summaries_YYYY-MM-DD.json
```

### 8. Summarizer (`summarization/summarizer.py`)

Generates final summaries when goals are achieved.

**Input:**
- Original query
- Execution context
- Final perception output
- Plan graph

**Output:**
- Natural language summary of results
- Formatted response to user

**Key Features:**
- Uses LLM for intelligent summarization
- Considers full execution context
- Formats output appropriately

### 9. Browser MCP Server (`browserMCP/`)

Specialized MCP server for browser automation.

**Architecture:**
```
Browser MCP Server (SSE)
    │
    ├─── Browser Context
    │    └─── Playwright instance
    │
    ├─── DOM Service
    │    └─── DOM tree building
    │
    ├─── Controller Service
    │    └─── Action execution
    │
    └─── Tools
         ├─── navigate
         ├─── click
         ├─── type
         ├─── get_page_state
         └─── ...
```

**Transport:**
- Uses Server-Sent Events (SSE) for real-time communication
- Runs on `http://localhost:8100/sse`

## Data Flow

### Complete Execution Flow

```
1. User Query
   │
   ▼
2. Memory Search
   │  └─── Find relevant past sessions
   │
   ▼
3. Initial Perception
   │  └─── Analyze query and context
   │
   ▼
4. Decision (if route == "decision")
   │  └─── Plan steps and generate code
   │
   ▼
5. Action Execution
   │  ├─── Execute code variant
   │  ├─── Call MCP tools
   │  └─── Save results to context
   │
   ▼
6. Post-Execution Perception
   │  └─── Analyze results
   │
   ▼
7. Loop (if goal not met)
   │  └─── Back to Decision
   │
   ▼
8. Summarization (if goal met)
   │  └─── Generate final summary
   │
   ▼
9. Save to Memory
   │  └─── Index for future searches
   │
   ▼
10. Return to User
```

## MCP Server Integration

### Available MCP Servers

1. **Browser MCP** (SSE)
   - Location: `browserMCP/browser_mcp_sse.py`
   - Transport: Server-Sent Events
   - Tools: Browser automation (navigate, click, type, etc.)

2. **Documents MCP** (stdio)
   - Location: `mcp_servers/mcp_server_2.py`
   - Transport: Standard I/O
   - Tools: Document search and extraction

3. **Other MCP Servers** (configurable)
   - Defined in `config/mcp_server_config.yaml`
   - Can use stdio or SSE transport

### Tool Execution Flow

```
Decision Module
    │
    │ Generates: tool_name(arg1, arg2, ...)
    │
    ▼
Action Executor
    │
    │ Wraps as: async function
    │
    ▼
MultiMCP
    │
    │ Routes to appropriate MCP client
    │
    ▼
MCP Server
    │
    │ Executes tool
    │
    ▼
Result returned to executor
```

## State Management

### Session State

Each execution session maintains:
- **Session ID**: Unique identifier
- **Query**: Original user query
- **Context Graph**: Execution step graph
- **Globals**: Variables accessible across steps
- **Perception Snapshots**: History of perception outputs
- **Decision Snapshots**: History of decision outputs
- **Execution Snapshots**: History of code executions

### Persistence

- **Session Logs**: `memory/session_logs/YYYY/MM/session_*.json`
- **Sandbox State**: `action/sandbox_state/{session_id}.json`
- **Memory Index**: `memory/session_summaries_index/`

## Error Handling & Retries

### Retry Strategy

1. **Step-Level Retries**:
   - Multiple code variants per step
   - Automatic fallback to next variant on failure
   - Max retries per step: 5

2. **Root-Level Recovery**:
   - If ROOT step fails multiple times, halt execution
   - Max root failures: 2

3. **Replanning**:
   - If step fails too many times, force replan from ROOT
   - Decision module generates new plan

### Error Types

- **Execution Errors**: Code execution failures
- **Tool Errors**: MCP tool call failures
- **LLM Errors**: Model API failures (503, etc.)
- **Parsing Errors**: JSON parsing failures

## Configuration

### Key Configuration Files

1. **MCP Server Config** (`config/mcp_server_config.yaml`)
   - Defines available MCP servers
   - Specifies transport types
   - Maps server IDs to scripts/URLs

2. **Model Config** (`config/models.json`)
   - LLM model configurations
   - API settings

3. **Profiles** (`config/profiles.yaml`)
   - Browser profiles
   - User preferences

## Dependencies

### Core Dependencies
- `mcp`: Model Context Protocol SDK
- `networkx`: Graph management
- `playwright`: Browser automation
- `google-genai`: Gemini API client
- `rapidfuzz`: Fuzzy string matching
- `spacy`: NLP for named entity recognition

### Execution Environment
- Python 3.10+
- Async/await support
- Sandboxed code execution

## Security Considerations

### Sandbox Safety
- Limited builtin functions
- Restricted module imports
- AST transformations for safety
- Timeout protection
- Function call limits

### Tool Access
- Tools only accessible through MCP
- No direct file system access (except through tools)
- No network access (except through tools)

## Performance Characteristics

### Execution Limits
- Max steps per session: 12
- Max retries per step: 5
- Max functions per code block: 20
- Timeout per function: 50 seconds

### Optimization Strategies
- Parallel tool execution (when possible)
- Session state caching
- Memory-based context retrieval
- Incremental graph building

## Extension Points

### Adding New MCP Servers
1. Create MCP server implementation
2. Add to `config/mcp_server_config.yaml`
3. Restart system

### Custom Tools
1. Implement tool in MCP server
2. Register with `@server.list_tools()`
3. Tool automatically available to Decision module

### Custom Strategies
- Modify `strategy` parameter in AgentLoop
- Implement custom decision logic
- Add custom perception analysis

## Troubleshooting

### Common Issues

1. **MCP Server Connection Failures**
   - Check server is running
   - Verify transport type (stdio vs SSE)
   - Check configuration paths

2. **LLM API Errors**
   - Verify API keys
   - Check rate limits
   - Handle 503 errors gracefully

3. **Code Execution Failures**
   - Check tool availability
   - Verify argument types
   - Review sandbox restrictions

4. **Memory Search Issues**
   - Rebuild index: `memory_indexer.py`
   - Check spacy model: `en_core_web_sm`
   - Verify session log format

## Future Enhancements

- [ ] Parallel step execution
- [ ] Advanced retry strategies
- [ ] Better error recovery
- [ ] Enhanced memory indexing
- [ ] Multi-agent coordination
- [ ] Real-time monitoring dashboard

