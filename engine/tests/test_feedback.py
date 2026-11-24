import json

import httpx
import pytest

from newcad_engine.feedback import ASSET_BRANCH, FeedbackStore


class FakeGitHub:
    def __init__(self, down: bool = False):
        self.down = down
        self.calls: list[tuple[str, str, dict]] = []
        self.labels: set[str] = set()
        self.files: dict[str, str] = {}
        self.issues: list[dict] = []
        self.branch = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("offline", request=req)
        body = json.loads(req.content) if req.content else {}
        path = req.url.path
        self.calls.append((req.method, path, body))
        assert req.headers["authorization"] == "Bearer t0k"
        if path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if path == f"/repos/o/r/git/ref/heads/{ASSET_BRANCH}":
            return httpx.Response(200 if self.branch else 404, json={"object": {"sha": "b"}})
        if path == "/repos/o/r/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "abc"}})
        if path == "/repos/o/r/git/refs":
            self.branch = True
            return httpx.Response(201, json={})
        if path.startswith("/repos/o/r/contents/"):
            self.files[path] = body["branch"]
            return httpx.Response(201, json={})
        if path.startswith("/repos/o/r/labels/"):
            return httpx.Response(200 if path.rsplit("/", 1)[1] in self.labels else 404, json={})
        if path == "/repos/o/r/labels":
            self.labels.add(body["name"])
            return httpx.Response(201, json={})
        if path == "/repos/o/r/issues":
            self.issues.append(body)
            n = len(self.issues)
            return httpx.Response(201, json={"number": n, "html_url": f"https://github.com/o/r/issues/{n}"})
        return httpx.Response(404, json={})


def store(tmp_path, gh, token="t0k"):
    return FeedbackStore(tmp_path, repo="o/r", token_source=lambda: token, transport=httpx.MockTransport(gh))


@pytest.mark.asyncio
async def test_feedback_files_issue_with_screenshot(tmp_path):
    gh = FakeGitHub()
    fs = store(tmp_path, gh)
    rec = await fs.submit("Idea", "Snap to grid\nwould be nice", {"project": "Gripper", "head": "9b11"}, b"\x89PNG fake")
    assert rec["status"] == "sent" and rec["issue"]["number"] == 1
    issue = gh.issues[0]
    assert issue["title"] == "[Idea] Snap to grid"
    assert issue["labels"] == ["feedback", "feedback:idea"]
    assert "Gripper" in issue["body"] and f"{ASSET_BRANCH}/feedback/{rec['id']}.png" in issue["body"]
    assert gh.branch and list(gh.files.values()) == [ASSET_BRANCH]
    assert {"feedback", "feedback:idea"} <= gh.labels
    # kept on disk as well
    saved = json.loads((tmp_path / "feedback" / f"{rec['id']}.json").read_text())
    assert saved["issue"]["url"].endswith("/issues/1")
    assert (tmp_path / "feedback" / f"{rec['id']}.png").exists()


@pytest.mark.asyncio
async def test_feedback_kept_when_offline_and_retried(tmp_path):
    gh = FakeGitHub(down=True)
    fs = store(tmp_path, gh)
    rec = await fs.submit("Bug", "Crash on export", None, None)
    assert rec["status"] == "pending" and rec["error"]
    assert fs.list()[0]["status"] == "pending"
    gh.down = False
    assert await fs.retry_pending() == 1
    assert fs.list()[0]["status"] == "sent" and gh.issues[0]["title"] == "[Bug] Crash on export"


@pytest.mark.asyncio
async def test_feedback_without_token_stays_local(tmp_path):
    fs = store(tmp_path, FakeGitHub(), token=None)
    rec = await fs.submit("Question", "How do I mirror a part?", None, None)
    assert rec["status"] == "pending" and "gh auth login" in rec["error"]


def test_feedback_api_attaches_model_picture(tmp_path):
    from fastapi.testclient import TestClient

    from newcad_engine.api.app import create_app
    from newcad_engine.config import Config
    from newcad_engine.core import Engine

    gh = FakeGitHub()
    eng = Engine(Config(home=tmp_path, token="tok", workers=1))
    eng.feedback = store(tmp_path, gh)
    H = {"Authorization": "Bearer tok"}
    with TestClient(create_app(eng)) as c:
        pid = c.post("/api/projects", json={"name": "Fb", "template": "demo"}, headers=H).json()["id"]
        r = c.post("/api/feedback", json={"type": "Bug", "text": "Hole is off", "screenshot": True, "project": pid, "context": {"project": "Fb"}}, headers=H).json()
        assert r["status"] == "sent" and r["screenshot"]
        assert (tmp_path / "feedback" / r["screenshot"]).read_bytes()[:4] == b"\x89PNG"
        assert c.get("/api/feedback", headers=H).json()[0]["id"] == r["id"]
        assert c.post("/api/feedback", json={"text": ""}, headers=H).status_code == 422
