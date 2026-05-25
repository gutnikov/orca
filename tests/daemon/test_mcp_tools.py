from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from orca.daemon.mcp_tools import create_mcp_server

FAKE_ROOT = "/tmp/test-repo"


def _first_text(content_blocks: object) -> str:
    assert isinstance(content_blocks, list)
    first_block = content_blocks[0]
    assert isinstance(first_block, TextContent)
    return str(first_block.text)


@pytest.fixture()
def mock_client() -> MagicMock:
    from orca.daemon.client import DaemonClient

    mock = MagicMock(spec=DaemonClient)
    mock.status = AsyncMock(return_value={"uptime": 1.0, "active_runs": 0, "total_runs": 0})
    mock.list_runs = AsyncMock(return_value=[])
    mock.get_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.get_issue = AsyncMock(return_value={"error": "issue 'iss-1' not found in run 'nope:default'"})
    mock.get_worker_log = AsyncMock(return_value="")
    mock.retry_issue = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.stop_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.drop_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.resume_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.list_inline_comments = AsyncMock(return_value={"comments": []})
    mock.add_thread_message = AsyncMock(return_value={"message_id": "msg-1"})
    mock.skip_comment = AsyncMock(return_value={"ok": True})
    return mock


class TestMcpToolRegistration:
    def test_server_has_all_tools(self) -> None:
        server = create_mcp_server()
        assert server is not None

    @pytest.mark.asyncio()
    async def test_all_tools_registered(self) -> None:
        server = create_mcp_server()
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "orca_daemon_status",
            "orca_start_run",
            "orca_list_runs",
            "orca_get_run",
            "orca_get_issue",
            "orca_get_worker_log",
            "orca_retry_issue",
            "orca_stop_run",
            "orca_drop_run",
            "orca_resume_run",
            "orca_unblock_worker",
            "orca_get_debug_review",
            "orca_submit_debug_decision",
            "orca_restart_state",
            "orca_clear_modify_pending",
            "orca_list_pending_comments",
            "orca_reply_to_comment",
            "orca_skip_comment",
            "orca_get_playbook",
            "orca_list_playbooks",
        }
        assert tool_names == expected


@pytest.mark.asyncio()
class TestDaemonStatusTool:
    async def test_returns_uptime_and_counts(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_daemon_status", {"root": FAKE_ROOT})
        data = json.loads(_first_text(content_blocks))
        assert data["active_runs"] == 0
        assert data["total_runs"] == 0
        assert "uptime" in data


@pytest.mark.asyncio()
class TestListRunsTool:
    async def test_empty_list(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_list_runs", {"root": FAKE_ROOT})
        data = json.loads(_first_text(content_blocks))
        assert data == []


@pytest.mark.asyncio()
class TestGetRunTool:
    async def test_not_found(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_get_run", {"root": FAKE_ROOT, "run_id": "nope:default"})
        data = json.loads(_first_text(content_blocks))
        assert "error" in data

    async def test_not_found_message(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_get_run", {"root": FAKE_ROOT, "run_id": "nope:default"})
        data = json.loads(_first_text(content_blocks))
        assert "nope:default" in data["error"]


@pytest.mark.asyncio()
class TestGetIssueTool:
    async def test_not_found_run(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_get_issue", {"root": FAKE_ROOT, "run_id": "nope:default", "issue_id": "iss-1"}
            )
        data = json.loads(_first_text(content_blocks))
        assert "error" in data


@pytest.mark.asyncio()
class TestGetWorkerLogTool:
    async def test_empty_for_unknown_run(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_get_worker_log", {"root": FAKE_ROOT, "run_id": "nope:default", "issue_id": "iss-1"}
            )
        assert _first_text(content_blocks) == ""


@pytest.mark.asyncio()
class TestRetryIssueTool:
    async def test_not_found(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_retry_issue", {"root": FAKE_ROOT, "run_id": "nope:default", "issue_id": "iss-1"}
            )
        data = json.loads(_first_text(content_blocks))
        assert "error" in data


@pytest.mark.asyncio()
class TestStopRunTool:
    async def test_not_found(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_stop_run", {"root": FAKE_ROOT, "run_id": "nope:default"})
        data = json.loads(_first_text(content_blocks))
        assert "error" in data


@pytest.mark.asyncio()
class TestGetPlaybookTool:
    async def test_returns_top_level_playbook_content(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_get_playbook", {"name": "orca-workflow-create"})
        text = _first_text(content_blocks)
        # The playbook starts with this header — proves we read the bundled file.
        assert text.startswith("# Playbook: Create an Orca Workflow")

    async def test_returns_subdir_playbook_content(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_get_playbook", {"name": "reference/orca-glossary"})
        text = _first_text(content_blocks)
        # First line of the glossary — proves the subdir lookup works.
        assert "glossary" in text.lower()

    async def test_accepts_trailing_md_suffix(self) -> None:
        """Names with or without `.md` should resolve identically."""
        server = create_mcp_server()
        with_md, _ = await server.call_tool("orca_get_playbook", {"name": "orca-workflow-create.md"})
        without_md, _ = await server.call_tool("orca_get_playbook", {"name": "orca-workflow-create"})
        assert _first_text(with_md) == _first_text(without_md)

    async def test_rejects_parent_traversal(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="invalid playbook name"):
            await server.call_tool("orca_get_playbook", {"name": "../../../etc/passwd"})

    async def test_rejects_absolute_path(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="invalid playbook name"):
            await server.call_tool("orca_get_playbook", {"name": "/etc/passwd"})

    async def test_rejects_empty_name(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="invalid playbook name"):
            await server.call_tool("orca_get_playbook", {"name": ""})

    async def test_errors_on_unknown_playbook(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="playbook not found"):
            await server.call_tool("orca_get_playbook", {"name": "does-not-exist"})


@pytest.mark.asyncio()
class TestListPlaybooksTool:
    async def test_includes_known_playbooks(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_list_playbooks", {})
        names = json.loads(_first_text(content_blocks))
        assert isinstance(names, list)
        # Spot-check a few well-known playbooks.
        assert "orca-workflow-create" in names
        assert "reference/orca-glossary" in names
        assert "reference/wrapper-skill-template" in names

    async def test_sorted_and_unique(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_list_playbooks", {})
        names = json.loads(_first_text(content_blocks))
        assert names == sorted(names)
        assert len(names) == len(set(names))

    async def test_no_md_suffix(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_list_playbooks", {})
        names = json.loads(_first_text(content_blocks))
        for n in names:
            assert not n.endswith(".md")


# -------------------------------------------------------------------------- #
# Inline-comment conversational tools (Task 6)                               #
# -------------------------------------------------------------------------- #


def _comment(
    cid: str,
    *,
    file: str = "src/foo.py",
    line: int | None = 10,
    body: str = "please fix this",
    thread: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": cid,
        "file": file,
        "line": line,
        "body": body,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "thread": thread,
    }


def _thread(
    messages: list[dict[str, object]],
    *,
    agent_last_reviewed_at: str | None = None,
) -> dict[str, object]:
    return {
        "id": "thr-1",
        "comment_id": "c-1",
        "messages": messages,
        "agent_last_reviewed_at": agent_last_reviewed_at,
    }


def _msg(role: str, body: str, timestamp: str, mid: str = "m") -> dict[str, object]:
    return {"id": mid, "role": role, "body": body, "timestamp": timestamp}


@pytest.mark.asyncio()
class TestListPendingCommentsTool:
    async def test_no_thread_is_pending(self, mock_client: MagicMock) -> None:
        mock_client.list_inline_comments = AsyncMock(return_value={"comments": [_comment("c-1", thread=None)]})
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
        data = json.loads(_first_text(content_blocks))
        assert len(data["comments"]) == 1
        item = data["comments"][0]
        assert item["id"] == "c-1"
        assert item["file"] == "src/foo.py"
        assert item["line"] == 10
        assert item["body"] == "please fix this"
        assert item["thread_messages"] == []

    async def test_agent_latest_message_not_pending(self, mock_client: MagicMock) -> None:
        thread = _thread(
            [
                _msg("user", "please fix", "2026-01-01T00:00:00Z", "m1"),
                _msg("agent", "ok will do", "2026-01-01T00:00:01Z", "m2"),
            ],
            agent_last_reviewed_at="2026-01-01T00:00:01Z",
        )
        mock_client.list_inline_comments = AsyncMock(return_value={"comments": [_comment("c-1", thread=thread)]})
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
        data = json.loads(_first_text(content_blocks))
        assert data["comments"] == []

    async def test_user_reply_newer_than_reviewed_is_pending(self, mock_client: MagicMock) -> None:
        thread = _thread(
            [
                _msg("user", "first", "2026-01-01T00:00:00Z", "m1"),
                _msg("agent", "got it", "2026-01-01T00:00:01Z", "m2"),
                _msg("user", "also this", "2026-01-01T00:00:03Z", "m3"),
            ],
            agent_last_reviewed_at="2026-01-01T00:00:01Z",
        )
        mock_client.list_inline_comments = AsyncMock(return_value={"comments": [_comment("c-1", thread=thread)]})
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
        data = json.loads(_first_text(content_blocks))
        assert len(data["comments"]) == 1
        item = data["comments"][0]
        assert item["id"] == "c-1"
        assert len(item["thread_messages"]) == 3
        assert item["thread_messages"][-1]["body"] == "also this"

    async def test_user_msg_older_than_reviewed_not_pending(self, mock_client: MagicMock) -> None:
        thread = _thread(
            [_msg("user", "already-seen", "2026-01-01T00:00:00Z", "m1")],
            agent_last_reviewed_at="2026-01-01T00:00:05Z",
        )
        mock_client.list_inline_comments = AsyncMock(return_value={"comments": [_comment("c-1", thread=thread)]})
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
        data = json.loads(_first_text(content_blocks))
        assert data["comments"] == []

    async def test_mixed_only_pending_returned(self, mock_client: MagicMock) -> None:
        pending_no_thread = _comment("c-pending-1", thread=None)
        not_pending_agent_last = _comment(
            "c-not-1",
            thread=_thread(
                [
                    _msg("user", "u", "2026-01-01T00:00:00Z", "m1"),
                    _msg("agent", "a", "2026-01-01T00:00:01Z", "m2"),
                ],
                agent_last_reviewed_at="2026-01-01T00:00:01Z",
            ),
        )
        pending_new_user = _comment(
            "c-pending-2",
            thread=_thread(
                [
                    _msg("user", "old", "2026-01-01T00:00:00Z", "m1"),
                    _msg("agent", "a", "2026-01-01T00:00:01Z", "m2"),
                    _msg("user", "new", "2026-01-01T00:00:05Z", "m3"),
                ],
                agent_last_reviewed_at="2026-01-01T00:00:01Z",
            ),
        )
        mock_client.list_inline_comments = AsyncMock(
            return_value={"comments": [pending_no_thread, not_pending_agent_last, pending_new_user]}
        )
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
        data = json.loads(_first_text(content_blocks))
        ids = [c["id"] for c in data["comments"]]
        assert ids == ["c-pending-1", "c-pending-2"]


@pytest.mark.asyncio()
class TestReplyToCommentTool:
    async def test_returns_message_id(self, mock_client: MagicMock) -> None:
        mock_client.add_thread_message = AsyncMock(return_value={"message_id": "m-new"})
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_reply_to_comment",
                {
                    "root": FAKE_ROOT,
                    "run_id": "r1",
                    "issue_id": "iss-1",
                    "comment_id": "c-1",
                    "body": "thanks, will address",
                },
            )
        data = json.loads(_first_text(content_blocks))
        assert data == {"message_id": "m-new"}
        mock_client.add_thread_message.assert_awaited_once_with("r1", "iss-1", "c-1", "agent", "thanks, will address")

    async def test_after_reply_comment_not_pending(self, mock_client: MagicMock) -> None:
        # Simulate: before reply -> pending (no thread). After reply -> thread
        # exists with agent as latest message, so not pending.
        responses = iter(
            [
                {"comments": [_comment("c-1", thread=None)]},
                {
                    "comments": [
                        _comment(
                            "c-1",
                            thread=_thread(
                                [
                                    _msg("agent", "thanks", "2026-01-01T00:00:10Z", "m1"),
                                ],
                                agent_last_reviewed_at="2026-01-01T00:00:10Z",
                            ),
                        )
                    ]
                },
            ]
        )
        mock_client.list_inline_comments = AsyncMock(side_effect=lambda *_a, **_k: next(responses))
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            # Before
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
            before = json.loads(_first_text(content_blocks))
            assert len(before["comments"]) == 1
            # Reply
            await server.call_tool(
                "orca_reply_to_comment",
                {
                    "root": FAKE_ROOT,
                    "run_id": "r1",
                    "issue_id": "iss-1",
                    "comment_id": "c-1",
                    "body": "thanks",
                },
            )
            # After
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
            after = json.loads(_first_text(content_blocks))
        assert after["comments"] == []


@pytest.mark.asyncio()
class TestSkipCommentTool:
    async def test_returns_ok(self, mock_client: MagicMock) -> None:
        mock_client.skip_comment = AsyncMock(return_value={"ok": True})
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_skip_comment",
                {
                    "root": FAKE_ROOT,
                    "run_id": "r1",
                    "issue_id": "iss-1",
                    "comment_id": "c-1",
                    "reason": "directive — worker will see it",
                },
            )
        data = json.loads(_first_text(content_blocks))
        assert data == {"ok": True}
        mock_client.skip_comment.assert_awaited_once_with("r1", "iss-1", "c-1", "directive — worker will see it")

    async def test_after_skip_comment_not_pending(self, mock_client: MagicMock) -> None:
        # Simulate skip bumping agent_last_reviewed_at past the user message timestamp.
        responses = iter(
            [
                {
                    "comments": [
                        _comment(
                            "c-1",
                            thread=_thread(
                                [_msg("user", "u", "2026-01-01T00:00:00Z", "m1")],
                                agent_last_reviewed_at=None,
                            ),
                        )
                    ]
                },
                {
                    "comments": [
                        _comment(
                            "c-1",
                            thread=_thread(
                                [_msg("user", "u", "2026-01-01T00:00:00Z", "m1")],
                                agent_last_reviewed_at="2026-01-01T00:00:05Z",
                            ),
                        )
                    ]
                },
            ]
        )
        mock_client.list_inline_comments = AsyncMock(side_effect=lambda *_a, **_k: next(responses))
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            # Before: pending because reviewed_at is None
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
            before = json.loads(_first_text(content_blocks))
            assert len(before["comments"]) == 1
            # Skip
            await server.call_tool(
                "orca_skip_comment",
                {
                    "root": FAKE_ROOT,
                    "run_id": "r1",
                    "issue_id": "iss-1",
                    "comment_id": "c-1",
                    "reason": "n/a",
                },
            )
            # After
            content_blocks, _ = await server.call_tool(
                "orca_list_pending_comments",
                {"root": FAKE_ROOT, "run_id": "r1", "issue_id": "iss-1"},
            )
            after = json.loads(_first_text(content_blocks))
        assert after["comments"] == []
