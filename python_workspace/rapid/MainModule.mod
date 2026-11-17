MODULE MainModule
    CONST jointtarget jHome := [[0, 0, 0, 0, 0, 0], [9E+9, 9E+9, 9E+9, 9E+9, 9E+9, 9E+9]];
    CONST jointtarget jSeguro1 := [[10, 0, 0, 0, 20, 0], [9E+9, 9E+9, 9E+9, 9E+9, 9E+9, 9E+9]];
    CONST jointtarget jSeguro2 := [[10, 10, -10, 0, 25, 0], [9E+9, 9E+9, 9E+9, 9E+9, 9E+9, 9E+9]];

    PROC main()
        TPWrite "Iniciando prueba segura";
        MoveAbsJ jHome\NoEOffs, v50, fine, tool0;
        MoveAbsJ jSeguro1\NoEOffs, v50, fine, tool0;
        WaitTime 0.5;
        MoveAbsJ jSeguro2\NoEOffs, v50, fine, tool0;
        WaitTime 0.5;
        MoveAbsJ jHome\NoEOffs, v50, fine, tool0;
        TPWrite "Prueba segura completada";
    ENDPROC
ENDMODULE
