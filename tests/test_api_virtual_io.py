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

    def test_edit_signal_and_export_rw5(self):
        h = {"X-Client-ID": "user_io_edit_test"}
        res_create = self.client.post("/api/virtual_io/signal/create", headers=h, json={
            "name": "do_test_edit",
            "type": "DO",
            "value": 0,
            "description": "Original"
        })
        self.assertEqual(res_create.status_code, 200)

        res_edit = self.client.post("/api/virtual_io/signal/edit", headers=h, json={
            "name": "do_test_edit",
            "new_name": "do_test_renamed",
            "description": "Editada"
        })
        self.assertEqual(res_edit.status_code, 200)
        edited = res_edit.get_json()["signal"]
        self.assertEqual(edited["name"], "do_test_renamed")
        self.assertEqual(edited["description"], "Editada")

        res_rw5 = self.client.get("/api/virtual_io/export/eio_cfg?rw=5", headers=h)
        self.assertEqual(res_rw5.status_code, 200)
        cfg5 = res_rw5.get_json()["content"]
        self.assertIn("EIO:CFG_1.0:5:0::", cfg5)
        self.assertIn("Virtual1", cfg5)
        self.assertIn("SYSSIG_OUT:", cfg5)
        self.assertIn("do_motor_on", cfg5)
        self.assertIn("do_test_renamed", cfg5)

        self.client.post("/api/virtual_io/signal/delete", headers=h, json={"name": "do_test_renamed"})

    def test_sync_and_live_do_update_with_mock(self):
        h = {"X-Client-ID": "user_io_live_test"}
        try:
            self.client.post("/api/virtual_io/signal/create", headers=h, json={
                "name": "do_live_test",
                "type": "DO",
                "value": 0,
                "description": "Salida en vivo"
            })
            self.client.post("/api/virtual_io/signal/create", headers=h, json={
                "name": "di_live_test",
                "type": "DI",
                "value": 1,
                "description": "Entrada en vivo"
            })

            r_start = self.client.post("/api/connection/mock_server/start", headers=h)
            self.assertEqual(r_start.status_code, 200)
            r_conn = self.client.post("/api/connection/connect", headers=h, json={
                "host": "127.0.0.1",
                "port": 5001,
                "mode": "SIMULATED"
            })
            self.assertEqual(r_conn.status_code, 200)
            self.assertTrue(r_conn.get_json().get("success"))

            r_sync = self.client.post("/api/virtual_io/sync", headers=h)
            self.assertEqual(r_sync.status_code, 200)
            sync_data = r_sync.get_json()
            self.assertTrue(sync_data.get("connected"))
            sig_map = {s["name"]: s for s in sync_data["signals"]}
            self.assertTrue(sig_map["do_live_test"]["synced"])
            self.assertEqual(sig_map["di_live_test"]["controller_value"], 1)

            r_upd = self.client.post("/api/virtual_io/signal/update", headers=h, json={
                "name": "do_live_test",
                "value": 1,
                "physical_confirmed": True,
                "sync_controller": True
            })
            self.assertEqual(r_upd.status_code, 200)
            upd_data = r_upd.get_json()
            self.assertTrue(upd_data.get("applied_to_controller"))
            self.assertEqual(upd_data["signal"]["value"], 1)

            r_cmd = self.client.post("/api/connection/command", headers=h, json={
                "cmd": "GET_DO",
                "name": "do_live_test"
            })
            self.assertEqual(r_cmd.status_code, 200)
            self.assertEqual(r_cmd.get_json()["data"], 1)
        finally:
            self.client.post("/api/connection/disconnect", headers=h)
            self.client.post("/api/connection/mock_server/stop", headers=h)
            self.client.post("/api/virtual_io/signal/delete", headers=h, json={"name": "do_live_test"})
            self.client.post("/api/virtual_io/signal/delete", headers=h, json={"name": "di_live_test"})

if __name__ == "__main__":
    unittest.main()
