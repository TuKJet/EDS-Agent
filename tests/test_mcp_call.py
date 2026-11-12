import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from eds import StudyStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mcp_call


class McpStudyRecordingTests(unittest.TestCase):
    def setUp(self):
        test_tmp = Path(__file__).resolve().parents[1] / "output" / "repository-tests" / "tmp"
        test_tmp.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=test_tmp)
        self.root = Path(self.tmp.name)
        self.store = StudyStore.create(self.root / "study", "MCP recording", mode="cad")
        self.store.add("experiment", {"question": "Does the backend return a usable result?",
            "observations": ["response"], "decision_rule": "record the protocol result"}, ref="exp")
        self.store.add("evidence", {"source": "state-a@1", "observation": {"state": "state-a@1"}}, ref="state-a")
        self.store.add("evidence", {"source": "state-a@2", "observation": {"state": "state-a@2"}}, ref="state-a@1")
        self.store.add("evidence", {"source": "state-b@1", "observation": {"state": "state-b@1"}}, ref="state-b")
        self.data = self.root / "args.json"
        self.data.write_text(json.dumps({"params": {"value": 1}}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def latest(self):
        return StudyStore(self.root / "study").read()["runs"][-1]

    def run_main(self, output, response=None, error=None, binding=None, capability=None, tool="demo_tool",
                 expected_server=None, experiment_ref="exp", input_refs=None, with_study=True):
        def inline_run(coro):
            try:
                return coro.send(None)
            except StopIteration as done:
                return done.value

        def inline_wait_for(coro, timeout):
            return coro

        call = AsyncMock(side_effect=error, return_value=response)
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["mcp_call.py", "--url", "http://127.0.0.1:1/mcp", "--output", str(output),
                "call", tool, "--data", str(self.data)]
        if with_study:
            argv[argv.index("call"):argv.index("call")] = [
                "--study-root", str(self.root / "study"), "--experiment-ref", experiment_ref]
            for input_ref in input_refs or []:
                argv[argv.index("call"):argv.index("call")] = ["--input-ref", input_ref]
        if expected_server:
            argv[argv.index("--output"):argv.index("--output")] = ["--expected-server", expected_server]
        if binding:
            binding_path = self.root / "binding.json"
            binding_path.write_text(json.dumps(binding), encoding="utf-8")
            argv[argv.index("call"):argv.index("call")] = ["--binding", str(binding_path), "--capability", capability]
        with patch.object(mcp_call, "invoke", call), patch.object(sys, "argv", argv), \
                patch.object(mcp_call.asyncio, "run", inline_run), \
                patch.object(mcp_call.asyncio, "wait_for", inline_wait_for), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = mcp_call.main()
        return code, call, stdout.getvalue(), stderr.getvalue()

    def test_main_success_records_completed_and_evidence(self):
        output = self.root / "success.json"
        code, call, stdout, _ = self.run_main(output, response={"result": {"ok": True}})
        self.assertEqual(code, 0)
        self.assertEqual(call.await_count, 1)
        run = self.latest()
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["input_snapshot"]["tool"], "demo_tool")
        self.assertEqual(run["input_snapshot"]["arguments"], {"params": {"value": 1}})
        self.assertEqual(run["input_snapshot"]["server_url"], "http://127.0.0.1:1/mcp")
        self.assertNotIn("output_path", run["input_snapshot"])
        self.assertTrue(output.exists())
        self.assertIn(run["run_id"], stdout)

    def test_completed_same_action_changed_output_is_rejected_without_call(self):
        first = self.root / "completed-first.json"
        code, call, stdout, _ = self.run_main(first, response={"result": {"ok": True}})
        self.assertEqual((code, call.await_count), (0, 1))

        second = self.root / "completed-second.json"
        code, call, _, stderr = self.run_main(second, response={"result": {"ok": "must-not-run"}})
        failure = json.loads(stderr)
        self.assertEqual((code, call.await_count), (2, 0))
        self.assertEqual((failure["existing_status"], failure["tool_sent"],
                          failure["current_call_not_executed"]), ("completed", False, True))
        self.assertEqual(failure["existing_run_id"], self.latest()["run_id"])
        self.assertFalse(second.exists())

    def test_unbound_preflight_failure_can_retry_without_changing_request(self):
        rejected = {"preflight_rejected": True, "preflight_error": "missing_tool", "tool_sent": False}
        code, call, _, _ = self.run_main(self.root / "unsent.json", response=rejected)
        self.assertEqual((code, call.await_count), (2, 1))
        failed = self.latest()
        code, call, _, stderr = self.run_main(self.root / "repaired.json", response={"result": {"ok": True}})
        self.assertEqual((code, call.await_count), (0, 1), stderr)
        runs = self.store.read()["runs"]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0], failed)
        self.assertEqual(runs[-1]["status"], "completed")

    def test_prepared_retry_resumes_its_run_after_local_interruption(self):
        rejected = {"preflight_rejected": True, "preflight_error": "missing_tool", "tool_sent": False}
        self.run_main(self.root / "unsent.json", response=rejected)
        failed = self.latest()
        planned = self.store.add_run(
            experiment_ref=failed["experiment_ref"], input_refs=failed["input_refs"],
            backend=failed["backend"], capability=failed["capability"],
            input_snapshot=failed["input_snapshot"], idempotency_key=failed["idempotency_key"] + ":retry-1")
        code, call, _, stderr = self.run_main(self.root / "resumed.json", response={"result": {"ok": True}})
        self.assertEqual((code, call.await_count), (0, 1), stderr)
        runs = self.store.read()["runs"]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0], failed)
        self.assertEqual(runs[-1]["run_id"], planned["run_id"])
        self.assertEqual(runs[-1]["status"], "completed")

    def test_mcp_attempt_limit_rejects_before_invoke_and_reports_marker(self):
        self.store.add("experiment", {
            "question": "Does the bounded operation run once?", "observations": ["response"],
            "decision_rule": "stop after one attempt", "budget": {"mcp_call_limits": {"demo_tool": 1}},
        }, ref="budget-exp")
        first_code, first_call, _, _ = self.run_main(
            self.root / "budget-first.json", response={"result": {"ok": True}}, experiment_ref="budget-exp")
        self.data.write_text(json.dumps({"params": {"value": 2}}), encoding="utf-8")
        second_code, second_call, _, stderr = self.run_main(
            self.root / "budget-second.json", response={"result": {"ok": True}}, experiment_ref="budget-exp")
        failure = json.loads(stderr)
        self.assertEqual((first_code, first_call.await_count), (0, 1))
        self.assertEqual((second_code, second_call.await_count), (2, 0))
        self.assertEqual((failure["preflight_error"], failure["tool_sent"],
                          failure["current_call_not_executed"]), ("mcp_attempt_limit", False, True))

        self.store.add("experiment", {
            "question": "Is the disabled operation rejected?", "observations": ["preflight"],
            "decision_rule": "never submit", "budget": {"mcp_call_limits": {"demo_tool": 0}},
        }, ref="zero-exp")
        zero_code, zero_call, _, zero_stderr = self.run_main(
            self.root / "budget-zero.json", response={"result": {"ok": True}}, experiment_ref="zero-exp")
        zero_failure = json.loads(zero_stderr)
        self.assertEqual((zero_code, zero_call.await_count, zero_failure["preflight_error"]),
                         (2, 0, "mcp_attempt_limit"))

    def test_new_fixed_state_ref_creates_new_occurrence(self):
        for index, state_ref in enumerate(("state-a@1", "state-b@1", "state-a@2"), start=1):
            code, call, _, stderr = self.run_main(
                self.root / ("state-" + str(index) + ".json"),
                response={"result": {"state": state_ref}}, input_refs=[state_ref])
            self.assertEqual((code, call.await_count, stderr), (0, 1, ""))
        self.assertEqual(len(self.store.read()["runs"]), 3)

    def test_repeat_inspect_same_state_is_not_fresh_but_new_state_is(self):
        first = self.root / "inspect-a-first.json"
        code, call, _, _ = self.run_main(first, response={"result": {"observed": "A"}},
                                          tool="inspect_tool", input_refs=["state-a@1"])
        self.assertEqual((code, call.await_count), (0, 1))

        repeat = self.root / "inspect-a-repeat.json"
        code, call, _, stderr = self.run_main(repeat, response={"result": {"observed": "stale"}},
                                              tool="inspect_tool", input_refs=["state-a@1"])
        failure = json.loads(stderr)
        self.assertEqual((code, call.await_count), (2, 0))
        self.assertEqual((failure["existing_status"], failure["tool_sent"]), ("completed", False))

        fresh = self.root / "inspect-b.json"
        code, call, _, _ = self.run_main(fresh, response={"result": {"observed": "B"}},
                                         tool="inspect_tool", input_refs=["state-b@1"])
        self.assertEqual((code, call.await_count), (0, 1))

    def test_completed_bound_read_only_observation_can_repeat_as_new_run(self):
        binding = {"schema": "eds-backend/v1", "id": "cad-test", "domain": "cad",
                   "codex_server": "cad-alias", "expected_server": "cad-protocol",
                   "capabilities": {"inspect": {"tool": "inspect_tool",
                       "description": "Read current model state", "read_only": True}}}
        first = self.root / "bound-inspect-first.json"
        code, call, _, _ = self.run_main(first, response={"result": {"observed": "A"}},
                                          binding=binding, capability="inspect", tool="inspect_tool",
                                          expected_server="cad-protocol", input_refs=["state-a@1"])
        self.assertEqual((code, call.await_count), (0, 1))
        second = self.root / "bound-inspect-repeat.json"
        code, call, _, stderr = self.run_main(second, response={"result": {"observed": "A2"}},
                                              binding=binding, capability="inspect", tool="inspect_tool",
                                              expected_server="cad-protocol", input_refs=["state-a@1"])
        self.assertEqual((code, call.await_count, stderr), (0, 1, ""))
        runs = self.store.read()["runs"]
        self.assertEqual(len(runs), 2)
        self.assertNotEqual(runs[0]["run_id"], runs[1]["run_id"])
        self.assertNotEqual(runs[0]["idempotency_key"], runs[1]["idempotency_key"])

    def test_failed_preflight_can_retry_same_request_after_repair(self):
        binding = {"schema": "eds-backend/v1", "id": "cad-test", "domain": "cad",
                   "codex_server": "cad-alias", "expected_server": "cad-protocol",
                   "capabilities": {"edit": {"tool": "set_length",
                       "description": "Change model length"}}}
        first = self.root / "preflight-failed.json"
        rejected = {"preflight_rejected": True, "preflight_error": "wrong_server", "tool_sent": False}
        code, call, _, _ = self.run_main(first, response=rejected, binding=binding,
                                          capability="edit", tool="set_length",
                                          expected_server="cad-protocol")
        self.assertEqual((code, call.await_count), (2, 1))
        old = self.latest()
        self.assertEqual(old["status"], "failed")
        second = self.root / "preflight-repaired.json"
        code, call, _, stderr = self.run_main(second, response={"result": {"ok": True}},
                                              binding=binding, capability="edit", tool="set_length",
                                              expected_server="cad-protocol")
        self.assertEqual((code, call.await_count, stderr), (0, 1, ""))
        runs = self.store.read()["runs"]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["run_id"], old["run_id"])
        self.assertEqual(runs[0]["status"], "failed")
        self.assertEqual(runs[1]["status"], "completed")
        third = self.root / "preflight-repaired-repeat.json"
        code, call, _, stderr = self.run_main(third, response={"result": {"ok": "must-not-run"}},
                                              binding=binding, capability="edit", tool="set_length",
                                              expected_server="cad-protocol")
        failure = json.loads(stderr)
        self.assertEqual((code, call.await_count, failure["existing_status"]), (2, 0, "completed"))
        self.assertEqual(len(self.store.read()["runs"]), 2)

    def test_unrecorded_call_is_marked_without_study(self):
        output = self.root / "unrecorded.json"
        code, call, stdout, _ = self.run_main(
            output, response={"tool_sent": True, "result": {"ok": True}}, with_study=False)
        summary = json.loads(stdout)
        self.assertEqual((code, call.await_count), (0, 1))
        self.assertEqual((summary["recording"], summary["tool_sent"]), ("unrecorded", True))

    def test_main_tool_error_records_failed(self):
        output = self.root / "tool-error.json"
        code, call, _, _ = self.run_main(output, response={"result": {"isError": True}})
        self.assertEqual(code, 2)
        self.assertEqual(call.await_count, 1)
        self.assertEqual(self.latest()["status"], "failed")

    def test_main_operation_failure_records_failed_and_exit2(self):
        for status in ("error", "blocked", "fail"):
            with self.subTest(status=status):
                self.data.write_text(json.dumps({"params": {"value": status}}), encoding="utf-8")
                output = self.root / ("operation-" + status + ".json")
                response = {"result": {"isError": False, "content": [{"type": "text",
                    "text": json.dumps({"status": status})}]}}
                code, call, _, _ = self.run_main(output, response=response)
                self.assertEqual(code, 2)
                self.assertEqual(call.await_count, 1)
                self.assertEqual(self.latest()["status"], "failed")

    def async_binding(self, **overrides):
        capability = {"tool": "demo_tool", "description": "submit one job", "async": True,
                      "query_tool": "query_job", "task_id_field": "job.job_id",
                      "status_map": {"queued": "submitted"}}
        capability.update(overrides)
        return {"schema": "eds-backend/v1", "id": "hub", "domain": "cae",
                "codex_server": "hub-alias", "expected_server": "hub-protocol",
                "capabilities": {"solve": capability}}

    def test_markdown_operation_failure_is_not_recorded_as_completed(self):
        for channel in ("content", "structuredContent"):
            with self.subTest(channel=channel):
                self.data.write_text(json.dumps({"params": {"value": channel}}), encoding="utf-8")
                text = "# error\n- **message**: Active document target mismatch"
                payload = {"isError": False}
                if channel == "content":
                    payload[channel] = [{"type": "text", "text": text}]
                else:
                    payload[channel] = {"result": text}
                code, call, stdout, _ = self.run_main(
                    self.root / (channel + "-failure.json"), response={"result": payload})
                self.assertEqual((code, call.await_count), (2, 1))
                self.assertEqual(self.latest()["status"], "failed")
                self.assertTrue(json.loads(stdout)["operation_failed"])
                self.assertEqual(self.latest()["history"][-1]["output"]["result"], payload)

    def test_markdown_error_mentions_are_not_operation_failures(self):
        for text in ("# ok\n- **message**: no error", "# error handling\nDocumentation",
                     "```markdown\n# error\n```", "Result text\n# error"):
            with self.subTest(text=text):
                self.data.write_text(json.dumps({"params": {"value": text}}), encoding="utf-8")
                code, call, _, _ = self.run_main(
                    self.root / (str(len(self.store.read()["runs"])) + "-ok.json"),
                    response={"result": {"isError": False,
                              "content": [{"type": "text", "text": text}]}})
                self.assertEqual((code, call.await_count), (0, 1))
                self.assertEqual(self.latest()["status"], "completed")

    def test_async_queued_response_records_submitted_and_task_id(self):
        output = self.root / "queued.json"
        response = {"server_name": "hub-protocol", "result": {"isError": False,
                    "content": [{"type": "text", "text": '{"success":true,"job":{"job_id":"j-1","status":"queued"}}'}]}}
        code, call, stdout, _ = self.run_main(output, response=response, binding=self.async_binding(), capability="solve",
                                              expected_server="hub-protocol")
        self.assertEqual(code, 0)
        self.assertEqual(call.await_count, 1)
        run = self.latest()
        self.assertEqual((run["status"], run["task_id"]), ("submitted", "j-1"))
        self.assertEqual(run["capability"], "solve")
        self.assertEqual(run["input_snapshot"]["binding_id"], "hub")
        self.assertIn('"requires_query": true', stdout)

    def test_async_missing_or_conflicting_task_id_is_unknown_without_retry(self):
        for name, payload in {
            "missing": '{"success":true,"job":{"status":"queued"}}',
            "conflicting": '{"success":true,"job":{"job_id":"j-1"}}',
        }.items():
            with self.subTest(name=name):
                self.data.write_text(json.dumps({"params": {"value": name}}), encoding="utf-8")
                output = self.root / (name + ".json")
                if name == "conflicting":
                    response = {"result": {"isError": False, "structuredContent": json.loads(payload),
                        "content": [{"type": "text", "text": '{"success":true,"job":{"job_id":"j-2"}}'}]}}
                else:
                    response = {"result": {"isError": False, "content": [{"type": "text", "text": payload}]}}
                code, call, _, _ = self.run_main(output, response=response, binding=self.async_binding(), capability="solve")
                self.assertEqual(code, 2)
                self.assertEqual(call.await_count, 1)
                self.assertEqual(self.latest()["status"], "unknown")

    def test_bound_explicit_failure_stays_failed_and_binding_mismatch_never_invokes(self):
        output = self.root / "explicit-failure.json"
        response = {"result": {"isError": False, "content": [{"type": "text",
                    "text": '{"success":false,"status":"failed","job":{"job_id":"j-1"}}'}]}}
        code, call, _, _ = self.run_main(output, response=response, binding=self.async_binding(), capability="solve")
        self.assertEqual(code, 2)
        self.assertEqual(call.await_count, 1)
        self.assertEqual((self.latest()["status"], self.latest()["task_id"]), ("failed", "j-1"))

        mismatch = self.root / "mismatch.json"
        binding = self.async_binding()
        binding["capabilities"]["solve"]["tool"] = "other_tool"
        code, call, _, stderr = self.run_main(mismatch, response=response, binding=binding, capability="solve")
        self.assertEqual(code, 2)
        self.assertEqual(call.await_count, 0)
        self.assertIn("does not match", stderr)

    def test_binding_cli_validation_server_identity_and_query_tool_preflight(self):
        base = ["mcp_call.py", "--url", "http://127.0.0.1:1/mcp", "--output", str(self.root / "flags.json")]
        for extra in (("--binding", str(self.root / "missing.json")), ("--capability", "solve")):
            with self.subTest(extra=extra), patch.object(sys, "argv", base + list(extra) + [
                    "call", "demo_tool", "--data", str(self.data)]):
                with self.assertRaises(SystemExit) as raised:
                    mcp_call.main()
                self.assertEqual(raised.exception.code, 2)

        binding = self.async_binding()
        binding["capabilities"].pop("solve")
        binding["capabilities"]["inspect"] = {"tool": "inspect_tool", "description": "inspect"}
        code, call, _, stderr = self.run_main(self.root / "missing-cap.json", response={}, binding=binding, capability="solve")
        self.assertEqual((code, call.await_count), (2, 0))
        self.assertIn("capability", stderr)

        binding = self.async_binding()
        binding["expected_server"] = "other-protocol"
        code, call, _, stderr = self.run_main(self.root / "server-mismatch.json", response={}, binding=binding,
                                              capability="solve", expected_server="hub-protocol")
        self.assertEqual((code, call.await_count), (2, 0))
        self.assertIn("expected_server", stderr)

        # codex_server is an alias; the actual protocol identity may differ.
        code, call, _, _ = self.run_main(self.root / "alias.json", response={"result": {"isError": False,
            "content": [{"type": "text", "text": '{"job":{"job_id":"alias-1"}}'}]}},
            binding=self.async_binding(), capability="solve", expected_server="hub-protocol")
        self.assertEqual((code, call.await_count), (0, 1))

        binding = self.async_binding()
        binding["capabilities"]["solve"]["task_id_field"] = "job..job_id"
        code, call, _, stderr = self.run_main(self.root / "bad-path.json", response={}, binding=binding, capability="solve")
        self.assertEqual((code, call.await_count), (2, 0))
        self.assertIn("task_id_field", stderr)
        preflight = mcp_call._preflight(server_name="hub-protocol", expected_server="hub-protocol",
            tools=[{"name": "demo_tool", "inputSchema": {"type": "object"}}], tool_name="demo_tool",
            arguments={}, query_tool="query_job")
        self.assertEqual((preflight["preflight_error"], preflight["tool_sent"]), ("missing_query_tool", False))

    def test_invoke_preflight_rejections_never_call_tool_with_sdk_stubs(self):
        calls = []

        class Context:
            def __init__(self, value): self.value = value
            async def __aenter__(self): return self.value
            async def __aexit__(self, *args): return False

        class FakeTool:
            def __init__(self, name, schema): self.name, self.schema = name, schema
            def model_dump(self, **kwargs): return {"name": self.name, "inputSchema": self.schema}

        class FakeSession:
            tools = []
            call_error = None
            def __init__(self, *args): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def initialize(self):
                return types.SimpleNamespace(model_dump=lambda **kwargs: {"serverInfo": {"name": "actual"}})
            async def list_tools(self, *args, **kwargs):
                return types.SimpleNamespace(tools=type(self).tools, nextCursor=None)
            async def call_tool(self, *args, **kwargs):
                calls.append(args)
                if type(self).call_error is not None:
                    raise type(self).call_error
                return types.SimpleNamespace(model_dump=lambda **kw: {"isError": False})

        class FakeValidator:
            def __init__(self, schema): self.schema = schema
            @classmethod
            def check_schema(cls, schema): return None
            def iter_errors(self, value):
                if "x" in self.schema.get("required", []) and "x" not in value:
                    return [types.SimpleNamespace(message="'x' is a required property", path=[])]
                return []

        fake_jsonschema = types.SimpleNamespace(Draft202012Validator=FakeValidator, SchemaError=ValueError)
        mcp_module = types.ModuleType("mcp")
        mcp_module.ClientSession = FakeSession
        client_module = types.ModuleType("mcp.client")
        stream_module = types.ModuleType("mcp.client.streamable_http")
        stream_module.streamable_http_client = lambda *args, **kwargs: Context((None, None, None))
        httpx_module = types.ModuleType("httpx")
        httpx_module.AsyncClient = lambda *args, **kwargs: Context(object())

        def run_inline(coro):
            try:
                coro.send(None)
            except StopIteration as done:
                return done.value
            raise AssertionError("fake invoke unexpectedly suspended")

        cases = [
            ("wrong_server", "wrong", [FakeTool("demo_tool", {"type": "object"}), FakeTool("query_job", {"type": "object"})]),
            ("missing_tool", None, [FakeTool("other_tool", {"type": "object"}), FakeTool("query_job", {"type": "object"})]),
            ("missing_query_tool", None, [FakeTool("demo_tool", {"type": "object"})]),
            ("invalid_tool_schema", None, [FakeTool("demo_tool", None), FakeTool("query_job", {"type": "object"})]),
            ("invalid_arguments", None, [FakeTool("demo_tool", {"type": "object", "required": ["x"]}), FakeTool("query_job", {"type": "object"})]),
            ("valid", None, [FakeTool("demo_tool", {"type": "object"}), FakeTool("query_job", {"type": "object"})]),
        ]
        for expected_error, expected_server, tools in cases:
            with self.subTest(expected_error=expected_error):
                FakeSession.tools = tools
                args = types.SimpleNamespace(action="call", url="http://127.0.0.1:1/mcp",
                    token_env="EDS_MCP_TOKEN", timeout=1, expected_server=expected_server,
                    tool="demo_tool", _data={}, capability="solve",
                    _binding={"capabilities": {"solve": {"async": True, "query_tool": "query_job",
                    "task_id_field": "job.job_id"}}})
                with patch.dict(sys.modules, {"httpx": httpx_module, "mcp": mcp_module,
                        "mcp.client": client_module, "mcp.client.streamable_http": stream_module,
                        "jsonschema": fake_jsonschema}):
                    result = run_inline(mcp_call.invoke(args))
                if expected_error == "valid":
                    self.assertEqual((result["preflight_rejected"], result["tool_sent"]), (False, True))
                else:
                    self.assertEqual(result["preflight_error"], expected_error)
                    self.assertFalse(result["tool_sent"])
        self.assertEqual(len(calls), 1)

        def run_real_main(argv):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(sys.modules, {"httpx": httpx_module, "mcp": mcp_module,
                    "mcp.client": client_module, "mcp.client.streamable_http": stream_module,
                    "jsonschema": fake_jsonschema}), patch.object(sys, "argv", argv), \
                    patch.object(mcp_call.asyncio, "run", run_inline), \
                    patch.object(mcp_call.asyncio, "wait_for", lambda coro, timeout: coro), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = mcp_call.main()
            return code, stdout.getvalue(), stderr.getvalue()

        # Once call_tool has accepted the operation, a transport timeout leaves
        # execution ambiguous: the recorded Run is unknown and must be queried.
        FakeSession.tools = [FakeTool("demo_tool", {"type": "object"}),
                             FakeTool("query_job", {"type": "object"})]
        FakeSession.call_error = TimeoutError("remote call timed out")
        timeout_output = self.root / "sdk-timeout.json"
        timeout_argv = ["mcp_call.py", "--url", "http://127.0.0.1:1/mcp",
                        "--output", str(timeout_output), "--study-root", str(self.root / "study"),
                        "--experiment-ref", "exp", "call", "demo_tool", "--data", str(self.data)]
        code, _, timeout_stderr = run_real_main(timeout_argv)
        timeout_failure = json.loads(timeout_stderr)
        self.assertEqual(code, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.latest()["status"], "unknown")
        self.assertEqual((timeout_failure["run_status"], timeout_failure["requires_query"]),
                         ("unknown", True))
        self.assertEqual((timeout_failure["tool_sent"], timeout_failure["current_call_not_executed"]),
                         (None, None))
        self.assertEqual((timeout_failure["invoke_started"], timeout_failure["preflight_outcome"]),
                         (True, "unknown"))
        self.assertIn("query", timeout_failure["retry"])

        # A local preflight rejection occurs before call_tool and can state that
        # this invocation was not sent, while still recording the failed Run.
        FakeSession.call_error = None
        FakeSession.tools = [FakeTool("other_tool", {"type": "object"}),
                             FakeTool("query_job", {"type": "object"})]
        reject_output = self.root / "sdk-preflight-rejected.json"
        reject_argv = ["mcp_call.py", "--url", "http://127.0.0.1:1/mcp",
                       "--output", str(reject_output), "--study-root", str(self.root / "study"),
                       "--experiment-ref", "exp", "--input-ref", "state-b", "call", "demo_tool",
                       "--data", str(self.data)]
        code, reject_stdout, reject_stderr = run_real_main(reject_argv)
        reject_failure = json.loads(reject_stderr)
        self.assertEqual((code, len(calls), reject_stdout), (2, 2, ""))
        self.assertEqual(self.latest()["status"], "unknown")
        self.assertEqual((reject_failure["existing_status"], reject_failure["tool_sent"],
                          reject_failure["current_call_not_executed"]), ("unknown", False, True))

    def test_async_ack_survives_evidence_write_failure(self):
        output = self.root / "write-fails.json"
        response = {"result": {"isError": False, "content": [{"type": "text",
                    "text": '{"success":true,"job":{"job_id":"durable-1"}}'}]}}
        original_write_text = Path.write_text
        def fail_evidence(path, data, *args, **kwargs):
            if path == output:
                raise OSError("evidence disk full")
            return original_write_text(path, data, *args, **kwargs)
        with patch.object(Path, "write_text", autospec=True, side_effect=fail_evidence):
            code, call, _, stderr = self.run_main(output, response=response, binding=self.async_binding(), capability="solve")
        self.assertEqual((code, call.await_count), (2, 1))
        run = self.latest()
        self.assertEqual((run["status"], run["task_id"], run["output"]), ("submitted", "durable-1", response))
        failure = json.loads(stderr)
        self.assertEqual((failure["protocol_completed"], failure["run_status"], failure["task_id"]),
                         (True, "submitted", "durable-1"))

    def test_transport_error_records_unknown_and_does_not_retry_existing_evidence(self):
        output = self.root / "transport-error.json"
        code, call, _, stderr = self.run_main(output, error=TimeoutError("network timeout"))
        self.assertEqual(code, 2)
        self.assertEqual(call.await_count, 1)
        run = self.latest()
        self.assertEqual(run["status"], "unknown")
        self.assertIn(run["run_id"], stderr)
        retry_code, retry_call, _, _ = self.run_main(output, response={"result": {"ok": True}})
        self.assertEqual(retry_code, 2)
        self.assertEqual(retry_call.await_count, 0)
        retry_code, retry_call, _, retry_stderr = self.run_main(
            self.root / "transport-error-new-path.json", response={"result": {"ok": True}})
        self.assertEqual(retry_code, 2)
        self.assertEqual(retry_call.await_count, 0)
        retry_failure = json.loads(retry_stderr)
        self.assertEqual((retry_failure["existing_status"], retry_failure["tool_sent"]), ("unknown", False))
        self.assertFalse(json.loads(stderr)["protocol_completed"])

    def test_legacy_unknown_run_blocks_retry_after_stable_key_change(self):
        legacy = self.store.add_run(
            experiment_ref="exp", input_refs=[], backend="mcp", capability="demo_tool",
            input_snapshot={"tool": "demo_tool", "arguments": {"params": {"value": 1}},
                            "server_url": "http://127.0.0.1:1/mcp", "expected_server": None,
                            "output_path": str(self.root / "old.json")}, idempotency_key="legacy-output-key")
        self.store.transition_run(legacy["run_id"], "submitting")
        self.store.transition_run(legacy["run_id"], "unknown", output={"error": "lost"})
        code, call, _, stderr = self.run_main(self.root / "new.json", response={"result": {"ok": True}})
        self.assertEqual((code, call.await_count), (2, 0))
        self.assertIn("legacy MCP run", stderr)

        bound = self.store.add_run(
            experiment_ref="exp", input_refs=[], backend="hub", capability="solve",
            input_snapshot={"tool": "demo_tool", "arguments": {"params": {"value": "bound"}},
                            "server_url": "http://127.0.0.1:1/mcp", "expected_server": "hub-protocol"},
            idempotency_key="legacy-bound-key")
        self.store.transition_run(bound["run_id"], "submitting")
        self.store.transition_run(bound["run_id"], "unknown", output={"error": "lost"})
        self.data.write_text(json.dumps({"params": {"value": "bound"}}), encoding="utf-8")
        code, call, _, stderr = self.run_main(self.root / "bound-new.json", response={"result": {"ok": True}},
                                              binding=self.async_binding(), capability="solve",
                                              expected_server="hub-protocol")
        self.assertEqual((code, call.await_count), (2, 0))
        self.assertIn("legacy MCP run", stderr)

    def test_idempotency_resolves_bare_and_pinned_experiment_refs(self):
        code, call, _, _ = self.run_main(self.root / "first.json", error=TimeoutError("lost"))
        self.assertEqual((code, call.await_count), (2, 1))
        code, call, _, stderr = self.run_main(self.root / "second.json", response={"result": {"ok": True}},
                                              experiment_ref="exp@1")
        self.assertEqual((code, call.await_count), (2, 0))
        failure = json.loads(stderr)
        self.assertEqual((failure["existing_status"], failure["tool_sent"]), ("unknown", False))
        self.assertEqual(failure["existing_run_id"], self.latest()["run_id"])


    def test_operation_payload_failure_detection_and_study_pair_validation(self):
        result = {"result": {"isError": False, "content": [{"type": "text", "text":
            '{"status":"error","success":false}'}]}}
        self.assertTrue(mcp_call._operation_failed(result))
        self.assertTrue(mcp_call._operation_failed({"result": {
            "structuredContent": {"status": "failed"}}}))
        self.assertTrue(mcp_call._operation_failed({"result": {"isError": False, "content": [{
            "type": "text", "text": '{"ok":false,"status":"not_configured","error":"bridge unavailable"}'}]}}))
        self.assertFalse(mcp_call._operation_failed({"result": {"isError": False, "content": [{
            "type": "text", "text": '{"ok":true,"status":"connected"}'}]}}))
        with patch.object(sys, "argv", ["mcp_call.py", "--url", "http://127.0.0.1:1/mcp",
                                         "--output", str(self.root / "bad.json"), "--study-root",
                                         str(self.root / "study"), "discover"]):
            with self.assertRaises(SystemExit) as raised:
                mcp_call.main()
        self.assertEqual(raised.exception.code, 2)

    def test_preflight_rejects_wrong_server_missing_tool_and_invalid_args(self):
        tools = [{"name": "solidworks_health_check", "inputSchema": {
            "type": "object", "required": ["params"], "properties": {"params": {"type": "object"}}
        }}]
        wrong = mcp_call._preflight(server_name="other", expected_server="solidworks_mcp",
                                    tools=tools, tool_name="solidworks_health_check", arguments={"params": {}})
        self.assertEqual((wrong["preflight_error"], wrong["tool_sent"]), ("wrong_server", False))
        missing = mcp_call._preflight(server_name="solidworks_mcp", expected_server="solidworks_mcp",
                                      tools=tools, tool_name="missing", arguments={})
        self.assertEqual((missing["preflight_error"], missing["tool_sent"]), ("missing_tool", False))
        for schema in (None, {}, {"type": "array"}):
            malformed = mcp_call._preflight(server_name="solidworks_mcp", expected_server="solidworks_mcp",
                tools=[{"name": "broken", "inputSchema": schema}], tool_name="broken", arguments={})
            self.assertEqual((malformed["preflight_error"], malformed["tool_sent"]), ("invalid_tool_schema", False))

        class SchemaError(ValueError):
            pass

        class Validator:
            def __init__(self, schema):
                self.schema = schema

            @classmethod
            def check_schema(cls, schema):
                if "properties" in schema and not isinstance(schema["properties"], dict):
                    raise SchemaError("properties must be an object")

            def iter_errors(self, value):
                if "params" not in value:
                    return [types.SimpleNamespace(message="'params' is a required property", path=[])]
                return []

        fake_jsonschema = types.SimpleNamespace(Draft202012Validator=Validator, SchemaError=SchemaError)
        with patch.dict(sys.modules, {"jsonschema": fake_jsonschema}):
            invalid = mcp_call._preflight(server_name="solidworks_mcp", expected_server="solidworks_mcp",
                                          tools=tools, tool_name="solidworks_health_check", arguments={})
            valid = mcp_call._preflight(server_name="solidworks_mcp", expected_server="solidworks_mcp",
                                        tools=tools, tool_name="solidworks_health_check", arguments={"params": {}})
            malformed = mcp_call._preflight(server_name="solidworks_mcp", expected_server="solidworks_mcp",
                tools=[{"name": "broken", "inputSchema": {"type": "object", "properties": 42}}],
                tool_name="broken", arguments={})
        self.assertEqual((invalid["preflight_error"], invalid["tool_sent"]), ("invalid_arguments", False))
        self.assertEqual((valid["preflight_rejected"], valid["tool_sent"]), (False, False))
        self.assertEqual((malformed["preflight_error"], malformed["tool_sent"]), ("invalid_tool_schema", False))

    def test_access_bearing_url_is_rejected_before_journaling(self):
        argv = ["mcp_call.py", "--url", "http://user:secret@127.0.0.1/mcp",
                "--output", str(self.root / "secret.json"), "--study-root", str(self.root / "study"),
                "--experiment-ref", "exp", "call", "demo_tool", "--data", str(self.data)]
        with patch.object(sys, "argv", argv), patch.object(mcp_call, "invoke", AsyncMock()) as call, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(mcp_call.main(), 2)
        call.assert_not_called()
        self.assertEqual(self.store.read()["runs"], [])
        self.assertNotIn("user:secret", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
