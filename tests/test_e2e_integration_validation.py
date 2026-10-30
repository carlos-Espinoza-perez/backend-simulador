import unittest
import os
import sys
import time
import socket
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot_connection.protocol import IRC5Protocol, IRC5Message, ProtocolError
from robot_connection.safety_validator import SafetyValidator, SafetyValidationError
from robot_connection.irc5_mock_server import IRC5MockServer
from robot_connection.virtual_io_manager import VirtualIOManager
from abb_irc5 import RobotClient, IRC5ClientError
from python_ide.script_runner import ScriptRunner

class TestE2EIntegrationValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 5994
        cls.io_mgr = VirtualIOManager()
        cls.server = IRC5MockServer(host="127.0.0.1", port=cls.port, virtual_io_manager=cls.io_mgr)
        cls.server.start()
        time.sleep(0.15)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_01_e2e_protocol_exchange(self):
        client = RobotClient(host="127.0.0.1", port=self.port, timeout=2.0)
        res = client.connect()
        self.assertTrue(res.get("success"), f"Fallo al conectar: {res}")

        ping_res = client.ping()
        self.assertTrue(ping_res.get("success"))
        self.assertEqual(ping_res.get("data"), "PONG")
        self.assertGreaterEqual(ping_res.get("latency_ms"), 0)

        status_res = client.get_status()
        self.assertTrue(status_res.get("success"))
        self.assertEqual(status_res["data"]["exec_state"], "running")

        di_res = client.get_di("di_pieza_presente")
        self.assertTrue(di_res.get("success"))

        set_res = client.set_do("do_valvula_aire", 1)
        self.assertTrue(set_res.get("success"))
        get_res = client.get_do("do_valvula_aire")
        self.assertTrue(get_res.get("success"))
        self.assertEqual(get_res.get("data"), 1)

        client.set_do("do_valvula_aire", 0)

        var_res = client.get_variable("cycle_count")
        self.assertTrue(var_res.get("success"))
        self.assertEqual(var_res.get("data"), 42)

        client.disconnect()

    def test_02_partial_and_malformed_messages(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("127.0.0.1", self.port))

        s.sendall(b'{"id":99,"cmd":"PI')
        time.sleep(0.05)
        s.sendall(b'NG","params":{}}\n')

        data = s.recv(1024)
        msg = IRC5Message.from_raw(data.decode("utf-8"))
        self.assertEqual(msg.msg_id, 99)
        self.assertEqual(msg.status, "OK")
        self.assertEqual(msg.data, "PONG")

        s.sendall(b'{corrupt_json\n')
        data_err = s.recv(1024)
        s.close()

    def test_03_virtual_io_lifecycle_and_whitelist_sync(self):
        sig_name = "di_sensor_verificacion"
        self.io_mgr.create_signal(sig_name, "DI", initial_value=1, description="Sensor de prueba E2E")

        self.assertIsNotNone(self.io_mgr.get_signal(sig_name))
        self.assertEqual(self.io_mgr.get_value(sig_name), 1)

        reloaded_mgr = VirtualIOManager(storage_path=self.io_mgr.storage_path)
        self.assertIsNotNone(reloaded_mgr.get_signal(sig_name))

        client = RobotClient(host="127.0.0.1", port=self.port, timeout=2.0)
        client.sync_validator_signals(self.io_mgr.get_allowed_di(), self.io_mgr.get_allowed_do())
        client.connect()

        res_di = client.get_di(sig_name)
        self.assertTrue(res_di.get("success"))
        self.assertEqual(res_di.get("data"), 1)

        self.io_mgr.update_signal_value(sig_name, 0)
        res_di_mod = client.get_di(sig_name)
        self.assertEqual(res_di_mod.get("data"), 0)

        self.io_mgr.delete_signal(sig_name)
        client.sync_validator_signals(self.io_mgr.get_allowed_di(), self.io_mgr.get_allowed_do())

        with self.assertRaises(SafetyValidationError):
            client.get_di(sig_name)

        client.disconnect()

    def test_04_security_physical_arming_and_host_validation(self):
        client_sim = RobotClient(host="192.168.1.100", port=5001, mode="SIMULATED")
        res_sim = client_sim.connect()
        self.assertFalse(res_sim.get("success"))
        self.assertIn("SIMULATED no puede conectar a la IP remota", res_sim.get("error"))

        client_unconf = RobotClient(host="0.0.0.0", port=5001, mode="CONNECTED_PHYSICAL")
        res_unconf = client_unconf.connect()
        self.assertFalse(res_unconf.get("success"))
        self.assertIn("Direccion IP no configurada", res_unconf.get("error"))

        client_phys = RobotClient(host="127.0.0.1", port=self.port, mode="CONNECTED_PHYSICAL", allow_loopback=True)
        res_phys_conn = client_phys.connect()
        self.assertTrue(res_phys_conn.get("success"), f"Fallo conexion loopback fisica: {res_phys_conn}")

        with self.assertRaises(SafetyValidationError):
            client_phys.set_do("do_valvula_aire", 1, physical_confirmed=True)

        client_phys.arm_physical_writes()
        res_ok = client_phys.set_do("do_valvula_aire", 1, physical_confirmed=True)
        self.assertTrue(res_ok.get("success"))

        client_phys.disconnect()

    def test_05_security_blocked_signals(self):
        with self.assertRaises(ValueError):
            self.io_mgr.create_signal("safety_guard", "DI")

        with self.assertRaises(ValueError):
            self.io_mgr.update_signal_value("emergencia", 1)

        with self.assertRaises(ValueError):
            self.io_mgr.delete_signal("brake_release")

    def test_06_real_script_runner_execution(self):
        ws_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python_workspace")
        runner = ScriptRunner(ws_dir)

        captured_logs = []
        def on_output(stream_type, text):
            captured_logs.append((stream_type, text))

        mock_5001 = IRC5MockServer(host="127.0.0.1", port=5001, virtual_io_manager=self.io_mgr)
        mock_5001.start()
        try:
            res = runner.run_script("ejemplo_monitoreo_irc5.py", on_output, timeout_sec=10.0)
            self.assertTrue(res.get("success"))

            t0 = time.time()
            time.sleep(0.2)
            while runner.is_running() and (time.time() - t0) < 6.0:
                time.sleep(0.1)

            self.assertFalse(runner.is_running())
            log_texts = " ".join([txt for _, txt in captured_logs])
            self.assertIn("Monitoreo de sistema", log_texts)
            self.assertIn("Ping RTT:", log_texts)
            self.assertIn("Contador de ciclos:", log_texts)
        finally:
            mock_5001.stop()

    def test_07_real_script_runner_cycle_automation(self):
        ws_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python_workspace")
        runner = ScriptRunner(ws_dir)

        captured_logs = []
        def on_output(stream_type, text):
            captured_logs.append((stream_type, text))

        mock_5001 = IRC5MockServer(host="127.0.0.1", port=5001, virtual_io_manager=self.io_mgr)
        mock_5001.start()
        try:
            res = runner.run_script("ejemplo_ciclo_io.py", on_output, timeout_sec=10.0)
            self.assertTrue(res.get("success"))

            t0 = time.time()
            time.sleep(0.2)
            while runner.is_running() and (time.time() - t0) < 6.0:
                time.sleep(0.1)

            self.assertFalse(runner.is_running())
            log_texts = " ".join([txt for _, txt in captured_logs])
            self.assertIn("Iniciando secuencia de ciclo", log_texts)
            self.assertIn("Pieza detectada en estacion", log_texts)
            self.assertIn("Secuencia finalizada", log_texts)
        finally:
            mock_5001.stop()

if __name__ == "__main__":
    unittest.main()
