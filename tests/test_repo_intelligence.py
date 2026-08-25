from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.repo_intelligence import (
    get_callees,
    get_callers,
    get_related_symbols,
    index_repository,
    intelligence_prompt,
    symbol_id,
)


def test_indexes_python_types_routes_models_and_imports(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(
        "from fastapi import FastAPI\n"
        "from pydantic import BaseModel\n"
        "app = FastAPI()\n\n"
        "class User(BaseModel):\n    name: str\n\n"
        "@app.get('/users')\nasync def list_users():\n    return []\n",
    )
    index = index_repository(tmp_path, "commit-1")

    assert any(item.kind == "data_model" and item.name == "User" and item.line == 5 for item in index.symbols)
    assert any(item.kind == "api_route" and item.name == "list_users" and item.line == 9 for item in index.symbols)
    assert any(item.kind == "imports" and item.target == "fastapi" for item in index.relations)
    assert "`app.py:9`" in index.artifacts["api-reference.md"]
    assert "source citations" in intelligence_prompt(index)


def test_indexes_typescript_symbols_routes_and_imports(tmp_path):
    source = tmp_path / "src" / "server.ts"
    source.parent.mkdir()
    source.write_text(
        "import express from 'express'\n"
        "export interface User { name: string }\n"
        "export const health = () => 'ok'\n"
        "router.get('/health', health)\n",
    )
    index = index_repository(tmp_path, "commit-2")

    assert {item.name for item in index.symbols} >= {"User", "health", "GET /health"}
    assert any(item.target == "express" for item in index.relations)
    assert "src/server.ts:4" in index.artifacts["api-reference.md"]


def test_excludes_vendored_bundles_from_product_evidence(tmp_path):
    vendor = tmp_path / "src" / "asset" / "js" / "bootstrap.bundle.js"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("function Carousel() {}\nfunction PatientMap() {}\n")
    app = tmp_path / "src" / "App.js"
    app.write_text("export function LogisticsDashboard() {}\n")

    index = index_repository(tmp_path, "commit-vendor")

    assert "src/asset/js/bootstrap.bundle.js" not in {item["path"] for item in index.files}
    assert {item.name for item in index.symbols} == {"LogisticsDashboard"}


def test_indexes_java_models_routes_and_imports(tmp_path):
    source = tmp_path / "src" / "main" / "java" / "app" / "model" / "Device.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package app.model;\nimport jakarta.persistence.Entity;\n"
        "public class Device {}\n@GetMapping(\"/devices\")\npublic void list() {}\n"
    )

    index = index_repository(tmp_path, "commit-java")

    assert any(item.name == "Device" and item.kind == "data_model" for item in index.symbols)
    assert any(item.name == "GET /devices" and item.kind == "api_route" for item in index.symbols)
    assert any(item.target == "jakarta.persistence.Entity" for item in index.relations)


# ── calls / cross-file resolution (INDEX_VERSION 3) ─────────────────────────

def _write_controller_service_repository(tmp_path):
    (tmp_path / "controller.py").write_text(
        "from service import UserService\n\n"
        "class UserController:\n"
        "    def __init__(self):\n"
        "        self.service = UserService()\n"
        "    def get(self, user_id):\n"
        "        return self.service.get_user(user_id)\n",
    )
    (tmp_path / "service.py").write_text(
        "from repository import UserRepository\n\n"
        "class UserService:\n"
        "    def __init__(self):\n"
        "        self.repository = UserRepository()\n"
        "    def get_user(self, user_id):\n"
        "        return self.repository.find_by_id(user_id)\n",
    )
    (tmp_path / "repository.py").write_text(
        "class UserRepository:\n"
        "    def find_by_id(self, user_id):\n"
        "        return requests.get('http://x')\n",
    )


def test_python_calls_chain_controller_service_repository(tmp_path):
    _write_controller_service_repository(tmp_path)
    index = index_repository(tmp_path, "commit-calls")

    calls = [item for item in index.relations if item.kind == "calls"]
    controller_to_service = next(item for item in calls if item.path == "controller.py" and item.line == 7)
    assert controller_to_service.target_name == "get_user"
    assert controller_to_service.resolved is True
    service_to_repository = next(item for item in calls if item.path == "service.py" and item.line == 7)
    assert service_to_repository.target_name == "find_by_id"
    assert service_to_repository.resolved is True

    # Not thrown away just because it can't be resolved to an indexed symbol
    # (requests.get is an external library, not something we index).
    unresolved_external = next(item for item in calls if item.target == "requests.get")
    assert unresolved_external.resolved is False


def test_cross_file_resolution_links_to_the_correct_indexed_symbol(tmp_path):
    _write_controller_service_repository(tmp_path)
    index = index_repository(tmp_path, "commit-resolution")

    controller_call = next(
        item for item in index.relations
        if item.kind == "calls" and item.path == "controller.py" and item.target_name == "get_user"
    )
    resolved_symbol = next(item for item in index.symbols if f"{item.path}::{item.name}@{item.line}" == controller_call.resolved_target)
    assert resolved_symbol.path == "service.py"
    assert resolved_symbol.name == "get_user"
    assert resolved_symbol.parent == "UserService"


def test_ambiguous_call_target_stays_unresolved_rather_than_guessing(tmp_path):
    # Two unrelated classes both define a same-named method with no type
    # hint connecting the caller to either one — resolve_relations must not
    # pick a winner.
    (tmp_path / "a.py").write_text("class Left:\n    def process(self):\n        pass\n")
    (tmp_path / "b.py").write_text("class Right:\n    def process(self):\n        pass\n")
    (tmp_path / "caller.py").write_text("def run(thing):\n    thing.process()\n")

    index = index_repository(tmp_path, "commit-ambiguous")
    call = next(item for item in index.relations if item.kind == "calls" and item.target_name == "process")
    assert call.resolved is False
    assert call.resolved_target is None
    # The raw call is still present, just unresolved.
    assert call.target == "thing.process"


def test_indexes_java_calls_controller_to_service(tmp_path):
    (tmp_path / "UserController.java").write_text(
        "package app;\nimport app.UserService;\n"
        "public class UserController {\n"
        "  private UserService userService;\n"
        "  @GetMapping(\"/users\")\n"
        "  public void get() { userService.getUser(1); }\n"
        "}\n",
    )
    (tmp_path / "UserService.java").write_text(
        "package app;\n"
        "public class UserService {\n"
        "  public void getUser(int id) { repository.findById(id); }\n"
        "}\n",
    )
    index = index_repository(tmp_path, "commit-java-calls")
    calls = [item for item in index.relations if item.kind == "calls"]
    controller_call = next(item for item in calls if item.path == "UserController.java")
    assert controller_call.target_name == "getUser"
    assert controller_call.target_object == "userService"
    # No per-method Java symbols exist yet (see repo_intelligence.py's
    # module docstring) — resolution falls back to class granularity.
    assert controller_call.resolved is True
    resolved_symbol = next(item for item in index.symbols if f"{item.path}::{item.name}@{item.line}" == controller_call.resolved_target)
    assert resolved_symbol.name == "UserService"


def test_indexes_typescript_calls_route_to_service(tmp_path):
    (tmp_path / "route.ts").write_text(
        "import { userService } from './service'\n"
        "router.get('/users/:id', function getUser(req, res) {\n"
        "  const result = userService.fetchUser(req.params.id)\n"
        "  res.json(result)\n"
        "})\n",
    )
    index = index_repository(tmp_path, "commit-ts-calls")
    calls = [item for item in index.relations if item.kind == "calls"]
    assert any(item.target == "userService.fetchUser" and item.target_name == "fetchUser" and item.target_object == "userService" for item in calls)
    # Regex-based extraction doesn't throw the call away just because it
    # can't attribute it to a precise enclosing scope.
    assert any(item.target == "userService.fetchUser" for item in calls)


def test_get_callers_and_get_callees(tmp_path):
    _write_controller_service_repository(tmp_path)
    index = index_repository(tmp_path, "commit-callers-callees")

    service_get_user = next(item for item in index.symbols if item.name == "get_user" and item.path == "service.py")
    sid = symbol_id(service_get_user)

    callers = get_callers(index, sid)
    assert len(callers) == 1
    assert callers[0].path == "controller.py"

    callees = get_callees(index, sid)
    assert any(item.target_name == "find_by_id" for item in callees)

    related = get_related_symbols(index, sid)
    related_names = {item.name for item in related}
    assert "get" in related_names  # caller (UserController.get)
    assert "find_by_id" in related_names  # callee (UserRepository.find_by_id)
    assert "UserRepository" in related_names  # via same-file import
