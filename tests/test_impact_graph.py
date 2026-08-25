from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.repo_intelligence import index_repository, symbol_id
from app.services.security.related_code import find_security_context
from app.services.security.impact_graph import build_impact_graph, enrich_with_security_context


def _symbol(index, name, path):
    return next(item for item in index.symbols if item.name == name and item.path == path)


def test_impact_graph_follows_a_to_b_to_c_chain(tmp_path):
    (tmp_path / "a.py").write_text(
        "from b import B\n\n"
        "class A:\n"
        "    def __init__(self):\n"
        "        self.b = B()\n"
        "    def run(self):\n"
        "        self.b.step()\n",
    )
    (tmp_path / "b.py").write_text(
        "from c import C\n\n"
        "class B:\n"
        "    def __init__(self):\n"
        "        self.c = C()\n"
        "    def step(self):\n"
        "        self.c.finish()\n",
    )
    (tmp_path / "c.py").write_text(
        "class C:\n"
        "    def finish(self):\n"
        "        pass\n",
    )
    index = index_repository(tmp_path, "commit-chain")
    seed = symbol_id(_symbol(index, "run", "a.py"))

    graph = build_impact_graph(index, [seed], max_depth=3, max_nodes=50, max_files=20)
    names = {node.name for node in graph.nodes.values()}
    assert names == {"run", "step", "finish"}
    assert graph.truncated is False
    assert any(edge.kind == "calls" for edge in graph.edges)
    assert any(edge.kind == "called_by" for edge in graph.edges)


def test_impact_graph_respects_max_depth(tmp_path):
    (tmp_path / "a.py").write_text(
        "from b import B\n\n"
        "class A:\n"
        "    def __init__(self):\n"
        "        self.b = B()\n"
        "    def run(self):\n"
        "        self.b.step()\n",
    )
    (tmp_path / "b.py").write_text(
        "from c import C\n\n"
        "class B:\n"
        "    def __init__(self):\n"
        "        self.c = C()\n"
        "    def step(self):\n"
        "        self.c.finish()\n",
    )
    (tmp_path / "c.py").write_text(
        "class C:\n"
        "    def finish(self):\n"
        "        pass\n",
    )
    index = index_repository(tmp_path, "commit-depth")
    seed = symbol_id(_symbol(index, "run", "a.py"))

    graph = build_impact_graph(index, [seed], max_depth=1, max_nodes=50, max_files=20)
    names = {node.name for node in graph.nodes.values()}
    # depth 0 = run, depth 1 = step (its direct callee) — "finish" is two
    # hops away and must not be reached with max_depth=1.
    assert names == {"run", "step"}


def test_impact_graph_terminates_on_a_cycle(tmp_path):
    (tmp_path / "a.py").write_text(
        "from b import B\n\n"
        "class A:\n"
        "    def __init__(self):\n"
        "        self.b = B()\n"
        "    def one(self):\n"
        "        self.b.two()\n",
    )
    (tmp_path / "b.py").write_text(
        "from c import C\n\n"
        "class B:\n"
        "    def __init__(self):\n"
        "        self.c = C()\n"
        "    def two(self):\n"
        "        self.c.three()\n",
    )
    (tmp_path / "c.py").write_text(
        "from a import A\n\n"
        "class C:\n"
        "    def __init__(self):\n"
        "        self.a = A()\n"
        "    def three(self):\n"
        "        self.a.one()\n",
    )
    index = index_repository(tmp_path, "commit-cycle")
    seed = symbol_id(_symbol(index, "one", "a.py"))

    # A -> B -> C -> A. Must terminate (not hang/recurse forever) and must
    # not visit "one" twice just because the cycle loops back to it.
    graph = build_impact_graph(index, [seed], max_depth=5, max_nodes=50, max_files=20)
    names = [node.name for node in graph.nodes.values()]
    assert sorted(names) == ["one", "three", "two"]
    assert len(names) == len(set(names))


def test_impact_graph_respects_max_nodes(tmp_path):
    (tmp_path / "a.py").write_text(
        "from b import B\n\n"
        "class A:\n"
        "    def __init__(self):\n"
        "        self.b = B()\n"
        "    def run(self):\n"
        "        self.b.step()\n",
    )
    (tmp_path / "b.py").write_text(
        "from c import C\n\n"
        "class B:\n"
        "    def __init__(self):\n"
        "        self.c = C()\n"
        "    def step(self):\n"
        "        self.c.finish()\n",
    )
    (tmp_path / "c.py").write_text(
        "class C:\n"
        "    def finish(self):\n"
        "        pass\n",
    )
    index = index_repository(tmp_path, "commit-max-nodes")
    seed = symbol_id(_symbol(index, "run", "a.py"))

    graph = build_impact_graph(index, [seed], max_depth=5, max_nodes=1, max_files=20)
    assert len(graph.nodes) <= 1
    assert graph.truncated is True


def test_enrich_with_security_context_tags_matching_nodes(tmp_path):
    (tmp_path / "controller.py").write_text(
        "from service import Service\n\n"
        "class Controller:\n"
        "    def __init__(self):\n"
        "        self.service = Service()\n"
        "    def handle(self):\n"
        "        self.service.query_data()\n",
    )
    (tmp_path / "service.py").write_text(
        "class Service:\n"
        "    def query_data(self):\n"
        "        conn.execute('SELECT 1')\n",
    )
    index = index_repository(tmp_path, "commit-enrich")
    seed = symbol_id(_symbol(index, "handle", "controller.py"))
    graph = build_impact_graph(index, [seed], max_depth=3, max_nodes=20, max_files=10)
    matches = find_security_context(tmp_path, index=index)

    enrich_with_security_context(graph, matches)
    tagged = {node.name: node.tags for node in graph.nodes.values() if node.tags}
    assert "DATABASE" in tagged.get("query_data", set())
