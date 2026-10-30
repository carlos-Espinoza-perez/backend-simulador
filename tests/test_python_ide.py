import unittest
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_ide.workspace_manager import WorkspaceManager
from python_ide.script_runner import ScriptRunner

class TestPythonIDE(unittest.TestCase):
    def setUp(self):
        self.test_workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_workspace")
        self.wm = WorkspaceManager(workspace_root=self.test_workspace)
        self.runner = ScriptRunner(workspace_root=self.test_workspace)

    def tearDown(self):
        if self.runner.is_running():
            self.runner.stop_script(force=True)
        import shutil
        if os.path.exists(self.test_workspace):
            shutil.rmtree(self.test_workspace, ignore_errors=True)

    def test_workspace_file_operations(self):
        self.wm.create_file("test_script.py", "print('Hola desde test')")
        content = self.wm.read_file("test_script.py")
        self.assertEqual(content, "print('Hola desde test')")

        self.wm.write_file("test_script.py", "x = 10\nprint(x * 2)")
        self.assertEqual(self.wm.read_file("test_script.py"), "x = 10\nprint(x * 2)")

        files = self.wm.list_files()
        paths = [f["path"] for f in files]
        self.assertIn("test_script.py", paths)

        self.wm.rename_item("test_script.py", "renamed_script.py")
        files2 = self.wm.list_files()
        paths2 = [f["path"] for f in files2]
        self.assertNotIn("test_script.py", paths2)
        self.assertIn("renamed_script.py", paths2)

        self.wm.delete_item("renamed_script.py")
        files3 = self.wm.list_files()
        paths3 = [f["path"] for f in files3]
        self.assertNotIn("renamed_script.py", paths3)

    def test_path_traversal_prevention(self):
        with self.assertRaises(PermissionError):
            self.wm.read_file("../../../secret.txt")

    def test_script_execution(self):
        self.wm.create_file("runner_test.py", "import sys\nsys.stdout.write('Resultado: 42\\n')\n")
        logs = []

        def callback(stream_type, text):
            logs.append((stream_type, text))

        res = self.runner.run_script("runner_test.py", callback, timeout_sec=5.0)
        self.assertTrue(res.get("success"))

        time.sleep(0.6)
        stdout_lines = [msg for stype, msg in logs if stype == "stdout"]
        self.assertIn("Resultado: 42", stdout_lines)

    def test_script_timeout(self):
        self.wm.create_file("infinite.py", "import time\nwhile True:\n    time.sleep(0.1)\n")
        logs = []

        def callback(stream_type, text):
            logs.append((stream_type, text))

        res = self.runner.run_script("infinite.py", callback, timeout_sec=1.0)
        self.assertTrue(res.get("success"))

        time.sleep(1.5)
        self.assertFalse(self.runner.is_running())
        stderr_lines = [msg for stype, msg in logs if stype == "stderr"]
        timeout_logged = any("[TIMEOUT]" in line for line in stderr_lines)
        self.assertTrue(timeout_logged)

if __name__ == "__main__":
    unittest.main()
