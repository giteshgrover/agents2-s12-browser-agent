import os
import json
from pathlib import Path
import pdb
from utils.utils import log_step, log_error, log_json_block
from google.genai.errors import ServerError
import time
from typing import Any, Literal, Optional
from agent.agentSession import AgentSession
import uuid
from datetime import datetime
from agent.model_manager import ModelManager
from utils.json_parser import parse_llm_json
from mcp_servers.multiMCP import MultiMCP


class Browser:
    def __init__(self, browser_prompt_path: str, multi_mcp: MultiMCP, api_key: str | None = None, model: str = "gemini-2.0-flash"):
        self.browser_prompt_path = browser_prompt_path
        self.multi_mcp = multi_mcp
        self.model = ModelManager()

    async def run(self, browser_input: dict, session: Optional[AgentSession] = None) -> dict:
        """
        Generate and execute browser automation plans.
        Handles both initial (gather page info) and interactive (execute actions) modes internally.
        Returns a dict with 'status' ('success' or 'failure') and 'result' or 'error'.
        """
        # Check if we have previous browser data to determine if we need initial mode
        globals_schema = browser_input.get("globals_schema", {})
        has_previous_browser_data = any(
            key.startswith("browser_result_") or 
            key.startswith("page_elements_") or 
            key.startswith("page_snapshot_")
            for key in globals_schema.keys()
        )
        
        # Get browser tools once (used for both modes)
        browser_tools = self._get_browser_tools()
        if not browser_tools:
            return {
                "status": "failure",
                "error": "No browser tools available. Please ensure 'webbrowsing' MCP server is configured and initialized.",
                "plan": [],
                "execution_details": []
            }
        
        tool_descriptions = self._format_tool_descriptions(browser_tools)
        
        # Step 1: Run initial mode if we don't have previous browser data
        initial_result = None
        if not has_previous_browser_data:
            log_step("[BROWSER AGENT: Running INITIAL mode to gather page information...]", symbol="→")
            initial_result = await self._run_mode(
                browser_input=browser_input,
                mode="initial",
                tool_descriptions=tool_descriptions,
                session=session
            )
            
            if initial_result.get("status") != "success":
                log_error("❌ Initial mode failed. Cannot proceed to interactive mode.")
                return initial_result
            
            # Update browser_input with initial mode results for interactive mode
            # Format them the same way as other globals_schema entries
            page_elements = initial_result.get("page_elements")
            page_snapshot = None # initial_result.get("page_snapshot")
            
            if page_elements:
                # For page_elements, try to format as JSON for better readability
                try:
                    elements_preview = json.dumps(page_elements, indent=2)[:2000] + ("…" if len(json.dumps(page_elements)) > 2000 else "")
                except:
                    elements_preview = str(page_elements)[:2000] + ("…" if len(str(page_elements)) > 2000 else "")
                browser_input["globals_schema"][f"page_elements_initial"] = {
                    "type": type(page_elements).__name__,
                    "preview": elements_preview
                }
            if page_snapshot:
                browser_input["globals_schema"][f"page_snapshot_initial"] = {
                    "type": type(page_snapshot).__name__,
                    "preview": str(page_snapshot)[:1000] + ("…" if len(str(page_snapshot)) > 1000 else "")
                }
            browser_input["globals_schema"][f"browser_result_initial"] = {
                "type": type(initial_result).__name__,
                "preview": str(initial_result)[:500] + ("…" if len(str(initial_result)) > 500 else "")
            }
            
            log_step("[BROWSER AGENT: Initial mode completed. Proceeding to INTERACTIVE mode...]", symbol="→")
        
        pdb.set_trace()
        # Step 2: Run interactive mode to execute actions
        interactive_result = await self._run_mode(
            browser_input=browser_input,
            mode="interactive",
            tool_descriptions=tool_descriptions,
            session=session
        )
        
        # Combine results
        final_result = {
            "status": interactive_result.get("status", "failure"),
            "result": interactive_result.get("result"),
            "error": interactive_result.get("error"),
            "plan": interactive_result.get("plan", []),
            "execution_details": interactive_result.get("execution_details", []),
            "initial_mode_result": initial_result if initial_result else None,
            "interactive_mode_result": interactive_result
        }
        
        # Include page elements and snapshot from either initial or interactive mode
        final_result["page_elements"] = interactive_result.get("page_elements") or (initial_result.get("page_elements") if initial_result else None)
        final_result["page_snapshot"] = interactive_result.get("page_snapshot") or (initial_result.get("page_snapshot") if initial_result else None)
        
        return final_result

    def _get_browser_tools(self):
        """Get browser MCP tools from webbrowsing server."""
        browser_tools = self.multi_mcp.get_tools_from_servers(["webbrowsing"])
        if not browser_tools:
            log_error("⚠️ No browser tools found from 'webbrowsing' server. Trying all tools...")
            # Fallback: try to get all tools and filter by name patterns
            all_tools = self.multi_mcp.get_all_tools()
            browser_tools = [t for t in all_tools if any(keyword in t.name.lower() for keyword in 
                ['click', 'navigate', 'browser', 'tab', 'element', 'input', 'scroll', 'snapshot', 'extract'])]
        return browser_tools

    def _format_tool_descriptions(self, browser_tools):
        """Format browser tools into description string for prompts."""
        browser_tool_descriptions = []
        for tool in browser_tools:
            schema = tool.inputSchema
            if "input" in schema.get("properties", {}):
                inner_key = next(iter(schema.get("$defs", {})), None)
                props = schema["$defs"][inner_key]["properties"] if inner_key else {}
            else:
                props = schema.get("properties", {})
            
            arg_types = []
            for k, v in props.items():
                t = v.get("type", "any")
                arg_types.append(f"{k}: {t}")
            
            signature_str = ", ".join(arg_types) if arg_types else "no args"
            browser_tool_descriptions.append(f"- `{tool.name}({signature_str})` - {tool.description}")
        
        return "\n".join(browser_tool_descriptions)

    async def _run_mode(self, browser_input: dict, mode: str, tool_descriptions: str, session: Optional[AgentSession] = None) -> dict:
        """
        Run browser agent in a specific mode (initial or interactive).
        """
        prompt_template = Path(self.browser_prompt_path).read_text(encoding="utf-8")
        
        # Create mode-specific input
        mode_input = browser_input.copy()
        mode_input["browser_mode"] = mode
        
        tool_descriptions_formatted = "\n\n### Available Browser Tools\n\n---\n\n" + tool_descriptions
        full_prompt = f"{prompt_template.strip()}\n{tool_descriptions_formatted}\n\n```json\n{json.dumps(mode_input, indent=2)}\n```"

        try:
            log_step(f"[SENDING PROMPT TO BROWSER AGENT ({mode.upper()} mode)...]", symbol="→")
            time.sleep(2)
            response = await self.model.generate_text(
                prompt=full_prompt
            )
            log_step(f"[RECEIVED OUTPUT FROM BROWSER AGENT ({mode.upper()} mode)...]", symbol="←")

            output = parse_llm_json(response, required_keys=["plan", "status", "result"])

            # Execute the plan
            execution_result = await self._execute_plan(output.get("plan", []), session)

            return {
                "status": execution_result.get("status", "failure"),
                "result": execution_result.get("result"),
                "error": execution_result.get("error"),
                "plan": output.get("plan", []),
                "execution_details": execution_result.get("execution_details", []),
                "mode": mode,
                "page_elements": execution_result.get("page_elements"),
                "page_snapshot": execution_result.get("page_snapshot")
            }

        except ServerError as e:
            log_error(f"🚫 BROWSER AGENT LLM ServerError ({mode} mode): {e}")
            return {
                "status": "failure",
                "error": f"Browser agent ServerError ({mode} mode): LLM unavailable - {str(e)}",
                "plan": [],
                "execution_details": [],
                "mode": mode
            }

        except Exception as e:
            log_error(f"🛑 BROWSER AGENT ERROR ({mode} mode): {str(e)}")
            return {
                "status": "failure",
                "error": f"Browser agent failed ({mode} mode): {str(e)}",
                "plan": [],
                "execution_details": [],
                "mode": mode
            }

    async def _execute_plan(self, plan: list, session: Optional[AgentSession] = None) -> dict:
        """
        Execute a plan of browser tool calls in sequence.
        Plan format: [{"tool": "tool_name", "arguments": {...}}, ...]
        """
        if not plan:
            return {
                "status": "failure",
                "error": "Empty plan provided",
                "execution_details": []
            }

        execution_details = []
        last_result = None
        page_elements = None
        page_snapshot = None

        for i, step in enumerate(plan):
            tool_name = step.get("tool")
            arguments = step.get("arguments", {})
            
            if not tool_name:
                execution_details.append({
                    "step": i + 1,
                    "tool": None,
                    "status": "error",
                    "error": "Missing tool name"
                })
                continue

            try:
                log_step(f"🔧 Executing browser tool {i+1}/{len(plan)}: {tool_name}", symbol="→")
                result = await self.multi_mcp.call_tool(tool_name, arguments)
                
                # Extract result content
                if hasattr(result, 'content') and result.content:
                    content_text = result.content[0].text if result.content else ""
                    try:
                        parsed = json.loads(content_text)
                        last_result = parsed
                    except:
                        last_result = content_text
                else:
                    last_result = result

                # Store specific results for easier access in interactive mode
                if tool_name == "get_interactive_elements":
                    page_elements = last_result
                elif tool_name in ["get_page_snapshot", "extract_content"]:
                    page_snapshot = last_result

                execution_details.append({
                    "step": i + 1,
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": "success",
                    "result": str(last_result)[:500]  # Truncate for logging
                })
                log_step(f"✅ Tool {tool_name} succeeded", symbol="✅")

            except Exception as e:
                error_msg = str(e)
                execution_details.append({
                    "step": i + 1,
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": "error",
                    "error": error_msg
                })
                log_error(f"❌ Tool {tool_name} failed: {error_msg}")
                
                # Decide whether to continue or stop on error
                # For now, we'll continue but mark as failure if any step fails
                # You can modify this logic based on requirements

        # Determine overall status
        all_success = all(detail.get("status") == "success" for detail in execution_details)
        
        return {
            "status": "success" if all_success else "failure",
            "result": last_result,
            "error": None if all_success else "One or more steps failed",
            "execution_details": execution_details,
            "page_elements": page_elements,  # Store for interactive mode
            "page_snapshot": page_snapshot     # Store for interactive mode
        }


def build_browser_input(ctx, query, p_out):
    """
    Build input for browser agent similar to decision input.
    Mode selection (initial vs interactive) is handled internally by the browser agent.
    """
    return {
        "current_time": datetime.utcnow().isoformat(),
        "original_query": query,
        "perception": p_out,
        "completed_steps": [ctx.graph.nodes[n]["data"].__dict__ for n in ctx.graph.nodes if ctx.graph.nodes[n]["data"].status == "completed"],
        "failed_steps": [ctx.graph.nodes[n]["data"].__dict__ for n in ctx.failed_nodes],
        "globals_schema": {
            k: {
                "type": type(v).__name__,
                "preview": str(v)[:500] + ("…" if len(str(v)) > 500 else "")
            } for k, v in ctx.globals.items()
        }
    }

