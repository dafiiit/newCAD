"""Git-backed project store.

One bare git repository per project. Writes build commits straight from git
objects (no working tree), so several branches can be edited at the same
time, for example the three concept branches BuilderBot builds in parallel.

Files in a project:
  project.yaml   name, goal, created, per-project Bot settings
  assembly.yaml  parts list: id, name, file, colour, material
  parts/*.py     build123d source, one file per part
  spec.yaml      the What? sheet: categories, questions, answers
  notes.yaml     3D comments with face tags

HEAD is the user's current version. It points at a branch, or at a commit
when the user checked out an older version.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import pygit2
import yaml
from pygit2.enums import FileMode, SortMode

from .templates import new_project_files

BOT = ("Bot", "bot@newcad.local")
YOU = ("You", "you@newcad.local")

# Small edits to these files (and studies/*.yaml) by the same author are folded into one commit,
# so answering ten questions doesn't produce ten versions.
COALESCE_FILES = {"spec.yaml", "notes.yaml"}
COALESCE_SECONDS = 15 * 60


class StoreError(Exception):
    """A request the store refuses, with a message meant for the caller."""


def slugify(text: str, fallback: str = "project") -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:40] or fallback


def valid_branch(name: str) -> str:
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}", name) or ".." in name or name.endswith((".lock", "/")):
        raise StoreError(f"Invalid branch name: {name!r}")
    return name


def valid_part_id(pid: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", pid):
        raise StoreError(f"Invalid part id {pid!r}: use lower-case letters, digits and _ and start with a letter")
    return pid


@dataclass
class CommitInfo:
    id: str
    short: str
    branch: str
    parents: list[str]
    message: str
    author: str
    time: int
    files: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "short": self.short, "branch": self.branch, "parents": self.parents, "message": self.message,
            "author": self.author, "time": self.time, "files": self.files,
        }


class Project:
    def __init__(self, store: "ProjectStore", pid: str, path: Path):
        self.store = store
        self.id = pid
        self.path = path
        self.repo = pygit2.Repository(str(path))
        self.lock = threading.RLock()

    # ---------- refs ----------

    def head_ref(self) -> str:
        """Branch name HEAD points to, or the commit id when detached."""
        if self.repo.head_is_detached:
            return str(self.repo.head.target)
        return self.repo.head.shorthand

    def head_branch(self) -> str | None:
        return None if self.repo.head_is_detached else self.repo.head.shorthand

    def branches(self) -> list[str]:
        return sorted(self.repo.branches.local)

    def resolve(self, ref: str | None) -> pygit2.Commit:
        ref = ref or "HEAD"
        try:
            if ref == "HEAD":
                return self.repo.head.peel(pygit2.Commit)
            if ref in self.repo.branches.local:
                return self.repo.branches.local[ref].peel(pygit2.Commit)
            obj = self.repo.revparse_single(ref)
            return obj.peel(pygit2.Commit)
        except (KeyError, ValueError, pygit2.GitError) as e:
            raise StoreError(f"Unknown version or branch: {ref}") from e

    def is_branch(self, ref: str | None) -> bool:
        return bool(ref) and ref in self.repo.branches.local

    # ---------- reading ----------

    def _tree_files(self, tree: pygit2.Tree, prefix: str = "") -> dict[str, pygit2.Oid]:
        out: dict[str, pygit2.Oid] = {}
        for e in tree:
            p = f"{prefix}{e.name}"
            if e.type_str == "tree":
                out.update(self._tree_files(self.repo[e.id], p + "/"))
            else:
                out[p] = e.id
        return out

    def files(self, ref: str | None = None, staged: bool = True) -> dict[str, str]:
        """All files at a version as text. For a branch, staged edits are laid on top."""
        c = self.resolve(ref)
        out = {p: self.repo[oid].data.decode("utf-8") for p, oid in self._tree_files(c.tree).items()}
        if staged and (ref is None or ref == "HEAD" or self.is_branch(ref)):
            branch = self.head_branch() if ref in (None, "HEAD") else ref
            if branch:
                for p, content in self.store.staging.get(self.id, branch).items():
                    if content is None:
                        out.pop(p, None)
                    else:
                        out[p] = content
        return out

    def read(self, path: str, ref: str | None = None, staged: bool = True) -> str | None:
        return self.files(ref, staged).get(path)

    def read_yaml(self, path: str, ref: str | None = None, staged: bool = True) -> Any:
        txt = self.read(path, ref, staged)
        return yaml.safe_load(txt) if txt else None

    def meta(self, ref: str | None = None) -> dict[str, Any]:
        return self.read_yaml("project.yaml", ref) or {}

    def assembly(self, ref: str | None = None) -> dict[str, Any]:
        a = self.read_yaml("assembly.yaml", ref) or {}
        a.setdefault("parts", [])
        return a

    # ---------- writing ----------

    def _branch_for_write(self, branch: str | None) -> str:
        if branch in (None, "HEAD"):
            b = self.head_branch()
            if not b:
                raise StoreError("HEAD is on an older version; create a branch from it before editing")
            return b
        return valid_branch(branch)

    def stage(self, branch: str | None, changes: dict[str, str | None]) -> str:
        """Stage edits on a branch without committing. Returns the branch name."""
        b = self._branch_for_write(branch)
        if b not in self.repo.branches.local:
            raise StoreError(f"No branch named {b}")
        for p in changes:
            _check_path(p)
        self.store.staging.update(self.id, b, changes)
        self.store.notify(self.id, "staged", branch=b)
        return b

    def staged(self, branch: str | None) -> dict[str, str | None]:
        b = self._branch_for_write(branch)
        return self.store.staging.get(self.id, b)

    def commit(self, branch: str | None, message: str, author: tuple[str, str] = YOU,
               changes: dict[str, str | None] | None = None, include_staged: bool = True) -> CommitInfo | None:
        """Commit staged edits plus `changes` on a branch. Returns None when nothing changed."""
        with self.lock:
            b = self._branch_for_write(branch)
            if b not in self.repo.branches.local:
                raise StoreError(f"No branch named {b}")
            all_changes: dict[str, str | None] = {}
            if include_staged:
                all_changes.update(self.store.staging.get(self.id, b))
            all_changes.update(changes or {})
            for p in all_changes:
                _check_path(p)
            parent = self.repo.branches.local[b].peel(pygit2.Commit)
            files = self._tree_files(parent.tree)
            touched: list[str] = []
            for p, content in all_changes.items():
                if content is None:
                    if p in files:
                        files.pop(p)
                        touched.append(p)
                    continue
                oid = self.repo.create_blob(content.encode("utf-8"))
                if files.get(p) != oid:
                    files[p] = oid
                    touched.append(p)
            if include_staged:
                self.store.staging.clear(self.id, b)
            if not touched:
                return None
            tree = self._build_tree(files)
            parents = [parent.id]
            # fold small spec/notes edits into the previous commit of the same kind
            if _soft(touched) and _coalescible(parent, author, touched):
                parents = [p.id for p in parent.parents]
                message = parent.message.strip()
            sig = pygit2.Signature(author[0], author[1])
            msg = message.strip() + "\n"
            if _soft(touched):
                msg += f"\nNewcad-Edit: {','.join(sorted(touched))}\n"
            oid = self.repo.create_commit(None, sig, sig, msg, tree, parents)
            self.repo.branches.local[b].set_target(oid)
            info = self.commit_info(self.repo[oid], b)
        self.store.notify(self.id, "commit", branch=b, commit=str(oid))
        return info

    def _build_tree(self, files: dict[str, pygit2.Oid]) -> pygit2.Oid:
        nested: dict[str, Any] = {}
        for p, oid in files.items():
            node = nested
            parts = p.split("/")
            for d in parts[:-1]:
                node = node.setdefault(d, {})
            node[parts[-1]] = oid

        def write(node: dict[str, Any]) -> pygit2.Oid:
            tb = self.repo.TreeBuilder()
            for name, v in sorted(node.items()):
                if isinstance(v, dict):
                    tb.insert(name, write(v), FileMode.TREE)
                else:
                    tb.insert(name, v, FileMode.BLOB)
            return tb.write()

        return write(nested)

    # ---------- branches and versions ----------

    def create_branch(self, name: str, from_ref: str | None = None, unique: bool = False) -> str:
        with self.lock:
            name = valid_branch(name)
            if unique:
                base, n = name, 2
                while name in self.repo.branches.local:
                    name = f"{base}-{n}"
                    n += 1
            elif name in self.repo.branches.local:
                raise StoreError(f"Branch {name} already exists")
            c = self.resolve(from_ref)
            self.repo.branches.local.create(name, c)
        self.store.notify(self.id, "branch", branch=name)
        return name

    def checkout(self, ref: str) -> str:
        """Move HEAD to a branch (or a commit, detached). Only the user does this."""
        with self.lock:
            if self.is_branch(ref):
                self.repo.set_head(f"refs/heads/{ref}")
            else:
                c = self.resolve(ref)
                tip_of = [b for b in self.branches() if self.repo.branches.local[b].target == c.id]
                if tip_of:
                    pref = self.head_branch() if self.head_branch() in tip_of else ("main" if "main" in tip_of else tip_of[0])
                    self.repo.set_head(f"refs/heads/{pref}")
                else:
                    self.repo.set_head(c.id)
        self.store.notify(self.id, "checkout", head=self.head_ref())
        return self.head_ref()

    def merge(self, source: str, into: str | None = None, author: tuple[str, str] = YOU) -> CommitInfo:
        """Bring a branch into another (default: the user's current branch). Fast-forward when possible."""
        with self.lock:
            target = self._branch_for_write(into)
            if not self.is_branch(source):
                raise StoreError(f"No branch named {source}")
            if self.store.staging.get(self.id, target):
                raise StoreError(f"{target} has uncommitted changes; commit them first")
            ours = self.repo.branches.local[target].peel(pygit2.Commit)
            theirs = self.repo.branches.local[source].peel(pygit2.Commit)
            if ours.id == theirs.id or self.repo.descendant_of(ours.id, theirs.id):
                return self.commit_info(ours, target)
            if self.repo.descendant_of(theirs.id, ours.id):
                self.repo.branches.local[target].set_target(theirs.id)
                oid = theirs.id
            else:
                idx = self.repo.merge_commits(ours, theirs)
                if idx.conflicts is not None:
                    paths = sorted({(c[0] or c[1] or c[2]).path for c in idx.conflicts})
                    raise StoreError(f"{source} and {target} both changed {', '.join(paths)}; check out {source} instead, or ask Bot to redo it on {target}")
                tree = idx.write_tree(self.repo)
                sig = pygit2.Signature(*author)
                oid = self.repo.create_commit(None, sig, sig, f"Apply {source} to {target}\n", tree, [ours.id, theirs.id])
                self.repo.branches.local[target].set_target(oid)
            info = self.commit_info(self.repo[oid], target)
        self.store.notify(self.id, "commit", branch=target, commit=str(oid))
        return info

    def delete_branch(self, name: str) -> None:
        with self.lock:
            if name == self.head_branch():
                raise StoreError("Can't delete the branch you have checked out")
            if name not in self.repo.branches.local:
                raise StoreError(f"No branch named {name}")
            self.repo.branches.local.delete(name)
            self.store.staging.clear(self.id, name)
        self.store.notify(self.id, "branch", branch=name)

    def commit_info(self, c: pygit2.Commit, branch: str = "") -> CommitInfo:
        files: list[str] = []
        if c.parents:
            diff = self.repo.diff(c.parents[0], c)
            files = [d.delta.new_file.path for d in diff]
        else:
            files = sorted(self._tree_files(c.tree))
        msg = c.message.split("\nNewcad-Edit:")[0].strip()
        return CommitInfo(str(c.id), str(c.id)[:7], branch, [str(p) for p in c.parent_ids], msg, c.author.name, c.commit_time, files)

    def log(self, limit: int = 300) -> list[CommitInfo]:
        """Every commit on every branch, oldest first. Each commit is labelled with the branch that
        introduced it: main claims its first-parent line first, then the other branches."""
        owner: dict[pygit2.Oid, str] = {}
        order = sorted(self.branches(), key=lambda b: (b != "main", b))
        for b in order:
            c = self.repo.branches.local[b].peel(pygit2.Commit)
            while c is not None and c.id not in owner:
                owner[c.id] = b
                c = c.parents[0] if c.parents else None
        walker = self.repo.walk(None, SortMode.TOPOLOGICAL | SortMode.TIME)
        for b in self.branches():
            walker.push(self.repo.branches.local[b].target)
        if self.repo.head_is_detached:
            walker.push(self.repo.head.target)
        out = []
        for c in walker:
            out.append(self.commit_info(c, owner.get(c.id, self.head_branch() or "main")))
            if len(out) >= limit:
                break
        return list(reversed(out))

    def tips(self) -> dict[str, str]:
        return {b: str(self.repo.branches.local[b].target) for b in self.branches()}

    def diff(self, a: str, b: str) -> list[dict[str, Any]]:
        fa, fb = self.files(a, staged=False), self.files(b, staged=False)
        out = []
        for p in sorted(set(fa) | set(fb)):
            if fa.get(p) == fb.get(p):
                continue
            ud = difflib.unified_diff((fa.get(p) or "").splitlines(), (fb.get(p) or "").splitlines(), f"a/{p}", f"b/{p}", lineterm="", n=2)
            out.append({"path": p, "status": "added" if p not in fa else "deleted" if p not in fb else "modified", "diff": "\n".join(ud)})
        return out

    def summary(self) -> dict[str, Any]:
        m = self.meta()
        head = self.resolve("HEAD")
        asm = self.assembly()
        return {
            "id": self.id, "name": m.get("name", self.id), "goal": m.get("goal", ""), "created": m.get("created"),
            "head": self.head_ref(), "headCommit": str(head.id), "branches": self.branches(),
            "parts": [{"id": p["id"], "name": p.get("name", p["id"])} for p in asm["parts"]],
            "updated": head.commit_time,
        }


def _check_path(p: str) -> None:
    if p.startswith("/") or ".." in p.split("/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", p):
        raise StoreError(f"Invalid file path {p!r}")


def _soft(paths: Iterable[str]) -> bool:
    """Small setup files whose edits fold into one version: the spec, notes and study files."""
    return all(p in COALESCE_FILES or (p.startswith("studies/") and p.endswith(".yaml")) for p in paths)


def _coalescible(c: pygit2.Commit, author: tuple[str, str], touched: Iterable[str]) -> bool:
    if c.author.name != author[0] or len(c.parents) != 1:
        return False
    if time.time() - c.commit_time > COALESCE_SECONDS:
        return False
    m = re.search(r"\nNewcad-Edit: ([^\n]+)", c.message)
    return bool(m) and set(touched) <= set(m.group(1).split(","))


class Staging:
    """Uncommitted edits per (project, branch), kept on disk so they survive restarts."""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()

    def _file(self, pid: str, branch: str) -> Path:
        return self.root / pid / (branch.replace("/", "__") + ".json")

    def get(self, pid: str, branch: str) -> dict[str, str | None]:
        f = self._file(pid, branch)
        with self.lock:
            return json.loads(f.read_text()) if f.exists() else {}

    def update(self, pid: str, branch: str, changes: dict[str, str | None]) -> None:
        f = self._file(pid, branch)
        with self.lock:
            cur = json.loads(f.read_text()) if f.exists() else {}
            cur.update(changes)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(cur))

    def clear(self, pid: str, branch: str) -> None:
        with self.lock:
            self._file(pid, branch).unlink(missing_ok=True)


Listener = Callable[[str, str, dict[str, Any]], None]


class ProjectStore:
    def __init__(self, root: Path, staging_root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging = Staging(staging_root)
        self._open: dict[str, Project] = {}
        self._lock = threading.Lock()
        self.listeners: list[Listener] = []

    def notify(self, pid: str, kind: str, **data: Any) -> None:
        for fn in list(self.listeners):
            try:
                fn(pid, kind, data)
            except Exception:  # a broken listener must not break a write
                pass

    def list(self) -> list[dict[str, Any]]:
        out = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and (d / "HEAD").exists():
                try:
                    out.append(self.get(d.name).summary())
                except Exception:
                    continue
        return sorted(out, key=lambda s: -s["updated"])

    def get(self, pid: str) -> Project:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", pid or ""):
            raise StoreError(f"No project {pid!r}")
        with self._lock:
            if pid not in self._open:
                path = self.root / pid
                if not (path / "HEAD").exists():
                    raise StoreError(f"No project {pid!r}")
                self._open[pid] = Project(self, pid, path)
            return self._open[pid]

    def create(self, name: str, goal: str = "", template: str = "blank", author: tuple[str, str] = YOU) -> Project:
        base = slugify(name)
        pid, n = base, 2
        with self._lock:
            while (self.root / pid).exists():
                pid = f"{base}-{n}"
                n += 1
            repo = pygit2.init_repository(str(self.root / pid), bare=True, initial_head="main")
            files = new_project_files(name, goal, template)
            tb_files = {p: repo.create_blob(c.encode()) for p, c in files.items()}
        proj = Project(self, pid, self.root / pid)
        tree = proj._build_tree(tb_files)
        sig = pygit2.Signature(*author)
        repo.create_commit("refs/heads/main", sig, sig, f"Create project {name}\n", tree, [])
        with self._lock:
            self._open[pid] = proj
        self.notify(pid, "created")
        return proj
