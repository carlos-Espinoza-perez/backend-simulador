import unittest
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot_connection.protocol import IRC5Protocol, IRC5Message
from robot_connection.safety_validator import SafetyValidator, SafetyValidationError
from robot_connection.irc5_mock_server import IRC5MockServer
from abb_irc5 import RobotClient, IRC5ClientError

class TestIRC5TcpCommunication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 5988
        cls.server = IRC5MockServer(host="127.0.0.1", port=cls.port)
        cls.server.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.client = RobotClient(host="127.0.0.1", port=self.port, timeout=2.0)
        res = self.client.connect()
        self.assertTrue(res.get("success"), f"Conexion fallida: {res}")

    def tearDown(self):
        self.client.disconnect()

    def test_ping(self):
        res = self.client.ping()
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("data"), "PONG")
        self.assertIsNotNone(res.get("latency_ms"))

    def test_get_status(self):
        res = self.client.get_status()
        self.assertTrue(res.get("success"))
        data = res.get("data", {})
        self.assertEqual(data.get("exec_state"), "running")

    def test_get_di(self):
        res = self.client.get_di("di_pieza_presente")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("data"), 1)

    def test_get_do_and_set_do(self):
        res_set = self.client.set_do("do_valvula_aire", 1)
        self.assertTrue(res_set.get("success"))
        self.assertEqual(res_set.get("data"), 1)

        res_get = self.client.get_do("do_valvula_aire")
        self.assertTrue(res_get.get("success"))
        self.assertEqual(res_get.get("data"), 1)

        self.client.set_do("do_valvula_aire", 0)
        res_get2 = self.client.get_do("do_valvula_aire")
        self.assertEqual(res_get2.get("data"), 0)

    def test_safety_blocked_signal(self):
        with self.assertRaises(SafetyValidationError):
            self.client.set_do("safety_override", 1)

    def test_safety_unauthorized_signal(self):
        with self.assertRaises(SafetyValidationError):
            self.client.get_di("di_inexistente_no_autorizada")

    def test_physical_safety_confirmation(self):
        client_phys = RobotClient(host="127.0.0.1", port=self.port, mode="CONNECTED_PHYSICAL", allow_loopback=True)
        res_conn = client_phys.connect()
        self.assertTrue(res_conn.get("success"), f"Fallo al conectar: {res_conn}")
        with self.assertRaises(SafetyValidationError):
            client_phys.set_do("do_pinza_actuar", 1, physical_confirmed=True)

        client_phys.arm_physical_writes()

        with self.assertRaises(SafetyValidationError):
            client_phys.set_do("do_pinza_actuar", 1, physical_confirmed=False)

        res = client_phys.set_do("do_pinza_actuar", 1, physical_confirmed=True)
        self.assertTrue(res.get("success"))
        client_phys.disconnect()

    def test_get_variable(self):
        res = self.client.get_variable("cycle_count")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("data"), 42)

if __name__ == "__main__":
    unittest.main()
