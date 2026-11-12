import os
import shutil
from typing import List, Dict, Any, Optional

class WorkspaceManager:
    def __init__(self, workspace_root: Optional[str] = None):
        if workspace_root is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.workspace_root = os.path.join(base_dir, "python_workspace")
        else:
            self.workspace_root = os.path.abspath(workspace_root)
        
        os.makedirs(self.workspace_root, exist_ok=True)
        self._init_default_workspace()

    def _init_default_workspace(self) -> None:
        python_dir = os.path.join(self.workspace_root, "python")
        rapid_dir = os.path.join(self.workspace_root, "rapid")
        os.makedirs(python_dir, exist_ok=True)
        os.makedirs(rapid_dir, exist_ok=True)

        main_py = os.path.join(python_dir, "main.py")
        if not os.path.exists(main_py):
            base_main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python_workspace", "python", "main.py")
            if os.path.exists(base_main):
                shutil.copy2(base_main, main_py)
            else:
                with open(main_py, "w", encoding="utf-8") as f:
                    f.write(
                        'from main_celda import ejecutar_ciclo_clasificacion\n\n'
                        'if __name__ == "__main__":\n'
                        '    ejecutar_ciclo_clasificacion()\n'
                    )

        rapid_mod = os.path.join(rapid_dir, "MainModule.mod")
        if not os.path.exists(rapid_mod):
            with open(rapid_mod, "w", encoding="utf-8") as f:
                f.write(
                    'MODULE MainModule\n'
                    '    CONST robtarget pHome := [[350.0, 0.0, 400.0], [0.0, 0.0, 1.0, 0.0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];\n'
                    '    VAR robtarget pPick := [[400.0, 100.0, 200.0], [0.0, 0.0, 1.0, 0.0], [0, -1, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];\n'
                    '    VAR robtarget pPlace := [[400.0, -100.0, 200.0], [0.0, 0.0, 1.0, 0.0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];\n\n'
                    '    PROC main()\n'
                    '        MoveJ pHome, v100, fine, tool0;\n'
                    '        MoveL pPick, v80, z10, tool0;\n'
                    '        WaitTime 0.5;\n'
                    '        MoveL pPlace, v80, fine, tool0;\n'
                    '        MoveJ pHome, v100, fine, tool0;\n'
                    '    ENDPROC\n'
                    'ENDMODULE\n'
                )

        config_json = os.path.join(self.workspace_root, "config.json")
        if not os.path.exists(config_json):
            with open(config_json, "w", encoding="utf-8") as f:
                f.write(
                    '{\n'
                    '  "connection_profile": "virtual",\n'
                    '  "controller_ip": "127.0.0.1",\n'
                    '  "controller_port": 5001,\n'
                    '  "timeout_sec": 3.0\n'
                    '}\n'
                )

    def _resolve_safe_path(self, rel_path: str) -> str:
        clean_rel = rel_path.strip().lstrip("/\\")
        abs_target = os.path.abspath(os.path.join(self.workspace_root, clean_rel))
        
        common = os.path.commonpath([self.workspace_root, abs_target])
        if common != self.workspace_root:
            raise PermissionError("Acceso denegado: ruta fuera del workspace del proyecto.")

        if not os.path.exists(abs_target):
            candidate_py = os.path.join(self.workspace_root, "python", clean_rel)
            if os.path.exists(candidate_py):
                return os.path.abspath(candidate_py)
            candidate_rapid = os.path.join(self.workspace_root, "rapid", clean_rel)
            if os.path.exists(candidate_rapid):
                return os.path.abspath(candidate_rapid)

        return abs_target

    def list_files(self) -> List[Dict[str, Any]]:
        items = []
        for root, dirs, files in os.walk(self.workspace_root):
            rel_dir = os.path.relpath(root, self.workspace_root)
            if rel_dir == ".":
                rel_dir = ""
            
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "users"]

            for d in dirs:
                rel_item = os.path.join(rel_dir, d).replace("\\", "/")
                items.append({
                    "name": d,
                    "path": rel_item,
                    "type": "directory"
                })

            for f in files:
                if f.startswith(".") or f.endswith(".pyc"):
                    continue
                rel_item = os.path.join(rel_dir, f).replace("\\", "/")
                full_path = os.path.join(root, f)
                items.append({
                    "name": f,
                    "path": rel_item,
                    "type": "file",
                    "size": os.path.getsize(full_path),
                    "modified": os.path.getmtime(full_path)
                })
        return items

    def read_file(self, rel_path: str) -> str:
        safe_path = self._resolve_safe_path(rel_path)
        if not os.path.isfile(safe_path):
            raise FileNotFoundError(f"Archivo no encontrado: {rel_path}")
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def write_file(self, rel_path: str, content: str) -> None:
        safe_path = self._resolve_safe_path(rel_path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

    def create_file(self, rel_path: str, initial_content: str = "") -> None:
        safe_path = self._resolve_safe_path(rel_path)
        if os.path.exists(safe_path):
            raise FileExistsError(f"El archivo ya existe: {rel_path}")
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(initial_content)

    def create_directory(self, rel_path: str) -> None:
        safe_path = self._resolve_safe_path(rel_path)
        if os.path.exists(safe_path):
            raise FileExistsError(f"La carpeta ya existe: {rel_path}")
        os.makedirs(safe_path, exist_ok=True)

    def rename_item(self, old_rel_path: str, new_rel_path: str) -> None:
        safe_old = self._resolve_safe_path(old_rel_path)
        safe_new = self._resolve_safe_path(new_rel_path)
        if not os.path.exists(safe_old):
            raise FileNotFoundError(f"Origen no encontrado: {old_rel_path}")
        if os.path.exists(safe_new):
            raise FileExistsError(f"Destino ya existente: {new_rel_path}")
        os.makedirs(os.path.dirname(safe_new), exist_ok=True)
        shutil.move(safe_old, safe_new)

    def delete_item(self, rel_path: str) -> None:
        safe_path = self._resolve_safe_path(rel_path)
        if safe_path == self.workspace_root:
            raise PermissionError("No se permite eliminar la raiz del workspace.")
        if not os.path.exists(safe_path):
            raise FileNotFoundError(f"Elemento no encontrado: {rel_path}")
        if os.path.isdir(safe_path):
            shutil.rmtree(safe_path)
        else:
            os.remove(safe_path)
