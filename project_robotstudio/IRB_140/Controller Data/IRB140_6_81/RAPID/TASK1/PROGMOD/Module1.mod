MODULE Module1
  CONST jointtarget ZERO:=[[0,0,0,0,0,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
  CONST robtarget P10:=[[450,0,450],[4.14816E-8,6.1133E-9,-1,-2.53589E-16],[0,0,-1,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
  CONST robtarget P20:=[[450,0,400],[4.14816E-8,6.1133E-9,-1,-2.53589E-16],[0,0,-1,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
  CONST robtarget P30:=[[550,0,400],[4.14816E-8,6.1133E-9,-1,-2.53589E-16],[0,0,-1,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
  
  PROC main()
    MoveAbsJ ZERO\NoEOffs, v1000, fine, tool0;
    MoveJ P10, v1000, fine, tool0;
    MoveL P20, v1000, fine, tool0;
    MoveL P30, v1000, fine, tool0;
    MoveL P20, v1000, fine, tool0;
    MoveAbsJ ZERO\NoEOffs, v1000, fine, tool0;
  ENDPROC
ENDMODULE