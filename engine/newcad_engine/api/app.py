"""FastAPI app: REST for commands, one WebSocket for events, and MCP at /mcp.

Binds to 127.0.0.1. Every request except /api/health needs the per-launch
token (Authorization: Bearer, X-NewCAD-Token header, or ?token=). Browser
requests from origins other than localhost and the Tauri webview are refused.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from .. import __version__
from ..core import Actor, Engine, current_actor
from ..project import spec as S
from ..project.store import YOU, StoreError
from ..project.templates import dump

log = logging.getLogger("newcad.api")
USER = Actor(YOU[0], YOU[1])


def origin_ok(origin: str | None, allowed: tuple[str, ...]) -> bool:
    if not origin or origin == "null":
        return True
    for a in allowed:
        if origin == a or origin.startswith(a + ":"):
            return True
    return False


# ---------- request bodies ----------

class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    goal: str = ""
    template: str = "blank"


class PartCode(BaseModel):
    code: str
    message: str | None = None
    branch: str | None = None
    name: str | None = None
    color: str | None = None
    material: str | None = None


class Ref(BaseModel):
    ref: str


class NewBranch(BaseModel):
    name: str
    from_ref: str | None = None


class Merge(BaseModel):
    source: str
    into: str | None = None


class Answer(BaseModel):
    question_id: str
    text: str
    replace: bool = False
    assumption: bool = False


class RemoveAnswer(BaseModel):
    question_id: str
    index: int


class NewQuestion(BaseModel):
    category: str
    text: str
    parent: str | None = None


class Overview(BaseModel):
    overview: str


class NewNote(BaseModel):
    part: str
    text: str
    point: list[float] | None = None
    face: str | None = None
    key: str | None = None  # cache key of the part build the face tag comes from
    queue: bool = False


class NoteReply(BaseModel):
    text: str
    queue: bool = False


class NoteState(BaseModel):
    resolved: bool


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    selected: str | None = None


class Generate(BaseModel):
    count: int = 3


class InterviewStep(BaseModel):
    answered: str | None = None


class Comments(BaseModel):
    note_ids: list[int]


class SettingsPatch(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    effort: str | None = None
    max_steps: int | None = None
    max_tokens: int | None = None
    vision: bool | None = None
    build_while_interview: bool | None = None


class SessionKey(BaseModel):
    provider: str
    key: str


class Export(BaseModel):
    format: str = "step"
    ref: str | None = None
    parts: list[str] | None = None


def create_app(engine: Engine | None = None) -> FastAPI:
    eng = engine or Engine()
    mcp_app = eng.mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        await eng.start()
        async with eng.mcp.session_manager.run():
            yield
        await eng.stop()

    app = FastAPI(title="NewCAD engine", version=__version__, lifespan=lifespan)
    app.state.engine = eng
    cfg = eng.cfg

    class Guard(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if request.method == "OPTIONS":
                return await call_next(request)
            if not origin_ok(request.headers.get("origin"), cfg.allowed_origins):
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            if path != "/api/health" and (path.startswith("/api") or path.startswith("/mcp")):
                tok = request.headers.get("x-newcad-token") or request.query_params.get("token") or ""
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    tok = auth[7:]
                if not hmac.compare_digest(tok, cfg.token):
                    return JSONResponse({"detail": "Missing or wrong engine token"}, status_code=401)
            if path == "/mcp":  # serve /mcp and /mcp/ alike
                request.scope["path"] = "/mcp/"
                request.scope["raw_path"] = b"/mcp/"
            token = current_actor.set(USER if path.startswith("/api") else current_actor.get())
            try:
                return await call_next(request)
            finally:
                current_actor.reset(token)

    app.add_middleware(Guard)

    @app.exception_handler(StoreError)
    async def store_error(_: Request, e: StoreError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    def proj(pid: str):
        return eng.store.get(pid)

    # ---------- basics ----------

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "name": "newcad-engine", "version": __version__}

    @app.get("/api/version")
    async def version() -> dict[str, Any]:
        import build123d
        return {"engine": __version__, "build123d": build123d.__version__, "workers": eng.pool.size, "mcp": "/mcp"}

    # ---------- projects ----------

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, Any]]:
        return await asyncio.to_thread(eng.store.list)

    @app.post("/api/projects")
    async def create_project(body: NewProject) -> dict[str, Any]:
        p = eng.store.create(body.name, body.goal, body.template if body.template in ("blank", "demo") else "blank", YOU)
        return p.summary()

    @app.get("/api/projects/{pid}")
    async def get_project(pid: str) -> dict[str, Any]:
        p = proj(pid)
        s = p.summary()
        s["staged"] = sorted(p.staged(None)) if p.head_branch() else []
        return s

    @app.get("/api/projects/{pid}/files")
    async def files(pid: str, ref: str | None = None) -> dict[str, Any]:
        p = proj(pid)
        c = p.resolve(ref)
        return {"ref": ref or p.head_ref(), "commit": str(c.id), "files": p.files(ref)}

    @app.put("/api/projects/{pid}/parts/{part}")
    async def save_part(pid: str, part: str, body: PartCode) -> dict[str, Any]:
        """Code edited in the Code panel: one commit by the user on their branch."""
        p = proj(pid)
        b = p._branch_for_write(body.branch)
        asm = p.assembly(b)
        entry = next((e for e in asm["parts"] if e["id"] == part), None)
        changes: dict[str, str | None] = {}
        if entry is None:
            from ..project.store import valid_part_id
            valid_part_id(part)
            entry = {"id": part, "name": body.name or part, "file": f"parts/{part}.py", "color": body.color or "#B4C2D6", "material": body.material or "Steel"}
            asm["parts"].append(entry)
            changes["assembly.yaml"] = dump(asm)
        changes[entry.get("file") or f"parts/{part}.py"] = body.code if body.code.endswith("\n") else body.code + "\n"
        info = p.commit(b, body.message or f"Edit {entry.get('name', part)} in code", YOU, changes=changes, include_staged=False)
        return {"commit": info.to_json() if info else None, "branch": b}

    @app.post("/api/projects/{pid}/build")
    async def build(pid: str, ref: str | None = None) -> dict[str, Any]:
        man = await eng.geometry.build(proj(pid), ref)
        eng.events.publish({"type": "build.done", "project": pid, "ref": man["ref"], "ok": man["ok"]})
        return man

    @app.get("/api/cache/{key}/part.glb")
    async def glb(key: str) -> Response:
        f = eng.geometry.entry(key) / "part.glb"
        if not f.exists():
            raise HTTPException(404, "Not built")
        return FileResponse(f, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/cache/{key}/faces")
    async def faces(key: str) -> dict[str, Any]:
        m = eng.geometry.meta(key)
        if m is None:
            raise HTTPException(404, "Not built")
        return {"faces": m["faces"]}

    @app.get("/api/projects/{pid}/snapshot.png")
    async def snapshot(pid: str, ref: str | None = None, view: str = "iso", w: int = 480, h: int = 360) -> Response:
        png, _ = await eng.geometry.snapshot(proj(pid), ref, view, (max(64, min(w, 1600)), max(64, min(h, 1200))))
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})

    @app.post("/api/projects/{pid}/export")
    async def export(pid: str, body: Export) -> Response:
        if body.format not in ("step", "stl"):
            raise HTTPException(400, "format must be step or stl")
        r = await eng.geometry.export(proj(pid), body.ref, body.format, body.parts)
        return FileResponse(r["path"], filename=r["file"], media_type="application/octet-stream")

    # ---------- versions ----------

    @app.get("/api/projects/{pid}/log")
    async def log_(pid: str) -> dict[str, Any]:
        p = proj(pid)
        return {"commits": [c.to_json() for c in p.log()], "tips": p.tips(), "head": p.head_ref(), "headBranch": p.head_branch(),
                "headCommit": str(p.resolve("HEAD").id), "branches": p.branches()}

    @app.post("/api/projects/{pid}/checkout")
    async def checkout(pid: str, body: Ref) -> dict[str, Any]:
        p = proj(pid)
        return {"head": p.checkout(body.ref), "headCommit": str(p.resolve("HEAD").id)}

    @app.post("/api/projects/{pid}/branches")
    async def new_branch(pid: str, body: NewBranch) -> dict[str, Any]:
        p = proj(pid)
        return {"branch": p.create_branch(body.name, body.from_ref, unique=True)}

    @app.delete("/api/projects/{pid}/branches/{name:path}")
    async def del_branch(pid: str, name: str) -> dict[str, Any]:
        proj(pid).delete_branch(name)
        return {"ok": True}

    @app.post("/api/projects/{pid}/merge")
    async def merge(pid: str, body: Merge) -> dict[str, Any]:
        return {"commit": proj(pid).merge(body.source, body.into, YOU).to_json()}

    @app.get("/api/projects/{pid}/diff")
    async def diff(pid: str, a: str, b: str) -> dict[str, Any]:
        return {"files": proj(pid).diff(a, b)}

    @app.get("/api/projects/{pid}/compare")
    async def compare(pid: str, refs: str) -> list[dict[str, Any]]:
        """Side-by-side numbers for several versions (mass now, safety factor once FEM exists)."""
        p = proj(pid)
        out = []
        for r in [x for x in refs.split(",") if x][:6]:
            man = await eng.geometry.build(p, r)
            out.append({"ref": r, "commit": man["commit"], "ok": man["ok"], "mass_kg": man["mass_kg"], "bbox": man["bbox"],
                        "parts": [{"id": x["id"], "name": x["name"], "ok": x["ok"], "mass_kg": x.get("mass_kg")} for x in man["parts"]]})
        return out

    # ---------- spec ----------

    def spec_write(p, mutate, message: str) -> dict[str, Any]:
        b = p._branch_for_write(None)
        spec = p.read_yaml("spec.yaml", b) or {"categories": []}
        mutate(spec)
        p.commit(b, message, YOU, changes={"spec.yaml": dump(spec)}, include_staged=False)
        return spec

    @app.get("/api/projects/{pid}/spec")
    async def get_spec(pid: str, ref: str | None = None) -> dict[str, Any]:
        return proj(pid).read_yaml("spec.yaml", ref) or {}

    @app.post("/api/projects/{pid}/spec/answer")
    async def answer(pid: str, body: Answer) -> dict[str, Any]:
        return spec_write(proj(pid), lambda s: S.answer(s, body.question_id, body.text, "you", body.assumption, body.replace), "Spec: answers")

    @app.post("/api/projects/{pid}/spec/answer/remove")
    async def remove_answer(pid: str, body: RemoveAnswer) -> dict[str, Any]:
        def m(s: dict[str, Any]) -> None:
            _, q = S.find_question(s, body.question_id)
            if 0 <= body.index < len(q.get("answers", [])):
                q["answers"].pop(body.index)
        return spec_write(proj(pid), m, "Spec: answers")

    @app.post("/api/projects/{pid}/spec/question")
    async def add_question(pid: str, body: NewQuestion) -> dict[str, Any]:
        return spec_write(proj(pid), lambda s: S.add_question(s, body.category, body.text, "you", body.parent), "Spec: questions")

    @app.delete("/api/projects/{pid}/spec/question/{qid}")
    async def del_question(pid: str, qid: str) -> dict[str, Any]:
        def m(s: dict[str, Any]) -> None:
            c, q = S.find_question(s, qid)
            c["questions"] = [x for x in c["questions"] if x["id"] != qid and x.get("parent") != qid]
        return spec_write(proj(pid), m, "Spec: questions")

    @app.put("/api/projects/{pid}/spec/overview")
    async def overview(pid: str, body: Overview) -> dict[str, Any]:
        return spec_write(proj(pid), lambda s: s.__setitem__("overview", body.overview.strip()), "Spec: overview")

    # ---------- notes ----------

    def notes_write(p, mutate, message: str) -> dict[str, Any]:
        b = p._branch_for_write(None)
        notes = p.read_yaml("notes.yaml", b) or {"notes": []}
        result = mutate(notes)
        p.commit(b, message, YOU, changes={"notes.yaml": dump(notes)}, include_staged=False)
        return result if result is not None else notes

    @app.get("/api/projects/{pid}/notes")
    async def get_notes(pid: str, ref: str | None = None) -> dict[str, Any]:
        return proj(pid).read_yaml("notes.yaml", ref) or {"notes": []}

    @app.post("/api/projects/{pid}/notes")
    async def add_note(pid: str, body: NewNote) -> dict[str, Any]:
        p = proj(pid)
        sig = None
        if body.face and body.key:
            meta = eng.geometry.meta(body.key) or {"faces": []}
            sig = next(({k: v for k, v in f.items() if k != "tag"} for f in meta["faces"] if f["tag"] == body.face), None)
        note = notes_write(p, lambda n: S.add_note(n, body.part, body.text, "You", body.point, body.face, sig, body.queue), "Comment")
        if body.queue:
            eng.bot.start_comments(pid, [note["id"]])
        return note

    @app.post("/api/projects/{pid}/notes/{nid}/reply")
    async def reply_note(pid: str, nid: int, body: NoteReply) -> dict[str, Any]:
        def m(n: dict[str, Any]) -> dict[str, Any]:
            note = S.find_note(n, nid)
            note["msgs"].append({"who": "You", "text": body.text})
            if body.queue:
                note["status"] = "queued"
            return note
        note = notes_write(proj(pid), m, "Comment")
        if body.queue:
            eng.bot.start_comments(pid, [nid])
        return note

    @app.post("/api/projects/{pid}/notes/{nid}/state")
    async def note_state(pid: str, nid: int, body: NoteState) -> dict[str, Any]:
        def m(n: dict[str, Any]) -> dict[str, Any]:
            note = S.find_note(n, nid)
            note["status"] = "resolved" if body.resolved else "open"
            return note
        return notes_write(proj(pid), m, "Comment")

    @app.delete("/api/projects/{pid}/notes/{nid}")
    async def del_note(pid: str, nid: int) -> dict[str, Any]:
        def m(n: dict[str, Any]) -> None:
            S.find_note(n, nid)
            n["notes"] = [x for x in n["notes"] if x["id"] != nid]
        return notes_write(proj(pid), m, "Comment")

    # ---------- BuilderBot ----------

    @app.get("/api/bot/status")
    async def bot_status(project: str | None = None) -> dict[str, Any]:
        return eng.bot.status(project)

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        return {**eng.settings.data, "session_keys": sorted(eng.settings.session_keys)}

    @app.put("/api/settings")
    async def put_settings(body: SettingsPatch) -> dict[str, Any]:
        eng.settings.update({k: v for k, v in body.model_dump().items() if v is not None})
        return eng.bot.status()

    @app.post("/api/settings/key")
    async def session_key(body: SessionKey) -> dict[str, Any]:
        """Keep an API key in memory for this engine run only (the desktop app stores it in the OS keychain)."""
        if body.key.strip():
            eng.settings.session_keys[body.provider] = body.key.strip()
        else:
            eng.settings.session_keys.pop(body.provider, None)
        return eng.bot.status()

    @app.get("/api/projects/{pid}/bot/chat")
    async def chat_log(pid: str) -> list[dict[str, Any]]:
        proj(pid)
        return eng.bot.chat(pid)

    @app.post("/api/projects/{pid}/bot/chat")
    async def chat(pid: str, body: Chat) -> dict[str, Any]:
        return eng.bot.start_change(pid, body.message, body.selected).to_json()

    @app.post("/api/projects/{pid}/bot/generate")
    async def generate(pid: str, body: Generate) -> dict[str, Any]:
        return eng.bot.generate(pid, body.count)

    @app.post("/api/projects/{pid}/bot/interview")
    async def interview(pid: str, body: InterviewStep) -> dict[str, Any]:
        return await eng.bot.interview_step(pid, body.answered)

    @app.post("/api/projects/{pid}/bot/comments")
    async def comments(pid: str, body: Comments) -> dict[str, Any]:
        return eng.bot.start_comments(pid, body.note_ids).to_json()

    @app.get("/api/projects/{pid}/bot/tasks")
    async def tasks(pid: str) -> list[dict[str, Any]]:
        return eng.bot.list(pid)

    @app.post("/api/bot/tasks/{tid}/stop")
    async def stop_task(tid: str) -> dict[str, Any]:
        return eng.bot.stop(tid).to_json()

    # ---------- events ----------

    @app.websocket("/api/ws")
    async def ws(socket: WebSocket) -> None:
        tok = socket.query_params.get("token") or socket.headers.get("x-newcad-token") or ""
        if not hmac.compare_digest(tok, cfg.token) or not origin_ok(socket.headers.get("origin"), cfg.allowed_origins):
            await socket.close(code=4401)
            return
        await socket.accept()
        q = eng.events.subscribe()
        try:
            await socket.send_text(json.dumps({"type": "hello", "version": __version__}))
            while True:
                ev = await q.get()
                await socket.send_text(json.dumps(ev, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            eng.events.unsubscribe(q)

    app.mount("/mcp", mcp_app)
    return app
