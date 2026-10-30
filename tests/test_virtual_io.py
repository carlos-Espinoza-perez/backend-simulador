import unittest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from robot_connection.virtual_io_manager import VirtualIOManager
from robot_connection.irc5_mock_server import IRC5MockServer
from abb_irc5 import RobotClient, IRC5ClientError

class TestVirtualIOManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.test_dir, "test_virtual_io.json")
        self.io_mgr = VirtualIOManager(storage_path=self.storage_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_signals_loaded(self):
        signals = self.io_mgr.list_signals()
        self.assertGreater(len(signals), 5)
        names = {s["name"] for s in signals}
        self.assertIn("di_pieza_presente", names)
        self.assertIn("do_valvula_aire", names)

    def test_create_and_delete_signal(self):
        created = self.io_mgr.create_signal(
            name="di_sensor_conveyor",
            signal_type="DI",
            initial_value=1,
            description="Sensor fotoelectrico de banda"
        )
        self.assertEqual(created["name"], "di_sensor_conveyor")
        self.assertEqual(created["value"], 1)

        sig = self.io_mgr.get_signal("di_sensor_conveyor")
        self.assertIsNotNone(sig)
        self.assertEqual(sig["type"], "DI")

        deleted = self.io_mgr.delete_signal("di_sensor_conveyor")
        self.assertTrue(deleted)
        self.assertIsNone(self.io_mgr.get_signal("di_sensor_conveyor"))

    def test_validation_rules(self):
        with self.assertRaises(ValueError):
            self.io_mgr.create_signal("123_invalido", "DI")

        with self.assertRaises(ValueError):
            self.io_mgr.create_signal("safety_guard", "DI")

        with self.assertRaises(ValueError):
            self.io_mgr.create_signal("do_test_tipo", "ANALOG")

    def test_update_signal_value(self):
        self.io_mgr.update_signal_value("do_valvula_aire", 1)
        self.assertEqual(self.io_mgr.get_value("do_valvula_aire"), 1)

        self.io_mgr.update_signal_value("do_valvula_aire", 0)
        self.assertEqual(self.io_mgr.get_value("do_valvula_aire"), 0)

    def test_generate_eio_cfg(self):
        cfg = self.io_mgr.generate_eio_cfg()
        self.assertIn("EIO:CFG_1.0:6:0::", cfg)
        self.assertIn("EIO_SIGNAL:", cfg)
        self.assertIn("-Name \"di_pieza_presente\"", cfg)
        self.assertIn("-Name \"do_valvula_aire\"", cfg)

    def test_mock_server_integration(self):
        port = 5991
        server = IRC5MockServer(host="127.0.0.1", port=port, virtual_io_manager=self.io_mgr)
        server.start()
        try:
            self.io_mgr.create_signal("di_custom_camera", "DI", initial_value=1)
            self.io_mgr.create_signal("do_custom_lamp", "DO", initial_value=0)

            client = RobotClient(host="127.0.0.1", port=port, timeout=2.0)
            client.sync_validator_signals(self.io_mgr.get_allowed_di(), self.io_mgr.get_allowed_do())
            res = client.connect()
            self.assertTrue(res.get("success"))

            res_di = client.get_di("di_custom_camera")
            self.assertTrue(res_di.get("success"))
            self.assertEqual(res_di.get("data"), 1)

            res_set = client.set_do("do_custom_lamp", 1)
            self.assertTrue(res_set.get("success"))
            self.assertEqual(self.io_mgr.get_value("do_custom_lamp"), 1)

            client.disconnect()
        finally:
            server.stop()

if __name__ == "__main__":
    unittest.main()
