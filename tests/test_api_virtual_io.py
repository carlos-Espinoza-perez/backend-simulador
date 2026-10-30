import unittest
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

class TestAPIVirtualIO(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_list_signals(self):
        res = self.client.get("/api/virtual_io/signals")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("signals"), list)

    def test_create_and_delete_signal(self):
        res = self.client.post("/api/virtual_io/signal/create", json={
            "name": "di_test_api_sensor",
            "type": "DI",
            "value": 1,
            "description": "Prueba API"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["signal"]["name"], "di_test_api_sensor")

        res_update = self.client.post("/api/virtual_io/signal/update", json={
            "name": "di_test_api_sensor",
            "value": 0
        })
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.get_json()["signal"]["value"], 0)

        res_del = self.client.post("/api/virtual_io/signal/delete", json={
            "name": "di_test_api_sensor"
        })
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json().get("success"))

    def test_export_eio_cfg(self):
        res = self.client.get("/api/virtual_io/export/eio_cfg")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("EIO:CFG_1.0:6:0::", data["content"])

    def test_connection_profiles(self):
        res = self.client.get("/api/connection/profiles")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("profiles", data)
        self.assertGreaterEqual(len(data["profiles"]), 1)

    def test_multitenant_browser_isolation(self):
        h_alpha = {"X-Client-ID": "user_alpha_test"}
        h_beta = {"X-Client-ID": "user_beta_test"}

        res_create = self.client.post("/api/virtual_io/signal/create", headers=h_alpha, json={
            "name": "di_alpha_special",
            "type": "DI",
            "value": 1,
            "description": "Exclusiva de Alpha"
        })
        self.assertEqual(res_create.status_code, 200)

        res_alpha_list = self.client.get("/api/virtual_io/signals", headers=h_alpha)
        names_alpha = [s["name"] for s in res_alpha_list.get_json()["signals"]]
        self.assertIn("di_alpha_special", names_alpha)

        res_beta_list = self.client.get("/api/virtual_io/signals", headers=h_beta)
        names_beta = [s["name"] for s in res_beta_list.get_json()["signals"]]
        self.assertNotIn("di_alpha_special", names_beta)

        res_f_alpha = self.client.post("/api/ide/file/create", headers=h_alpha, json={
            "path": "alpha_script.py",
            "content": "print('alpha')"
        })
        self.assertEqual(res_f_alpha.status_code, 200)

        res_files_beta = self.client.get("/api/ide/files", headers=h_beta)
        beta_files = [f["name"] for f in res_files_beta.get_json()["files"]]
        self.assertNotIn("alpha_script.py", beta_files)

        self.client.post("/api/virtual_io/signal/delete", headers=h_alpha, json={"name": "di_alpha_special"})
        self.client.post("/api/ide/item/delete", headers=h_alpha, json={"path": "alpha_script.py"})

if __name__ == "__main__":
    unittest.main()
