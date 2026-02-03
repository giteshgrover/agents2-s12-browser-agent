import uuid
from datetime import datetime

from perception.perception import Perception, build_perception_input
from decision.decision import Decision, build_decision_input
from summarization.summarizer import Summarizer
from browser.browser import Browser, build_browser_input
from agent.contextManager import ContextManager
from agent.agentSession import AgentSession
from memory.memory_search import MemorySearch
from action.execute_step import execute_step_with_mode
from utils.utils import log_step, log_error, save_final_plan, log_json_block
import pdb

class Route:
    SUMMARIZE = "summarize"
    DECISION = "decision"
    BROWSE = "browse"

class StepType:
    ROOT = "ROOT"
    CODE = "CODE"


class AgentLoop:
    def __init__(self, perception_prompt, decision_prompt, summarizer_prompt, browser_prompt, multi_mcp, strategy="exploratory"):
        self.perception = Perception(perception_prompt)
        self.decision = Decision(decision_prompt, multi_mcp)
        self.summarizer = Summarizer(summarizer_prompt)
        self.browser = Browser(browser_prompt, multi_mcp)
        self.multi_mcp = multi_mcp
        self.strategy = strategy
        self.status: str = "in_progress"

    async def run(self, query: str):
        self._initialize_session(query) # new session per query
        await self._run_initial_perception()

        if self._should_early_exit():
            return await self._summarize()

        route = self.p_out.get("route")
        if route == Route.DECISION:
            await self._run_decision_loop()
        elif route == Route.BROWSE:
            await self._run_browse_loop()
            # After browse, check perception again to determine next step
            p_input = build_perception_input(self.query, self.memory, self.ctx, snapshot_type="step_result")
            self.p_out = await self.perception.run(p_input, session=self.session)
            self.ctx.attach_perception(StepType.ROOT, self.p_out)
            log_json_block('📌 Perception output after browse', self.p_out)
            
            if self.p_out.get("original_goal_achieved") or self.p_out.get("route") == Route.SUMMARIZE:
                self.status = "success"
                self.final_output = await self._summarize()
            elif self.p_out.get("route") == Route.DECISION:
                await self._run_decision_loop()
            elif self.p_out.get("route") == Route.BROWSE:
                # Could continue browsing if needed
                await self._run_browse_loop()
                # Check perception again
                p_input = build_perception_input(self.query, self.memory, self.ctx, snapshot_type="step_result")
                self.p_out = await self.perception.run(p_input, session=self.session)
                if self.p_out.get("original_goal_achieved") or self.p_out.get("route") == Route.SUMMARIZE:
                    self.status = "success"
                    self.final_output = await self._summarize()
            else:
                log_error("🚩 Invalid route from perception after browse. Exiting.")
                return "Summary generation failed."
        else:
            log_error("🚩 Invalid perception route. Exiting.")
            return "Summary generation failed."

        if self.status == "success":
            return self.final_output

        return await self._handle_failure()

    def _initialize_session(self, query):
        self.session_id = str(uuid.uuid4())  # This session is different than MCP session.
        self.ctx = ContextManager(self.session_id, query)
        self.session = AgentSession(self.session_id, query) # new session per query
        self.query = query
        self.memory = MemorySearch().search_memory(query) # TODO GG: need to understand
        self.ctx.globals = {"memory": self.memory}

    async def _run_initial_perception(self):
        p_input = build_perception_input(self.query, self.memory, self.ctx)
        # pdb.set_trace()
        self.p_out = await self.perception.run(p_input, session=self.session)

        self.ctx.add_step(step_id=StepType.ROOT, description="initial query", step_type=StepType.ROOT)
        self.ctx.mark_step_completed(StepType.ROOT)
        self.ctx.attach_perception(StepType.ROOT, self.p_out)

        log_json_block('📌 Perception output (ROOT)', self.p_out)
        self.ctx._print_graph(depth=2)

    def _should_early_exit(self) -> bool:
        return (
            self.p_out.get("original_goal_achieved") or
            self.p_out.get("route") == Route.SUMMARIZE
        )

    async def _summarize(self):
        return await self.summarizer.summarize(self.query, self.ctx, self.p_out, self.session)

    async def _run_decision_loop(self):
        """Executes initial decision and begins step execution."""
        d_input = build_decision_input(self.ctx, self.query, self.p_out, self.strategy)
        d_out = await self.decision.run(d_input, session=self.session)

        log_json_block("📌 Decision Output", d_out)

        self.code_variants = d_out["code_variants"]
        self.next_step_id = d_out["next_step_id"]

        for node in d_out["plan_graph"]["nodes"]:
            self.ctx.add_step(
                step_id=node["id"],
                description=node["description"],
                step_type=StepType.CODE,
                from_node=StepType.ROOT      # TODO GG: Why from_node is hardcoded and not decided based on d_out["plan_graph"]["edges"] ?
            )

        await self._execute_steps_loop()

    async def _run_browse_loop(self):
        """Executes browser agent to generate and execute browser automation plan.
        The browser agent handles initial and interactive modes internally.
        """
        b_input = build_browser_input(self.ctx, self.query, self.p_out)
        b_out = await self.browser.run(b_input, session=self.session)

        log_json_block("📌 Browser Agent Output", b_out)

        # Create a step for browser execution
        latest_node = self.ctx.get_latest_node() or StepType.ROOT
        browser_step_id = f"browse_{latest_node}"
        self.ctx.add_step(
            step_id=browser_step_id,
            description="Browser automation execution",
            step_type=StepType.CODE,
            from_node=latest_node
        )

        # Store browser result in context
        browser_result_key = f"browser_result_{browser_step_id}"
        self.ctx.globals[browser_result_key] = b_out
        
        # TODO Store page elements and snapshot separately for easier access in interactive mode ???
        if b_out.get("page_elements"):
            page_elements_key = f"page_elements_{browser_step_id}"
            self.ctx.globals[page_elements_key] = b_out.get("page_elements")
        
        if b_out.get("page_snapshot"):
            page_snapshot_key = f"page_snapshot_{browser_step_id}"
            self.ctx.globals[page_snapshot_key] = b_out.get("page_snapshot")

        if b_out.get("status") == "success":
            self.ctx.mark_step_completed(browser_step_id)
            self.ctx.update_step_result(browser_step_id, b_out.get("result"))
        else:
            self.ctx.mark_step_failed(browser_step_id, b_out.get("error", "Browser execution failed"))

    async def _execute_steps_loop(self):
        tracker = StepExecutionTracker(max_steps=12, max_retries=5)
        AUTO_EXECUTION_MODE = "fallback"

        while tracker.should_continue():
            tracker.increment()
            log_step(f"🔁 Loop {tracker.tries} — Executing step {self.next_step_id}")

            if self.ctx.is_step_completed(self.next_step_id):
                log_step(f"✅ Step {self.next_step_id} already completed. Skipping.")
                self.next_step_id = self._pick_next_step(self.ctx)
                continue

            retry_step_id = tracker.retry_step_id(self.next_step_id)
            pdb.set_trace()
            success = await execute_step_with_mode(
                retry_step_id,
                self.code_variants,
                self.ctx,
                AUTO_EXECUTION_MODE,
                self.session,
                self.multi_mcp
            ) # TODO GG: need to understand

            if not success:
                self.ctx.mark_step_failed(self.next_step_id, "All fallback variants failed")
                tracker.record_failure(self.next_step_id)

                if tracker.has_exceeded_retries(self.next_step_id):
                    if self.next_step_id == StepType.ROOT:
                        if tracker.register_root_failure():
                            log_error("🚨 ROOT failed too many times. Halting execution.")
                            return
                    else:
                        log_error(f"⚠️ Step {self.next_step_id} failed too many times. Forcing replan.")
                        self.next_step_id = StepType.ROOT
                continue

            self.ctx.mark_step_completed(self.next_step_id)

            # 🔍 Perception after execution
            p_input = build_perception_input(self.query, self.memory, self.ctx, snapshot_type="step_result")
            self.p_out = await self.perception.run(p_input, session=self.session)

            self.ctx.attach_perception(self.next_step_id, self.p_out)
            log_json_block(f"📌 Perception output ({self.next_step_id})", self.p_out)
            self.ctx._print_graph(depth=3)

            if self.p_out.get("original_goal_achieved") or self.p_out.get("route") == Route.SUMMARIZE:
                self.status = "success"
                self.final_output = await self._summarize()
                return

            route = self.p_out.get("route")
            if route == Route.BROWSE:
                await self._run_browse_loop()
                # After browse, check perception again
                p_input = build_perception_input(self.query, self.memory, self.ctx, snapshot_type="step_result")
                self.p_out = await self.perception.run(p_input, session=self.session)
                self.ctx.attach_perception(self.next_step_id, self.p_out)
                log_json_block(f"📌 Perception output after browse ({self.next_step_id})", self.p_out)
                
                if self.p_out.get("original_goal_achieved") or self.p_out.get("route") == Route.SUMMARIZE:
                    self.status = "success"
                    self.final_output = await self._summarize()
                    return
                
                if self.p_out.get("route") != Route.DECISION:
                    log_error("🚩 Invalid route from perception after browse. Exiting.")
                    return
                # Continue to decision if route is DECISION
            elif route != Route.DECISION:
                log_error("🚩 Invalid route from perception. Exiting.")
                return

            # 🔁 Decision again
            d_input = build_decision_input(self.ctx, self.query, self.p_out, self.strategy)
            d_out = await self.decision.run(d_input, session=self.session)

            log_json_block(f"📌 Decision Output ({tracker.tries})", d_out)

            self.next_step_id = d_out["next_step_id"]
            self.code_variants = d_out["code_variants"]
            plan_graph = d_out["plan_graph"]
            self.update_plan_graph(self.ctx, plan_graph, self.next_step_id)


    async def _handle_failure(self):
        log_error(f"❌ Max steps reached. Halting at {self.next_step_id}")
        self.ctx._print_graph(depth=3)

        self.session.status = "failed"
        self.session.completed_at = datetime.utcnow().isoformat()

        save_final_plan(self.session_id, {
            "context": self.ctx.get_context_snapshot(),
            "session": self.session.to_json(),
            "status": "failed",
            "final_step_id": self.ctx.get_latest_node(),
            "reason": "Agent halted after max iterations or step failures.",
            "timestamp": datetime.utcnow().isoformat(),
            "original_query": self.ctx.original_query
        })

        return "⚠️ Agent halted after max iterations."

    def update_plan_graph(self, ctx, plan_graph, from_step_id):
        for node in plan_graph["nodes"]:
            step_id = node["id"]
            if step_id in ctx.graph.nodes:
                existing = ctx.graph.nodes[step_id]["data"]
                if existing.status != "pending":
                    continue
            ctx.add_step(step_id, description=node["description"], step_type=StepType.CODE, from_node=from_step_id)

    def _pick_next_step(self, ctx) -> str:
        for node_id in ctx.graph.nodes:
            node = ctx.graph.nodes[node_id]["data"]
            if node.status == "pending":
                return node.index
        return StepType.ROOT

    def _get_retry_step_id(self, step_id, failed_step_attempts):
        attempts = failed_step_attempts.get(step_id, 0)
        return f"{step_id}F{attempts}" if attempts > 0 else step_id


class StepExecutionTracker:
    def __init__(self, max_steps=12, max_retries=3):
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.attempts = {}
        self.tries = 0
        self.root_failures = 0

    def increment(self):
        self.tries += 1

    def record_failure(self, step_id):
        self.attempts[step_id] = self.attempts.get(step_id, 0) + 1

    def retry_step_id(self, step_id):
        attempts = self.attempts.get(step_id, 0)
        return f"{step_id}F{attempts}" if attempts > 0 else step_id

    def should_continue(self):
        return self.tries < self.max_steps

    def has_exceeded_retries(self, step_id):
        return self.attempts.get(step_id, 0) >= self.max_retries

    def register_root_failure(self):
        self.root_failures += 1
        return self.root_failures >= 2
