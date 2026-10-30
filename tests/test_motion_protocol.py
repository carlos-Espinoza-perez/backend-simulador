import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot_connection.protocol import IRC5Protocol, IRC5Message, ProtocolError
from robot_connection.safety_validator import SafetyValidator, SafetyValidationError
from robot_connection.irc5_mock_server import IRC5MockServer
from abb_irc5 import RobotClient, IRC5ClientError

class TestMotionProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 5991
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

    def test_protocol_supported_commands(self):
        self.assertIn("MOVE_JOINTS", IRC5Protocol.SUPPORTED_COMMANDS)
        self.assertIn("MOVE_PRESET", IRC5Protocol.SUPPORTED_COMMANDS)
        self.assertIn("GET_JOINTS", IRC5Protocol.SUPPORTED_COMMANDS)

    def test_protocol_build_motion_request(self):
        raw = IRC5Protocol.build_request(10, "MOVE_PRESET", {"target": "HOME", "speed": 50})
        messages, _ = IRC5Protocol.extract_messages_from_buffer(raw)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].cmd, "MOVE_PRESET")
        self.assertEqual(messages[0].params.get("target"), "HOME")

    def test_safety_validator_presets(self):
        val = SafetyValidator(mode="SIMULATED")
        res = val.validate_motion_command("MOVE_PRESET", {"target": "HOME", "speed": 50})
        self.assertEqual(res["target"], "HOME")
        self.assertEqual(res["joints"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_PRESET", {"target": "UNSAFE_TARGET"})

    def test_safety_validator_joint_limits(self):
        val = SafetyValidator(mode="SIMULATED")
        valid = val.validate_motion_command("MOVE_JOINTS", {"joints": [0, 10, -10, 0, 20, 0], "speed": 50})
        self.assertEqual(valid["joints"], [0.0, 10.0, -10.0, 0.0, 20.0, 0.0])

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_JOINTS", {"joints": [0, 150, 0, 0, 0, 0]})

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_JOINTS", {"joints": [0, 0, 0]})

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_JOINTS", {"joints": [0, float('nan'), 0, 0, 0, 0]})

    def test_safety_validator_physical_mode(self):
        val = SafetyValidator(mode="CONNECTED_PHYSICAL")

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_PRESET", {"target": "HOME"}, physical_confirmed=True)

        val.arm_physical_mode()

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_PRESET", {"target": "HOME"}, physical_confirmed=False)

        res = val.validate_motion_command("MOVE_PRESET", {"target": "HOME", "speed": 50}, physical_confirmed=True)
        self.assertEqual(res["target"], "HOME")

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_PRESET", {"target": "HOME", "speed": 150}, physical_confirmed=True)

        with self.assertRaises(SafetyValidationError):
            val.validate_motion_command("MOVE_JOINTS", {"joints": [120, 0, 0, 0, 0, 0], "speed": 50}, physical_confirmed=True)

    def test_client_get_joints(self):
        res = self.client.get_joints()
        self.assertTrue(res.get("success"))
        data = res.get("data", {})
        self.assertIn("joints", data)
        self.assertEqual(len(data["joints"]), 6)

    def test_client_move_preset(self):
        res = self.client.move_preset("TEST_DELTA_J1", speed=50.0)
        self.assertTrue(res.get("success"), f"Fallo move_preset: {res}")
        data = res.get("data", {})
        self.assertEqual(data.get("state"), "COMPLETED")
        self.assertEqual(data.get("target"), "TEST_DELTA_J1")
        self.assertEqual(data.get("joints"), [10.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        j_res = self.client.get_joints()
        self.assertEqual(j_res.get("data", {}).get("joints"), [10.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_client_move_joints(self):
        target = [0.0, 15.0, -15.0, 0.0, 30.0, 0.0]
        res = self.client.move_joints(target, speed=50.0)
        self.assertTrue(res.get("success"), f"Fallo move_joints: {res}")
        data = res.get("data", {})
        self.assertEqual(data.get("state"), "COMPLETED")
        self.assertEqual(data.get("joints"), target)

        j_res = self.client.get_joints()
        self.assertEqual(j_res.get("data", {}).get("joints"), target)

    def test_client_physical_motion_guard(self):
        client_phys = RobotClient(host="127.0.0.1", port=self.port, mode="CONNECTED_PHYSICAL", allow_loopback=True)
        res_conn = client_phys.connect()
        self.assertTrue(res_conn.get("success"))

        with self.assertRaises(SafetyValidationError):
            client_phys.move_preset("HOME", physical_confirmed=True)

        client_phys.arm_physical_writes()

        with self.assertRaises(SafetyValidationError):
            client_phys.move_preset("HOME", physical_confirmed=False)

        res = client_phys.move_preset("HOME", speed=50.0, physical_confirmed=True)
        self.assertTrue(res.get("success"))
        client_phys.disconnect()

if __name__ == "__main__":
    unittest.main()
