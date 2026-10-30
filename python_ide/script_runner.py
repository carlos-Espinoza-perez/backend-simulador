import os
import sys
import time
import subprocess
import threading
from typing import Callable, Optional, Dict, Any

class ScriptRunner:
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.current_process: Optional[subprocess.Popen] = None
        self.process_lock = threading.Lock()
        self.start_time: Optional[float] = None
        self.execution_thread: Optional[threading.Thread] = None
        self.current_script: Optional[str] = None
        self.logs: list = []

    def is_running(self) -> bool:
        with self.process_lock:
            if self.execution_thread is not None and self.execution_thread.is_alive():
                return True
            if self.current_process is None:
                return False
            return self.current_process.poll() is None

    def run_script(
        self,
        rel_script_path: str,
        output_callback: Callable[[str, str], None],
        timeout_sec: float = 60.0
    ) -> Dict[str, Any]:
        with self.process_lock:
            if self.execution_thread is not None and self.execution_thread.is_alive():
                return {
                    "success": False,
                    "error": "Ya hay un proceso en ejecucion. Detengalo antes de iniciar otro."
                }
            if self.current_process is not None and self.current_process.poll() is None:
                return {
                    "success": False,
                    "error": "Ya hay un proceso en ejecucion. Detengalo antes de iniciar otro."
                }

        abs_script = os.path.abspath(os.path.join(self.workspace_root, rel_script_path))
        if not os.path.isfile(abs_script):
            candidate_py = os.path.join(self.workspace_root, "python", rel_script_path)
            if os.path.isfile(candidate_py):
                abs_script = os.path.abspath(candidate_py)
            else:
                return {"success": False, "error": f"Archivo no encontrado: {rel_script_path}"}

        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_dir = os.path.dirname(abs_script)
        env = os.environ.copy()
        python_paths = [self.workspace_root, script_dir, backend_dir]
        if "PYTHONPATH" in env:
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("IRC5_BACKEND_PROXY", f"http://127.0.0.1:{os.environ.get('PORT', '5000')}")

        def _record_and_emit(stream_type: str, text: str):
            with self.process_lock:
                self.logs.append({"type": stream_type, "text": text, "timestamp": time.time()})
            output_callback(stream_type, text)

        def _execute():
            with self.process_lock:
                self.logs = []
            self.start_time = time.time()
            self.current_script = rel_script_path
            _record_and_emit("system", f"--- Ejecutando {rel_script_path} (PID inicializando) ---")

            try:
                proc = subprocess.Popen(
                    [sys.executable, "-u", abs_script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=script_dir,
                    env=env,
                    text=True,
                    bufsize=1
                )
                with self.process_lock:
                    self.current_process = proc

                _record_and_emit("system", f"--- Proceso iniciado [PID: {proc.pid}] ---")

                def _read_stream(stream, stream_type):
                    try:
                        for line in iter(stream.readline, ''):
                            _record_and_emit(stream_type, line.rstrip("\r\n"))
                    except Exception as err:
                        _record_and_emit("system", f"Error en lectura de flujo: {err}")
                    finally:
                        stream.close()

                t_out = threading.Thread(target=_read_stream, args=(proc.stdout, "stdout"), daemon=True)
                t_err = threading.Thread(target=_read_stream, args=(proc.stderr, "stderr"), daemon=True)
                t_out.start()
                t_err.start()

                while proc.poll() is None:
                    if time.time() - self.start_time > timeout_sec:
                        _record_and_emit("stderr", f"\n[TIMEOUT] Tiempo maximo de ejecucion ({timeout_sec}s) alcanzado. Terminando...")
                        self.stop_script(force=True)
                        break
                    time.sleep(0.1)

                t_out.join(timeout=2.0)
                t_err.join(timeout=2.0)
                exit_code = proc.wait()
                duration = time.time() - self.start_time
                _record_and_emit("system", f"--- Proceso finalizado con codigo {exit_code} ({duration:.2f}s) ---")

            except Exception as e:
                _record_and_emit("stderr", f"[ERROR DE PROCESO] {str(e)}")
            finally:
                with self.process_lock:
                    self.current_process = None
                    self.current_script = None

        self.execution_thread = threading.Thread(target=_execute, daemon=True)
        self.execution_thread.start()

        return {
            "success": True,
            "message": "Ejecucion iniciada en subproceso controlado.",
            "script": rel_script_path
        }

    def stop_script(self, force: bool = False) -> Dict[str, Any]:
        with self.process_lock:
            if self.current_process is None or self.current_process.poll() is not None:
                return {"success": False, "error": "No hay procesos activos."}

            proc = self.current_process

        try:
            if force:
                proc.kill()
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return {"success": True, "message": "Proceso detenido exitosamente."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        with self.process_lock:
            running = self.current_process is not None and self.current_process.poll() is None
            pid = self.current_process.pid if running else None
            elapsed = time.time() - self.start_time if (running and self.start_time) else 0.0

        return {
            "is_running": running,
            "pid": pid,
            "current_script": self.current_script,
            "elapsed_seconds": round(elapsed, 2)
        }

    def get_logs(self, since: int = 0) -> list:
        with self.process_lock:
            return self.logs[since:]
