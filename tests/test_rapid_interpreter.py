import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rapid_parser import parse_rapid_code

class TestRapidInterpreter(unittest.TestCase):
    def test_basic_linear_motion(self):
        code = """
        MODULE MainModule
            CONST robtarget pHome := [[350, 0, 400], [0, 0, 1, 0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];
            CONST robtarget pPick := [[400, 100, 200], [0, 0, 1, 0], [0, -1, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];

            PROC main()
                MoveJ pHome, v100, fine, tool0;
                MoveL pPick, v50, z10, tool0;
            ENDPROC
        ENDMODULE
        """
        res = parse_rapid_code(code)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["movements"]), 2)
        self.assertEqual(res["movements"][0]["type"], "MoveJ")
        self.assertEqual(res["movements"][1]["type"], "MoveL")
        self.assertEqual(res["movements"][0]["data"]["position"], [350.0, 0.0, 400.0])

    def test_for_loop_with_offs(self):
        code = """
        MODULE MainModule
            CONST robtarget pStart := [[300, 0, 300], [1, 0, 0, 0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];

            PROC main()
                FOR i FROM 1 TO 3 DO
                    MoveL Offs(pStart, i * 10, 0, i * 5), v100, fine, tool0;
                ENDFOR
            ENDPROC
        ENDMODULE
        """
        res = parse_rapid_code(code)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["movements"]), 3)
        self.assertEqual(res["movements"][0]["data"]["position"], [310.0, 0.0, 305.0])
        self.assertEqual(res["movements"][1]["data"]["position"], [320.0, 0.0, 310.0])
        self.assertEqual(res["movements"][2]["data"]["position"], [330.0, 0.0, 315.0])

    def test_while_loop_and_conditionals(self):
        code = """
        MODULE MainModule
            CONST robtarget pBase := [[200, 50, 200], [0, 0, 1, 0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];
            VAR num k := 0;

            PROC main()
                WHILE k < 4 DO
                    IF k = 2 THEN
                        MoveJ Offs(pBase, 100, 0, 0), v100, fine, tool0;
                    ELSE
                        MoveL pBase, v50, z10, tool0;
                    ENDIF
                    k := k + 1;
                ENDWHILE
            ENDPROC
        ENDMODULE
        """
        res = parse_rapid_code(code)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["movements"]), 4)
        self.assertEqual(res["movements"][0]["data"]["position"], [200.0, 50.0, 200.0])
        self.assertEqual(res["movements"][1]["data"]["position"], [200.0, 50.0, 200.0])
        self.assertEqual(res["movements"][2]["data"]["position"], [300.0, 50.0, 200.0])
        self.assertEqual(res["movements"][3]["data"]["position"], [200.0, 50.0, 200.0])

    def test_reltool_transformation(self):
        code = """
        MODULE MainModule
            CONST robtarget pHome := [[300, 200, 400], [1, 0, 0, 0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];

            PROC main()
                MoveL RelTool(pHome, 0, 0, 50), v100, fine, tool0;
            ENDPROC
        ENDMODULE
        """
        res = parse_rapid_code(code)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["movements"]), 1)
        self.assertEqual(res["movements"][0]["data"]["position"], [300.0, 200.0, 450.0])

    def test_procedure_calls_and_process_instructions(self):
        code = """
        MODULE MainModule
            CONST robtarget pHome := [[350, 0, 400], [0, 0, 1, 0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];

            PROC grip_cycle()
                SetDO do_pinza, 1;
                WaitTime 0.5;
                Reset do_pinza;
            ENDPROC

            PROC main()
                MoveJ pHome, v100, fine, tool0;
                grip_cycle();
                MoveL Offs(pHome, 0, 0, -50), v100, fine, tool0;
            ENDPROC
        ENDMODULE
        """
        res = parse_rapid_code(code)
        self.assertTrue(res["success"])
        types = [m["type"] for m in res["movements"]]
        self.assertIn("MoveJ", types)
        self.assertIn("SetDO", types)
        self.assertIn("WaitTime", types)
        self.assertIn("Reset", types)
        self.assertIn("MoveL", types)

if __name__ == "__main__":
    unittest.main()
