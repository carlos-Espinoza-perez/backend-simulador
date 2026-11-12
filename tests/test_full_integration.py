import unittest
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_ide.workspace_manager import WorkspaceManager
from python_ide.script_runner import ScriptRunner
from robot_connection.irc5_mock_server import IRC5MockServer

class TestFullIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_server = IRC5MockServer(host="127.0.0.1", port=5001)
        self.mock_server.start()
        time.sleep(0.1)

        self.wm = WorkspaceManager()
        self.runner = ScriptRunner(self.wm.workspace_root)

    def tearDown(self):
        if self.runner.is_running():
            self.runner.stop_script(force=True)
        self.mock_server.stop()

    def test_run_workspace_main_py_with_mock_server(self):
        logs = []
        def log_cb(stype, text):
            logs.append((stype, text))

        res = self.runner.run_script("main.py", log_cb, timeout_sec=5.0)
        self.assertTrue(res.get("success"))

        time.sleep(1.2)
        all_stdout = "\n".join([text for stype, text in logs if stype == "stdout"])

        self.assertTrue(
            "Ciclo de deteccion" in all_stdout or "Iniciando script" in all_stdout
        )
        self.assertTrue(
            "Conectado a controlador IRC5" in all_stdout or "PONG" in all_stdout
        )

if __name__ == "__main__":
    unittest.main()
