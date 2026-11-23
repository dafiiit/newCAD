import pytest

from newcad_engine.project.store import BOT, YOU, ProjectStore, StoreError


@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path / "projects", tmp_path / "staging")


def test_create_has_spec_and_demo_parts(store):
    p = store.create("Generator mount", "hold a generator", "demo")
    assert p.id == "generator-mount"
    s = p.summary()
    assert s["head"] == "main" and [x["id"] for x in s["parts"]] == ["plate", "upright", "gusset"]
    spec = p.read_yaml("spec.yaml")
    assert spec["goal"] == "hold a generator"
    assert all(q["answers"] == [] for c in spec["categories"] for q in c["questions"])
    assert store.create("Generator mount").id == "generator-mount-2"


def test_stage_then_commit_on_branch_without_touching_main(store):
    p = store.create("P")
    b = p.create_branch("concept-a")
    p.stage(b, {"parts/x.py": "x = 1\n"})
    assert "parts/x.py" in p.files(b) and "parts/x.py" not in p.files(b, staged=False)
    assert "parts/x.py" not in p.files("main")
    info = p.commit(b, "Add x", BOT)
    assert info.author == "Bot" and info.files == ["parts/x.py"] and info.branch == "concept-a"
    assert p.staged(b) == {}
    assert p.commit(b, "nothing", BOT) is None
    assert "parts/x.py" not in p.files("main")


def test_small_spec_edits_fold_into_one_version(store):
    p = store.create("P")
    n0 = len(p.log())
    p.commit("main", "Spec: answers", YOU, changes={"spec.yaml": "a: 1\n"})
    p.commit("main", "Spec: answers", YOU, changes={"spec.yaml": "a: 2\n"})
    p.commit("main", "Spec: answers", BOT, changes={"spec.yaml": "a: 3\n"})  # other author: new version
    log = p.log()
    assert len(log) == n0 + 2
    assert p.read("spec.yaml") == "a: 3\n"


def test_merge_fast_forward_and_three_way_and_conflict(store):
    p = store.create("P")
    b = p.create_branch("bot/x")
    p.commit(b, "x", BOT, changes={"parts/x.py": "1\n"})
    p.merge(b)  # fast-forward
    assert p.read("parts/x.py", "main") == "1\n"
    c = p.create_branch("concept-c")
    p.commit(c, "c", BOT, changes={"parts/c.py": "c\n"})
    p.commit("main", "m", YOU, changes={"parts/m.py": "m\n"})
    info = p.merge(c)
    assert len(info.parents) == 2 and p.read("parts/c.py") == "c\n" and p.read("parts/m.py") == "m\n"
    d = p.create_branch("concept-d")
    p.commit(d, "d", BOT, changes={"parts/x.py": "from d\n"})
    p.commit("main", "m2", YOU, changes={"parts/x.py": "from main\n"})
    with pytest.raises(StoreError, match="both changed parts/x.py"):
        p.merge(d)


def test_checkout_older_version_detaches_and_blocks_default_writes(store):
    p = store.create("P")
    first = p.log()[0].id
    p.commit("main", "more", YOU, changes={"a.txt": "a\n"})
    assert p.checkout(first) == first
    assert p.head_branch() is None
    with pytest.raises(StoreError, match="create a branch"):
        p.commit(None, "x", YOU, changes={"b.txt": "b\n"})
    assert p.checkout("main") == "main"


def test_log_labels_commits_with_their_branch(store):
    p = store.create("P")
    for name in ("concept-a", "concept-b"):
        b = p.create_branch(name)
        p.commit(b, f"{name} work", BOT, changes={f"parts/{name.replace('-', '_')}.py": "1\n"})
    by_msg = {c.message: c.branch for c in p.log()}
    assert by_msg["concept-a work"] == "concept-a" and by_msg["concept-b work"] == "concept-b"
    assert by_msg["Create project P"] == "main"


def test_invalid_names_are_refused(store):
    p = store.create("P")
    for bad in ("../x", "a..b", "-x", "x.lock"):
        with pytest.raises(StoreError):
            p.create_branch(bad)
    with pytest.raises(StoreError):
        p.stage("main", {"../evil": "x"})
    with pytest.raises(StoreError):
        store.get("../etc")
