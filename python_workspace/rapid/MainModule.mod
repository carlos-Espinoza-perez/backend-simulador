MODULE MainModule
    CONST robtarget pHome := [[350.0, 0.0, 400.0], [0.0, 0.0, 1.0, 0.0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];
    CONST robtarget pPick := [[400.0, 100.0, 180.0], [0.0, 0.0, 1.0, 0.0], [0, -1, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];
    CONST robtarget pPlace := [[400.0, -100.0, 180.0], [0.0, 0.0, 1.0, 0.0], [0, 0, 0, 0], [9E9, 9E9, 9E9, 9E9, 9E9, 9E9]];

    PROC main()
        MoveJ pHome, v1000, fine, tool0;

        FOR i FROM 1 TO 3 DO
            TPWrite "Iniciando ciclo de paletizado";
            MoveJ Offs(pPick, 0, (i - 1) * 25, 60), v800, z10, tool0;
            MoveL Offs(pPick, 0, (i - 1) * 25, 0), v300, fine, tool0;
            SetDO do_pinza, 1;
            WaitTime 0.3;
            MoveL Offs(pPick, 0, (i - 1) * 25, 60), v400, z10, tool0;

            MoveJ Offs(pPlace, 0, -(i - 1) * 25, 60), v800, z10, tool0;
            MoveL Offs(pPlace, 0, -(i - 1) * 25, 0), v300, fine, tool0;
            Reset do_pinza;
            WaitTime 0.3;
            MoveL Offs(pPlace, 0, -(i - 1) * 25, 60), v400, z10, tool0;
        ENDFOR

        MoveJ pHome, v1000, fine, tool0;
        TPWrite "Paletizado RAPID completado";
    ENDPROC
ENDMODULE
