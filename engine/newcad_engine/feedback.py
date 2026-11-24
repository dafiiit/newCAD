"""Developer feedback: saved locally first, then filed as a GitHub issue.

Every report is written to ``$NEWCAD_HOME/feedback/<id>.json`` (plus ``<id>.png``
when a picture was attached) before anything goes over the network, so nothing
is lost when GitHub is unreachable. Reports that could not be sent stay
``pending`` and are retried on the next report and when the engine starts.

Issues go to ``NEWCAD_FEEDBACK_REPO`` (default ``dafiiit/newCAD``) with the
labels ``feedback`` and ``feedback:<type>``. Pictures are committed to the
``feedback-assets`` branch of that repo and linked from the issue.

The GitHub token comes from ``NEWCAD_GITHUB_TOKEN``, ``GITHUB_TOKEN`` or, if
neither is set, ``gh auth token`` (the GitHub CLI's login).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import platform
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from . import __version__

log = logging.getLogger(__name__)

DEFAULT_REPO = "dafiiit/newCAD"
ASSET_BRANCH = "feedback-assets"
API = "https://api.github.com"
TYPES = ("Bug", "Idea", "Question")


def _gh_token() -> str | None:
    for k in ("NEWCAD_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(k):
            return os.environ[k].strip()
    gh = shutil.which("gh") or next((p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if Path(p).exists()), None)
    if not gh:
        return None
    try:
        out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    tok = out.stdout.strip()
    return tok if out.returncode == 0 and tok else None


class FeedbackStore:
    def __init__(self, home: Path, repo: str | None = None, token_source=_gh_token, api: str = API, transport: httpx.AsyncBaseTransport | None = None):
        self.dir = home / "feedback"
        self.repo = repo or os.environ.get("NEWCAD_FEEDBACK_REPO", DEFAULT_REPO)
        self.token_source = token_source
        self.api = api
        self.transport = transport
        self._lock = asyncio.Lock()

    # ---------- local records ----------

    def _path(self, fid: str) -> Path:
        return self.dir / f"{fid}.json"

    def _save(self, rec: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(rec["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=2))
        tmp.replace(self._path(rec["id"]))

    def list(self) -> list[dict[str, Any]]:
        if not self.dir.exists():
            return []
        out = []
        for p in self.dir.glob("*.json"):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda r: r.get("created", 0), reverse=True)

    def create(self, type_: str, text: str, context: dict[str, Any] | None, png: bytes | None) -> dict[str, Any]:
        fid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        ctx = dict(context or {})
        ctx.setdefault("engine", __version__)
        ctx.setdefault("os", f"{platform.system()} {platform.release()} ({platform.machine()})")
        rec: dict[str, Any] = {
            "id": fid, "created": time.time(), "type": type_ if type_ in TYPES else "Bug", "text": text.strip(),
            "context": ctx, "screenshot": None, "status": "pending", "issue": None, "error": None, "repo": self.repo,
        }
        if png:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{fid}.png").write_bytes(png)
            rec["screenshot"] = f"{fid}.png"
        self._save(rec)
        return rec

    # ---------- GitHub ----------

    def _body(self, rec: dict[str, Any], image_url: str | None) -> str:
        lines = [rec["text"] or "_(no text)_", ""]
        if image_url:
            lines += [f"![screenshot]({image_url})", ""]
        ctx = rec.get("context") or {}
        if ctx:
            lines += ["<details><summary>Context</summary>", "", "| | |", "|---|---|"]
            lines += [f"| {k} | `{str(v).replace('|', '/')}` |" for k, v in ctx.items() if v not in (None, "")]
            lines += ["", "</details>", ""]
        lines.append(f"_Sent from the NewCAD app (feedback id `{rec['id']}`)._")
        return "\n".join(lines)

    @staticmethod
    def _title(rec: dict[str, Any]) -> str:
        first = (rec["text"].splitlines() or [""])[0].strip() or "(no text)"
        if len(first) > 70:
            first = first[:67].rstrip() + "..."
        return f"[{rec['type']}] {first}"

    async def _upload_png(self, c: httpx.AsyncClient, rec: dict[str, Any]) -> str | None:
        png = self.dir / rec["screenshot"]
        if not png.exists():
            return None
        ref = await c.get(f"/repos/{self.repo}/git/ref/heads/{ASSET_BRANCH}")
        if ref.status_code == 404:
            repo = (await c.get(f"/repos/{self.repo}")).raise_for_status().json()
            base = (await c.get(f"/repos/{self.repo}/git/ref/heads/{repo['default_branch']}")).raise_for_status().json()
            r = await c.post(f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{ASSET_BRANCH}", "sha": base["object"]["sha"]})
            if r.status_code not in (201, 422):  # 422: created meanwhile
                r.raise_for_status()
        else:
            ref.raise_for_status()
        path = f"feedback/{rec['screenshot']}"
        r = await c.put(f"/repos/{self.repo}/contents/{path}", json={
            "message": f"Feedback screenshot {rec['id']}", "branch": ASSET_BRANCH,
            "content": base64.b64encode(png.read_bytes()).decode(),
        })
        if r.status_code == 422:  # already uploaded by an earlier attempt
            return f"https://github.com/{self.repo}/blob/{ASSET_BRANCH}/{path}?raw=true"
        r.raise_for_status()
        return f"https://github.com/{self.repo}/blob/{ASSET_BRANCH}/{path}?raw=true"

    async def _ensure_labels(self, c: httpx.AsyncClient, labels: list[str]) -> None:
        colors = {"feedback": "5319E7", "feedback:bug": "D73A4A", "feedback:idea": "0E8A16", "feedback:question": "0075CA"}
        for name in labels:
            r = await c.get(f"/repos/{self.repo}/labels/{name}")
            if r.status_code == 404:
                await c.post(f"/repos/{self.repo}/labels", json={"name": name, "color": colors.get(name, "BFD4F2"), "description": "From the in-app developer feedback dialog"})

    async def _send(self, rec: dict[str, Any], token: str) -> None:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "newcad-engine"}
        async with httpx.AsyncClient(base_url=self.api, headers=headers, timeout=20, transport=self.transport) as c:
            image = None
            if rec.get("screenshot"):
                try:
                    image = await self._upload_png(c, rec)
                except httpx.HTTPError as e:  # the issue matters more than the picture
                    log.warning("feedback screenshot upload failed: %s", e)
            labels = ["feedback", f"feedback:{rec['type'].lower()}"]
            await self._ensure_labels(c, labels)
            r = await c.post(f"/repos/{self.repo}/issues", json={"title": self._title(rec), "body": self._body(rec, image), "labels": labels})
            if r.status_code >= 400:
                raise httpx.HTTPStatusError(f"GitHub answered {r.status_code}: {r.text[:200]}", request=r.request, response=r)
            j = r.json()
            rec.update(status="sent", issue={"number": j["number"], "url": j["html_url"]}, error=None, sent=time.time())

    async def deliver(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Try to file one record as an issue; the record is saved either way."""
        token = await asyncio.to_thread(self.token_source)
        if not token:
            rec.update(status="pending", error="No GitHub token: run `gh auth login` or set NEWCAD_GITHUB_TOKEN")
        else:
            try:
                await self._send(rec, token)
            except (httpx.HTTPError, KeyError, ValueError) as e:
                rec.update(status="pending", error=str(e)[:300])
        self._save(rec)
        return rec

    async def submit(self, type_: str, text: str, context: dict[str, Any] | None, png: bytes | None) -> dict[str, Any]:
        rec = self.create(type_, text, context, png)
        async with self._lock:
            rec = await self.deliver(rec)
        asyncio.get_running_loop().create_task(self.retry_pending(skip=rec["id"]))
        return rec

    async def retry_pending(self, skip: str | None = None) -> int:
        sent = 0
        async with self._lock:
            for rec in self.list():
                if rec.get("status") == "pending" and rec["id"] != skip:
                    rec = await self.deliver(rec)
                    sent += rec["status"] == "sent"
                    if rec["status"] != "sent":
                        break  # GitHub still unreachable; try again later
        return sent
