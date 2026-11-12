MODULE IRC5_TcpServer
    LOCAL VAR socketdev server_socket;
    LOCAL VAR socketdev client_socket;
    LOCAL VAR string client_ip;
    LOCAL VAR bool keep_listening := TRUE;

    CONST num SERVER_PORT := 5001;
    CONST num RECV_TIMEOUT := 30;

    PERS num cycle_counter := 0;
    PERS num current_speed := 100;

    CONST jointtarget JT_HOME := [[0,0,0,0,0,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
    CONST jointtarget JT_DELTA_J1 := [[10,0,0,0,0,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
    CONST jointtarget JT_SAFE_1 := [[0,15,-15,0,30,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];

    PROC main()
        EnsureServer;
        WHILE keep_listening DO
            AcceptAndServe;
        ENDWHILE
    ENDPROC

    LOCAL PROC EnsureServer()
        IF SocketGetStatus(client_socket) <> SOCKET_CLOSED THEN
            SocketClose client_socket;
        ENDIF
        IF SocketGetStatus(server_socket) <> SOCKET_LISTENING THEN
            IF SocketGetStatus(server_socket) <> SOCKET_CLOSED THEN
                SocketClose server_socket;
            ENDIF
            SocketCreate server_socket;
            SocketBind server_socket, "0.0.0.0", SERVER_PORT;
            SocketListen server_socket;
            ErrWrite \I, "IRC5 TCP 5001", "Escuchando conexiones en 0.0.0.0:5001";
            TPWrite "Servidor TCP activo en puerto 5001";
        ENDIF
    ENDPROC

    LOCAL PROC AcceptAndServe()
        EnsureServer;
        SocketAccept server_socket, client_socket \ClientAddress:=client_ip \Time:=WAIT_MAX;
        ErrWrite \I, "IRC5 TCP 5001", "Cliente conectado: " + client_ip;
        TPWrite "Cliente conectado: " + client_ip;

        ClientLoop;

        IF SocketGetStatus(client_socket) <> SOCKET_CLOSED THEN
            SocketClose client_socket;
        ENDIF
        ErrWrite \I, "IRC5 TCP 5001", "Cliente desconectado, esperando nueva conexion";
    ERROR
        IF ERRNO = ERR_SOCK_TIMEOUT THEN
            RETRY;
        ELSE
            IF SocketGetStatus(client_socket) <> SOCKET_CLOSED THEN
                SocketClose client_socket;
            ENDIF
            IF SocketGetStatus(server_socket) <> SOCKET_CLOSED THEN
                SocketClose server_socket;
            ENDIF
            WaitTime 0.5;
            RETURN;
        ENDIF
    ENDPROC

    LOCAL PROC ClientLoop()
        VAR rawbytes rx_raw;
        VAR num n_bytes;
        VAR num len_hdr;
        VAR num len_body;
        VAR num p_params;
        VAR string hdr;
        VAR string body;

        WHILE TRUE DO
            ClearRawBytes rx_raw;
            SocketReceive client_socket \RawData:=rx_raw \Time:=RECV_TIMEOUT;
            n_bytes := RawBytesLen(rx_raw);

            IF n_bytes >= 2 THEN
                len_hdr := n_bytes;
                IF len_hdr > 80 THEN
                    len_hdr := 80;
                ENDIF
                UnpackRawBytes rx_raw, 1, hdr \ASCII:=len_hdr;

                body := hdr;
                IF StrLen(hdr) >= 8 THEN
                    ! En RAPID StrMatch retorna StrLen + 1 cuando no hay coincidencia
                    p_params := StrMatch(hdr, 1, """params""");
                    IF p_params <= StrLen(hdr) AND p_params <= n_bytes THEN
                        len_body := n_bytes - p_params + 1;
                        IF len_body > 80 THEN
                            len_body := 80;
                        ENDIF
                        UnpackRawBytes rx_raw, p_params, body \ASCII:=len_body;
                    ENDIF
                ENDIF

                ProcessFrame hdr, body;
            ENDIF
        ENDWHILE
    ERROR
        IF ERRNO = ERR_SOCK_TIMEOUT THEN
            RETRY;
        ELSE
            RETURN;
        ENDIF
    ENDPROC

    LOCAL PROC ProcessFrame(string hdr, string body)
        VAR num msg_id := 0;
        VAR num p_id := 0;

        IF StrLen(hdr) < 10 THEN
            RETURN;
        ENDIF

        p_id := StrMatch(hdr, 1, """id"":");
        IF p_id <= StrLen(hdr) THEN
            msg_id := ExtractNumber(hdr, p_id + 5);
        ENDIF

        IF NOT Contains(hdr, """cmd"":""") THEN
            SendError msg_id, "FORMATO_INVALIDO_FALTA_CMD";
            RETURN;
        ENDIF

        IF Contains(hdr, """cmd"":""PING""") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":""PONG"",""error"":null}\0A");

        ELSEIF Contains(hdr, """cmd"":""STOP""") THEN
            StopMove \Quick;
            ClearPath;
            StartMove;
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":""STOPPED"",""error"":null}\0A");

        ELSEIF Contains(hdr, """cmd"":""GET_STATUS""") THEN
            HandleGetStatus msg_id;

        ELSEIF Contains(hdr, """cmd"":""GET_JOINTS""") THEN
            HandleGetJoints msg_id;

        ELSEIF Contains(hdr, """cmd"":""MOVE_JOINTS""") THEN
            HandleMoveJoints body, msg_id;

        ELSEIF Contains(hdr, """cmd"":""MOVE_PRESET""") THEN
            HandleMovePreset body, msg_id;

        ELSEIF Contains(hdr, """cmd"":""GET_DI""") THEN
            HandleGetDI body, msg_id;

        ELSEIF Contains(hdr, """cmd"":""GET_DO""") THEN
            HandleGetDO body, msg_id;

        ELSEIF Contains(hdr, """cmd"":""SET_DO""") THEN
            HandleSetDO body, msg_id;

        ELSEIF Contains(hdr, """cmd"":""GET_VARIABLE""") THEN
            HandleGetVar body, msg_id;

        ELSE
            SendError msg_id, "COMANDO_NO_RECONOCIDO";
        ENDIF
    ENDPROC

    LOCAL PROC HandleGetStatus(num msg_id)
        VAR jointtarget jt_curr;
        jt_curr := CJointT();

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",");
        SocketSend client_socket \Str:=("""data"":{""exec_state"":""running"",""mode"":""auto"",""joints"":[");
        SocketSend client_socket \Str:=(NumToStr(jt_curr.robax.rax_1, 2) + "," + NumToStr(jt_curr.robax.rax_2, 2) + "," + NumToStr(jt_curr.robax.rax_3, 2) + ",");
        SocketSend client_socket \Str:=(NumToStr(jt_curr.robax.rax_4, 2) + "," + NumToStr(jt_curr.robax.rax_5, 2) + "," + NumToStr(jt_curr.robax.rax_6, 2) + "]},""error"":null}\0A");
    ERROR
        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",");
        SocketSend client_socket \Str:=("""data"":{""exec_state"":""running"",""mode"":""auto""},""error"":null}\0A");
        RETURN;
    ENDPROC

    LOCAL PROC HandleGetJoints(num msg_id)
        VAR jointtarget jt_curr;
        jt_curr := CJointT();

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":{""joints"":[");
        SocketSend client_socket \Str:=(NumToStr(jt_curr.robax.rax_1, 2) + "," + NumToStr(jt_curr.robax.rax_2, 2) + "," + NumToStr(jt_curr.robax.rax_3, 2) + ",");
        SocketSend client_socket \Str:=(NumToStr(jt_curr.robax.rax_4, 2) + "," + NumToStr(jt_curr.robax.rax_5, 2) + "," + NumToStr(jt_curr.robax.rax_6, 2) + "]},""error"":null}\0A");
    ERROR
        SendError msg_id, "ERROR_LECTURA_ARTICULACIONES";
        RETURN;
    ENDPROC

    LOCAL PROC HandleMoveJoints(string body, num msg_id)
        VAR num p_curr := 0;
        VAR num p_spd := 0;
        VAR num spd_val := 100;
        VAR num q1 := 0;
        VAR num q2 := 0;
        VAR num q3 := 0;
        VAR num q4 := 0;
        VAR num q5 := 0;
        VAR num q6 := 0;
        VAR speeddata spd;
        VAR jointtarget target_jt;

        IF StrLen(body) < 12 THEN
            SendError msg_id, "PARAMETRO_JOINTS_FALTANTE";
            RETURN;
        ENDIF

        p_curr := StrMatch(body, 1, "[");
        IF p_curr >= StrLen(body) THEN
            SendError msg_id, "PARAMETRO_JOINTS_FALTANTE";
            RETURN;
        ENDIF

        p_curr := p_curr + 1;
        q1 := ExtractFloat(body, p_curr);

        p_curr := NextComma(body, p_curr);
        IF p_curr = 0 THEN SendError msg_id, "ERROR_PARSE_Q2"; RETURN; ENDIF
        q2 := ExtractFloat(body, p_curr);

        p_curr := NextComma(body, p_curr);
        IF p_curr = 0 THEN SendError msg_id, "ERROR_PARSE_Q3"; RETURN; ENDIF
        q3 := ExtractFloat(body, p_curr);

        p_curr := NextComma(body, p_curr);
        IF p_curr = 0 THEN SendError msg_id, "ERROR_PARSE_Q4"; RETURN; ENDIF
        q4 := ExtractFloat(body, p_curr);

        p_curr := NextComma(body, p_curr);
        IF p_curr = 0 THEN SendError msg_id, "ERROR_PARSE_Q5"; RETURN; ENDIF
        q5 := ExtractFloat(body, p_curr);

        p_curr := NextComma(body, p_curr);
        IF p_curr = 0 THEN SendError msg_id, "ERROR_PARSE_Q6"; RETURN; ENDIF
        q6 := ExtractFloat(body, p_curr);

        IF q1 < -180 OR q1 > 180 OR q2 < -90 OR q2 > 110 OR q3 < -230 OR q3 > 50 OR q4 < -200 OR q4 > 200 OR q5 < -115 OR q5 > 115 OR q6 < -400 OR q6 > 400 THEN
            SendError msg_id, "LIMITES_ARTICULARES_EXCEDIDOS";
            RETURN;
        ENDIF

        spd := v500;
        p_spd := StrMatch(body, 1, """speed"":");
        IF p_spd <= StrLen(body) THEN
            spd_val := ExtractFloat(body, p_spd + 8);
            IF spd_val <= 50 THEN
                spd := v50;
            ELSEIF spd_val <= 100 THEN
                spd := v100;
            ELSEIF spd_val <= 200 THEN
                spd := v200;
            ELSEIF spd_val <= 500 THEN
                spd := v500;
            ELSE
                spd := v1000;
            ENDIF
        ENDIF

        target_jt := [[q1, q2, q3, q4, q5, q6], [9E+9, 9E+9, 9E+9, 9E+9, 9E+9, 9E+9]];
        MoveAbsJ target_jt, spd, z10, tool0;
        cycle_counter := cycle_counter + 1;

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",");
        SocketSend client_socket \Str:=("""data"":{""state"":""COMPLETED"",""joints"":[");
        SocketSend client_socket \Str:=(NumToStr(q1, 2) + "," + NumToStr(q2, 2) + "," + NumToStr(q3, 2) + ",");
        SocketSend client_socket \Str:=(NumToStr(q4, 2) + "," + NumToStr(q5, 2) + "," + NumToStr(q6, 2) + "]},""error"":null}\0A");
    ERROR
        SendError msg_id, "FALLO_EJECUCION_MOVIMIENTO";
        RETURN;
    ENDPROC

    LOCAL PROC HandleMovePreset(string body, num msg_id)
        VAR jointtarget target_jt;
        VAR string preset_name := "";

        IF Contains(body, """HOME""") THEN
            target_jt := JT_HOME;
            preset_name := "HOME";
        ELSEIF Contains(body, """TEST_DELTA_J1""") THEN
            target_jt := JT_DELTA_J1;
            preset_name := "TEST_DELTA_J1";
        ELSEIF Contains(body, """TEST_SAFE_1""") THEN
            target_jt := JT_SAFE_1;
            preset_name := "TEST_SAFE_1";
        ELSE
            SendError msg_id, "PRESET_NO_AUTORIZADO";
            RETURN;
        ENDIF

        MoveAbsJ target_jt, v100, fine, tool0;
        cycle_counter := cycle_counter + 1;

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",");
        SocketSend client_socket \Str:=("""data"":{""state"":""COMPLETED"",""target"":""" + preset_name + """},""error"":null}\0A");
    ERROR
        SendError msg_id, "FALLO_EJECUCION_PRESET";
        RETURN;
    ENDPROC

    LOCAL PROC HandleGetDI(string body, num msg_id)
        IF Contains(body, "di_pieza_presente") OR Contains(body, "di_robot_listo") OR Contains(body, "di_pinza_abierta") OR Contains(body, "di1") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":1,""error"":null}\0A");
        ELSEIF Contains(body, "di_sensor_inductivo") OR Contains(body, "di_sensor_capacitivo") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":0,""error"":null}\0A");
        ELSEIF Contains(body, "di_ciclo_inicio") OR Contains(body, "di_parada_celda") OR Contains(body, "di_pinza_cerrada") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":0,""error"":null}\0A");
        ELSE
            SendError msg_id, "SENAL_DI_NO_CONFIGURADA";
        ENDIF
    ENDPROC

    LOCAL PROC HandleGetDO(string body, num msg_id)
        IF Contains(body, "do_indicador_verde") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":1,""error"":null}\0A");
        ELSEIF Contains(body, "do_valvula_aire") OR Contains(body, "do_pinza_actuar") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":0,""error"":null}\0A");
        ELSE
            SendError msg_id, "SENAL_DO_NO_CONFIGURADA";
        ENDIF
    ENDPROC

    LOCAL PROC HandleSetDO(string body, num msg_id)
        VAR num val := 0;

        IF Contains(body, """value"":1") THEN
            val := 1;
        ELSEIF Contains(body, """value"":0") THEN
            val := 0;
        ELSE
            SendError msg_id, "VALOR_DIGITAL_INVALIDO";
            RETURN;
        ENDIF

        IF Contains(body, "do_") OR Contains(body, "do1") OR Contains(body, "do2") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":" + NumToStr(val, 0) + ",""error"":null}\0A");
        ELSE
            SendError msg_id, "SALIDA_NO_AUTORIZADA";
        ENDIF
    ENDPROC

    LOCAL PROC HandleGetVar(string body, num msg_id)
        IF Contains(body, "cycle_counter") OR Contains(body, "cycle_count") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":" + NumToStr(cycle_counter, 0) + ",""error"":null}\0A");
        ELSEIF Contains(body, "current_speed") OR Contains(body, "speed_override") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":" + NumToStr(current_speed, 0) + ",""error"":null}\0A");
        ELSE
            SendError msg_id, "VARIABLE_NO_ENCONTRADA";
        ENDIF
    ENDPROC

    LOCAL PROC SendError(num msg_id, string err_desc)
        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""ERROR"",""data"":null,");
        SocketSend client_socket \Str:=("""error"":""" + err_desc + """}\0A");
    ENDPROC

    LOCAL FUNC bool Contains(string s, string pat)
        IF StrLen(s) = 0 OR StrLen(pat) = 0 OR StrLen(pat) > StrLen(s) THEN
            RETURN FALSE;
        ENDIF
        RETURN StrMatch(s, 1, pat) <= StrLen(s);
    ENDFUNC

    LOCAL FUNC num NextComma(string s, num idx)
        VAR num p;
        IF idx < 1 OR idx > StrLen(s) THEN
            RETURN 0;
        ENDIF
        p := StrMatch(s, idx, ",");
        IF p >= StrLen(s) THEN
            RETURN 0;
        ENDIF
        RETURN p + 1;
    ENDFUNC

    LOCAL FUNC num ExtractNumber(string s, num start_idx)
        VAR string digit_str := "";
        VAR string c := "";
        VAR num i;
        VAR num val := 0;
        VAR bool ok := FALSE;

        IF start_idx < 1 OR start_idx > StrLen(s) THEN
            RETURN 0;
        ENDIF

        i := start_idx;
        WHILE i <= StrLen(s) DO
            c := StrPart(s, i, 1);
            ! StrFind retorna 1..10 si el digito pertenece al conjunto y 11 si no pertenece
            IF StrFind("0123456789", 1, c) <= 10 THEN
                digit_str := digit_str + c;
            ELSEIF StrLen(digit_str) > 0 THEN
                i := StrLen(s) + 1;
            ENDIF
            i := i + 1;
        ENDWHILE

        IF StrLen(digit_str) > 0 THEN
            ok := StrToVal(digit_str, val);
        ENDIF
        RETURN val;
    ENDFUNC

    LOCAL FUNC num ExtractFloat(string s, num start_idx)
        VAR string num_str := "";
        VAR string c := "";
        VAR num i;
        VAR num val := 0;
        VAR bool ok := FALSE;

        IF start_idx < 1 OR start_idx > StrLen(s) THEN
            RETURN 0;
        ENDIF

        i := start_idx;
        WHILE i <= StrLen(s) DO
            c := StrPart(s, i, 1);
            IF c = "-" OR c = "." OR StrFind("0123456789", 1, c) <= 10 THEN
                num_str := num_str + c;
            ELSEIF StrLen(num_str) > 0 THEN
                i := StrLen(s) + 1;
            ENDIF
            i := i + 1;
        ENDWHILE

        IF StrLen(num_str) > 0 THEN
            ok := StrToVal(num_str, val);
        ENDIF
        RETURN val;
    ENDFUNC

ENDMODULE
