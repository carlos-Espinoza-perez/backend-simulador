import os
import sys
import json
import urllib.request
import jedi
from typing import List, Dict, Any, Optional

class CompletionService:
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project = jedi.Project(
            path=self.workspace_root,
            added_sys_path=[self.workspace_root, self.backend_dir]
        )

    def get_completions(self, code: str, line: int, column: int, filename: str = "main.py") -> List[Dict[str, Any]]:
        try:
            abs_path = os.path.join(self.workspace_root, filename)
            script = jedi.Script(code=code, path=abs_path, project=self.project)
            jedi_completions = script.complete(line, column)
            
            results = []
            for c in jedi_completions:
                type_name = c.type
                kind_map = {
                    "module": 8,
                    "class": 6,
                    "instance": 5,
                    "function": 2,
                    "param": 5,
                    "statement": 5,
                    "keyword": 13,
                    "property": 9
                }
                monaco_kind = kind_map.get(type_name, 5)

                doc = ""
                try:
                    doc = c.docstring(fast=True)
                except Exception:
                    pass

                results.append({
                    "label": c.name,
                    "kind": monaco_kind,
                    "detail": f"({type_name}) {c.description}",
                    "documentation": doc,
                    "insertText": c.complete or c.name,
                    "type": type_name
                })

            lines = code.split("\n")
            if 0 < line <= len(lines):
                prefix = lines[line - 1][:column]
                is_di = "get_di" in prefix or "di_" in prefix
                is_do = "get_do" in prefix or "set_do" in prefix or "do_" in prefix
                if is_di or is_do:
                    signals = []
                    io_file = os.path.join(self.workspace_root, "virtual_io.json")
                    if os.path.isfile(io_file):
                        try:
                            with open(io_file, "r", encoding="utf-8") as f:
                                signals = json.load(f)
                        except Exception:
                            pass
                    if not signals:
                        from robot_connection.virtual_io_manager import DEFAULT_SIGNALS
                        signals = DEFAULT_SIGNALS

                    for s in signals:
                        stype = s.get("type", "")
                        sname = s.get("name", "")
                        sdesc = s.get("description", "")
                        sval = s.get("value", 0)

                        if is_di and stype != "DI" and not is_do:
                            continue
                        if is_do and stype != "DO" and not is_di:
                            continue

                        results.append({
                            "label": sname,
                            "kind": 5,
                            "detail": f"[{stype}] {sdesc} (Valor: {sval})",
                            "documentation": f"Señal {stype} en celda robótica.\n{sdesc}\nEstado: {sval}",
                            "insertText": sname,
                            "type": stype
                        })

            return results
        except Exception:
            return []

    def get_ai_completion(self, code_before_cursor: str, code_after_cursor: str = "") -> Optional[str]:
        config_path = os.path.join(self.workspace_root, "config.json")
        ai_config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    ai_config = json.load(f).get("ai_completion", {})
            except Exception:
                pass

        provider = ai_config.get("provider", "").lower()
        if provider == "ollama":
            url = ai_config.get("endpoint", "http://localhost:11434/api/generate")
            model = ai_config.get("model", "codellama")
            prompt = f"Complete the following Python code directly with only code, no markdown:\n{code_before_cursor}"
            try:
                payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("response", "").strip()
            except Exception:
                pass

        last_line = code_before_cursor.split("\n")[-1] if code_before_cursor else ""
        stripped = last_line.strip()

        if stripped == "robot." or stripped.endswith("robot."):
            return "connect(timeout=2.0)"
        if stripped == "if res.get(\"success\"):" or stripped.endswith("res.get(\"success\"):"):
            return "\n        print(\"Ping:\", robot.ping())\n        print(\"Estado:\", robot.get_status())"
        if stripped.startswith("def mover_a_posicion(") and stripped.endswith(":"):
            return "\n    \"\"\"Mueve el efector a las coordenadas especificadas.\"\"\"\n    pass"
        if stripped.startswith("try:") or stripped.endswith("try:"):
            return "\n    pass\nexcept Exception as e:\n    print(f\"Error: {e}\")"

        return None
