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
        self.max_iterations = 5  # Maximum number of browser agent calls

    async def run(self, browser_input: dict, session: Optional[AgentSession] = None) -> dict:
        """
        Generate and execute browser automation plans iteratively.
        Uses next_action field to determine if more calls are needed.
        Returns a dict with 'status' ('success' or 'failure') and 'result' or 'error'.
        """
        # Get browser tools once (used for all iterations)
        browser_tools = self._get_browser_tools()
        if not browser_tools:
            return {
                "status": "failure",
                "error": "No browser tools available. Please ensure 'webbrowsing' MCP server is configured and initialized.",
                "plan": [],
                "execution_details": []
            }
        
        tool_descriptions = self._format_tool_descriptions(browser_tools)
        
        # Accumulate all plans and execution details across iterations
        all_plans = []
        all_execution_details = []
        all_iteration_results = []
        page_elements = None
        
        iteration = 0
        next_action = "CALL_AGAIN"  # Start by calling the agent
        
        while next_action == "CALL_AGAIN" and iteration < self.max_iterations:
            iteration += 1
            is_initial_mode = (iteration == 1)  # First iteration is initial mode
            log_step(f"[BROWSER AGENT: Iteration {iteration}/{self.max_iterations} ({'INITIAL' if is_initial_mode else 'INTERACTIVE'} mode)...]", symbol="→")
            
            # Call LLM to get plan
            llm_result = await self._call_llm(
                browser_input=browser_input,
                tool_descriptions=tool_descriptions,
                session=session,
                iteration=iteration,
                is_initial_mode=is_initial_mode
            )
            
            if llm_result.get("status") == "failure":
                log_error(f"❌ Browser agent LLM call failed at iteration {iteration}")
                return {
                    "status": "failure",
                    "error": llm_result.get("error", "LLM call failed"),
                    "plan": all_plans,
                    "execution_details": all_execution_details,
                    "iterations": iteration
                }
            
            plan = llm_result.get("plan", [])
            next_action = llm_result.get("next_action", "DONE")
            pdb.set_trace()
            
            if not plan:
                log_error(f"⚠️ Empty plan returned at iteration {iteration}")
                next_action = "DONE"  # Stop if no plan
                continue
            
            all_plans.extend(plan)
            
            # Execute the plan
            execution_result = await self._execute_plan(plan, session)
            all_execution_details.extend(execution_result.get("execution_details", []))
            
            # Store iteration result
            iteration_result = {
                "iteration": iteration,
                "plan": plan,
                "execution_details": execution_result.get("execution_details", []),
                "status": execution_result.get("status", "failure"),
                "next_action": next_action
            }
            all_iteration_results.append(iteration_result)
            
            # Update page_elements if we got new ones
            if execution_result.get("page_elements"):
                page_elements = execution_result.get("page_elements")
            
            # If execution failed, stop
            if execution_result.get("status") != "success":
                log_error(f"❌ Plan execution failed at iteration {iteration}")
                return {
                    "status": "failure",
                    "error": execution_result.get("error", "Plan execution failed"),
                    "plan": all_plans,
                    "execution_details": all_execution_details,
                    "iterations": iteration,
                    "iteration_results": all_iteration_results
                }
            
            # If next_action is CALL_AGAIN, update browser_input with execution results
            if next_action == "CALL_AGAIN":
                # Add execution results to globals_schema for next iteration
                result_key = f"browser_result_iteration_{iteration}"
                browser_input["globals_schema"][result_key] = {
                    "type": type(execution_result).__name__,
                    "preview": str(execution_result)[:500] + ("…" if len(str(execution_result)) > 500 else "")
                }
                
                # Add page elements if we have them
                if page_elements:
                    elements_key = f"page_elements_iteration_{iteration}"
                    try:
                        elements_preview = json.dumps(page_elements, indent=2)[:2000] + ("…" if len(json.dumps(page_elements)) > 2000 else "")
                    except:
                        elements_preview = str(page_elements)[:2000] + ("…" if len(str(page_elements)) > 2000 else "")
                    browser_input["globals_schema"][elements_key] = {
                        "type": type(page_elements).__name__,
                        "preview": elements_preview
                    }
                
                log_step(f"[BROWSER AGENT: Iteration {iteration} completed. Continuing with next iteration...]", symbol="→")
            else:
                log_step(f"[BROWSER AGENT: Iteration {iteration} completed. Task DONE.]", symbol="✅")
        
        # Check if we hit max iterations
        if iteration >= self.max_iterations and next_action == "CALL_AGAIN":
            log_error(f"⚠️ Reached maximum iterations ({self.max_iterations}). Stopping.")
            return {
                "status": "failure",
                "error": f"Reached maximum iterations ({self.max_iterations})",
                "plan": all_plans,
                "execution_details": all_execution_details,
                "iterations": iteration,
                "iteration_results": all_iteration_results
            }
        
        # Determine final status
        all_success = all(result.get("status") == "success" for result in all_iteration_results)
        final_status = "success" if all_success else "failure"
        
        return {
            "status": final_status,
            "result": all_iteration_results[-1].get("execution_details", [{}])[-1].get("result") if all_iteration_results else None,
            "error": None if all_success else "One or more iterations failed",
            "plan": all_plans,
            "execution_details": all_execution_details,
            "iterations": iteration,
            "iteration_results": all_iteration_results,
            "page_elements": page_elements
        }

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

    async def _call_llm(self, browser_input: dict, tool_descriptions: str, session: Optional[AgentSession] = None, iteration: int = 1, is_initial_mode: bool = True) -> dict:
        """
        Call LLM to get browser automation plan.
        
        Args:
            browser_input: Input dictionary for browser agent
            tool_descriptions: Formatted tool descriptions
            session: Optional agent session
            iteration: Current iteration number
            is_initial_mode: True if this is the first iteration (initial mode), False otherwise
        """
        prompt_template = Path(self.browser_prompt_path).read_text(encoding="utf-8")
        
        # Add mode information to browser_input
        mode_input = browser_input.copy()
        mode_input["is_initial_mode"] = is_initial_mode
        mode_input["iteration"] = iteration
        
        tool_descriptions_formatted = "\n\n### Available Browser Tools\n\n---\n\n" + tool_descriptions
        full_prompt = f"{prompt_template.strip()}\n{tool_descriptions_formatted}\n\n```json\n{json.dumps(mode_input, indent=2)}\n```"

        try:
            log_step(f"[SENDING PROMPT TO BROWSER AGENT (Iteration {iteration})...]", symbol="→")
            time.sleep(2)
            response = await self.model.generate_text(
                prompt=full_prompt
            )
            log_step(f"[RECEIVED OUTPUT FROM BROWSER AGENT (Iteration {iteration})...]", symbol="←")

            output = parse_llm_json(response, required_keys=["plan", "status", "result", "next_action"])
            
            # Validate next_action
            next_action = output.get("next_action", "DONE")
            if next_action not in ["DONE", "CALL_AGAIN"]:
                log_error(f"⚠️ Invalid next_action: {next_action}. Defaulting to DONE.")
                next_action = "DONE"
            
            return {
                "status": "success",
                "plan": output.get("plan", []),
                "status_prediction": output.get("status", "success"),
                "result": output.get("result", ""),
                "next_action": next_action
            }

        except ServerError as e:
            log_error(f"🚫 BROWSER AGENT LLM ServerError (Iteration {iteration}): {e}")
            return {
                "status": "failure",
                "error": f"Browser agent ServerError (Iteration {iteration}): LLM unavailable - {str(e)}",
                "plan": [],
                "next_action": "DONE"
            }

        except Exception as e:
            log_error(f"🛑 BROWSER AGENT ERROR (Iteration {iteration}): {str(e)}")
            return {
                "status": "failure",
                "error": f"Browser agent failed (Iteration {iteration}): {str(e)}",
                "plan": [],
                "next_action": "DONE"
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

                # Store specific results for easier access in next iteration
                if tool_name == "get_interactive_elements":
                    page_elements = last_result

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

        # Determine overall status
        all_success = all(detail.get("status") == "success" for detail in execution_details)
        
        return {
            "status": "success" if all_success else "failure",
            "result": last_result,
            "error": None if all_success else "One or more steps failed",
            "execution_details": execution_details,
            "page_elements": page_elements
        }


def build_browser_input(ctx, query, p_out):
    """
    Build input for browser agent similar to decision input.
    The browser agent handles iterative calls internally using next_action.
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
