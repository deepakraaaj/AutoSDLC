from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.repo_intelligence import index_repository
from app.services.security.related_code import find_security_context


def test_finds_authentication_pattern(tmp_path):
    (tmp_path / "app.py").write_text(
        "from flask_login import login_required\n\n"
        "@login_required\n"
        "def view():\n"
        "    pass\n",
    )
    matches = find_security_context(tmp_path)
    assert any(m.category == "AUTHENTICATION" and m.file == "app.py" for m in matches)


def test_finds_database_pattern(tmp_path):
    (tmp_path / "repository.py").write_text(
        "def find_by_id(conn, id):\n"
        "    conn.execute('SELECT * FROM users WHERE id = ' + str(id))\n",
    )
    matches = find_security_context(tmp_path)
    assert any(m.category == "DATABASE" and m.file == "repository.py" for m in matches)


def test_finds_external_http_pattern(tmp_path):
    (tmp_path / "client.py").write_text(
        "def call_out(url):\n"
        "    return requests.get(url)\n",
    )
    matches = find_security_context(tmp_path)
    assert any(m.category == "EXTERNAL_HTTP" for m in matches)


def test_finds_filesystem_pattern(tmp_path):
    (tmp_path / "io_utils.py").write_text(
        "def read(path):\n"
        "    return open(path).read()\n",
    )
    matches = find_security_context(tmp_path)
    assert any(m.category == "FILESYSTEM" for m in matches)


def test_finds_command_execution_pattern(tmp_path):
    (tmp_path / "runner.py").write_text(
        "import subprocess\n\n"
        "def run(cmd):\n"
        "    subprocess.run(cmd)\n",
    )
    matches = find_security_context(tmp_path)
    assert any(m.category == "COMMAND_EXECUTION" for m in matches)


def test_finds_authorization_pattern_in_java(tmp_path):
    (tmp_path / "Controller.java").write_text(
        "public class Controller {\n"
        "  public void get() {\n"
        "    permissionService.checkPermission(user, \"read\");\n"
        "  }\n"
        "}\n",
    )
    matches = find_security_context(tmp_path)
    assert any(m.category == "AUTHORIZATION" and m.language == "java" for m in matches)


def test_ignores_vendored_and_binary_noise_and_bounds_output(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("subprocess.exec('rm -rf /')\n")
    (tmp_path / "app.js").write_text("fetch('http://x')\n")
    matches = find_security_context(tmp_path)
    assert all(m.file != "node_modules/lib.js" for m in matches)
    assert any(m.file == "app.js" for m in matches)


def test_attributes_match_to_nearest_enclosing_symbol_when_index_given(tmp_path):
    (tmp_path / "app.py").write_text(
        "def get_user(id):\n"
        "    conn.execute('SELECT 1')\n",
    )
    index = index_repository(tmp_path, "commit-security-context")
    matches = find_security_context(tmp_path, index=index)
    database_match = next(m for m in matches if m.category == "DATABASE")
    assert database_match.symbol == "get_user"


def test_returns_empty_list_for_empty_repository(tmp_path):
    assert find_security_context(tmp_path) == []
