import logging

from fastapi.testclient import TestClient

from newcad_engine.api.app import create_app, origin_ok
from newcad_engine.config import Config
from newcad_engine.core import Engine

logging.getLogger("httpx").setLevel(logging.WARNING)
H = {"Authorization": "Bearer tok"}


def test_api_end_to_end(tmp_path):
    eng = Engine(Config(home=tmp_path, token="tok", workers=2))
    with TestClient(create_app(eng)) as c:
        assert c.get("/api/health").json()["ok"]
        assert c.get("/api/projects").status_code == 401
        assert c.get("/api/projects", headers={"X-NewCAD-Token": "tok"}).status_code == 200
        assert c.get("/api/projects", headers={**H, "Origin": "https://evil.example"}).status_code == 403
        assert c.get("/api/projects", headers={**H, "Origin": "http://localhost:5173"}).status_code == 200
        pid = c.post("/api/projects", json={"name": "Api demo", "template": "demo"}, headers=H).json()["id"]
        man = c.post(f"/api/projects/{pid}/build", headers=H).json()
        assert man["ok"] and len(man["parts"]) == 3
        glb = c.get(man["parts"][0]["glb"], headers=H)
        assert glb.status_code == 200 and glb.content[:4] == b"glTF"
        # code edit from the Code panel = one commit by You
        files = c.get(f"/api/projects/{pid}/files", headers=H).json()["files"]
        r = c.put(f"/api/projects/{pid}/parts/plate", json={"code": files["parts/plate.py"].replace("220", "200")}, headers=H).json()
        assert r["commit"]["author"] == "You" and r["branch"] == "main"
        # spec answers and comments
        spec = c.post(f"/api/projects/{pid}/spec/answer", json={"question_id": "function-1", "text": "Carry 4 kg"}, headers=H).json()
        assert spec["categories"][0]["questions"][0]["answers"][0] == {"text": "Carry 4 kg", "by": "you", "assumption": False}
        face = c.get(f"/api/cache/{man['parts'][0]['key']}/faces", headers=H).json()["faces"][0]
        note = c.post(f"/api/projects/{pid}/notes", json={"part": "plate", "text": "Chamfer", "face": face["tag"], "key": man["parts"][0]["key"]}, headers=H).json()
        assert note["face_sig"]["type"] == face["type"]
        # Bot via the scripted model, events over the WebSocket
        c.put("/api/settings", json={"provider": "scripted"}, headers=H)
        with c.websocket_connect("/api/ws?token=tok") as ws:
            assert ws.receive_json()["type"] == "hello"
            task = c.post(f"/api/projects/{pid}/bot/chat", json={"message": "Add a bracket"}, headers=H).json()
            seen = set()
            for _ in range(200):
                ev = ws.receive_json()
                seen.add(ev["type"])
                if ev["type"] == "bot.message" and ev["message"].get("task") == task["id"]:
                    break
            assert {"bot.task", "project.changed", "bot.message"} <= seen
        log = c.get(f"/api/projects/{pid}/log", headers=H).json()
        assert task["branch"] in log["branches"] and log["head"] == "main"
        merged = c.post(f"/api/projects/{pid}/merge", json={"source": task["branch"]}, headers=H).json()
        assert merged["commit"]["branch"] == "main"
        cmp = c.get(f"/api/projects/{pid}/compare", params={"refs": f"main,{log['commits'][0]['id']}"}, headers=H).json()
        assert cmp[0]["mass_kg"] != cmp[1]["mass_kg"]
        assert c.get(f"/api/projects/{pid}/snapshot.png", headers=H).content[:4] == b"\x89PNG"
        step = c.post(f"/api/projects/{pid}/export", json={"format": "step"}, headers=H)
        assert step.status_code == 200 and b"ISO-10303" in step.content[:200]


def test_origin_rules():
    allowed = Config().allowed_origins
    assert origin_ok(None, allowed) and origin_ok("http://localhost:5173", allowed) and origin_ok("tauri://localhost", allowed)
    assert not origin_ok("http://localhost.evil.com", allowed) and not origin_ok("https://example.com", allowed)
