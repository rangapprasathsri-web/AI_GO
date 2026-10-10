"""
Engine Isolation Test.

Asserts that core decision engine (backend/engine/) contains zero
dependencies or imports on Firebase Admin, Firebase DB, or Google Cloud.
The engine must remain pure and infrastructure-agnostic.
"""
import ast
from pathlib import Path


def test_engine_has_zero_firebase_imports():
    engine_dir = Path("backend/engine")
    assert engine_dir.exists(), "backend/engine directory must exist"

    forbidden_modules = {"firebase_admin", "firebase", "google", "backend.storage"}

    violations = []
    for py_file in engine_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".")[0]
                    if alias.name in forbidden_modules or root_name in forbidden_modules:
                        violations.append(f"{py_file}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_name = node.module.split(".")[0]
                    if node.module in forbidden_modules or root_name in forbidden_modules:
                        violations.append(f"{py_file}: from {node.module} import ...")

    assert not violations, f"Engine architectural boundary violated! Forbidden imports found:\n" + "\n".join(violations)
