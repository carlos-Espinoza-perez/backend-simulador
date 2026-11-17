MODULE IRC5_TcpServer
    ! Servidor TCP para gemelo digital - compatible RobotWare 5 (requiere opcion 616-1 PC Interface)
    ! Bitacora: todo lo recibido, ejecutado y respondido se escribe en la ventana de operador (TPWrite)
    LOCAL VAR socketdev server_socket;
    LOCAL VAR socketdev client_socket;
    LOCAL VAR string client_ip;
    LOCAL VAR bool keep_listening := TRUE;
    LOCAL VAR bool client_bye := FALSE;
    LOCAL VAR num rx_count := 0;

    CONST num SERVER_PORT := 5001;
    CONST num RECV_TIMEOUT := 30;
    ! TRUE: muestra en el FlexPendant cada trama, instruccion y respuesta (incluido PING)
    CONST bool LOG_TP := TRUE;

    PERS num cycle_counter := 0;
    PERS num current_speed := 100;

    CONST jointtarget JT_HOME := [[0,0,0,0,0,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
    CONST jointtarget JT_DELTA_J1 := [[10,0,0,0,0,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];
    CONST jointtarget JT_SAFE_1 := [[0,15,-15,0,30,0],[9E+9,9E+9,9E+9,9E+9,9E+9,9E+9]];

    PROC main()
        TPErase;
        LogTP "=== IRC5_TcpServer (RW5) - bitacora activa ===";
        LogDiag "CFG";
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
            LogTP "Servidor TCP activo en puerto 5001";
        ENDIF
    ENDPROC

    LOCAL PROC AcceptAndServe()
        EnsureServer;
        LogTP "Esperando cliente...";
        SocketAccept server_socket, client_socket \ClientAddress:=client_ip \Time:=WAIT_MAX;
        ErrWrite \I, "IRC5 TCP 5001", "Cliente conectado: " + client_ip;
        LogTP "Cliente conectado: " + client_ip;
        LogDiag "CFG";

        client_bye := FALSE;
        ClientLoop;

        IF SocketGetStatus(client_socket) <> SOCKET_CLOSED THEN
            SocketClose client_socket;
        ENDIF
        ErrWrite \I, "IRC5 TCP 5001", "Cliente desconectado, esperando nueva conexion";
        LogTP "Cliente desconectado";
    ERROR
        IF ERRNO = ERR_SOCK_TIMEOUT THEN
            RETRY;
        ELSE
            LogTP "ERROR socket servidor, errno " + NumToStr(ERRNO, 0) + ". Reiniciando";
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

        WHILE NOT client_bye DO
            ClearRawBytes rx_raw;
            ! WAIT_MAX evita el warning 41581 (ERR_SOCK_TIMEOUT) cada 30s en el registro de eventos
            SocketReceive client_socket \RawData:=rx_raw \Time:=WAIT_MAX;
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

                rx_count := rx_count + 1;
                LogRx hdr, n_bytes;
                ProcessFrame hdr, body;
            ENDIF
        ENDWHILE
    ERROR
        IF ERRNO = ERR_SOCK_TIMEOUT THEN
            RETRY;
        ELSEIF ERRNO = ERR_SOCK_CLOSED THEN
            LogTP "La PC cerro la conexion sin DISCONNECT";
            RETURN;
        ELSE
            LogTP "ERROR en recepcion, errno " + NumToStr(ERRNO, 0);
            RETURN;
        ENDIF
    ENDPROC

    LOCAL PROC ProcessFrame(string hdr, string body)
        VAR num msg_id := 0;
        VAR num p_id := 0;

        IF StrLen(hdr) < 10 THEN
            LogTP "  Trama descartada (muy corta)";
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
            LogTx msg_id, "{""status"":""OK"",""data"":""PONG""}";

        ELSEIF Contains(hdr, """cmd"":""DISCONNECT""") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":""BYE"",""error"":null}\0A");
            LogTx msg_id, "{""status"":""OK"",""data"":""BYE""}";
            client_bye := TRUE;

        ELSEIF Contains(hdr, """cmd"":""STOP""") THEN
            LogTP "EXE StopMove + ClearPath";
            StopMove \Quick;
            ClearPath;
            StartMove;
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":""STOPPED"",""error"":null}\0A");
            LogTx msg_id, "{""status"":""OK"",""data"":""STOPPED""}";

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
        VAR pos p_curr;
        VAR string op_mode := "auto";
        VAR string r_mode := "continuous";
        VAR num ovr := 100;

        IF OpMode() = OP_MAN_PROG THEN
            op_mode := "manual_T1";
        ELSEIF OpMode() = OP_MAN_TEST THEN
            op_mode := "manual_T2";
        ELSEIF OpMode() <> OP_AUTO THEN
            op_mode := "other";
        ENDIF
        IF RunMode() = RUN_STEP_MOVE THEN
            r_mode := "step";
        ENDIF
        ovr := CSpeedOverride();
        jt_curr := CJointT();
        p_curr := CPos(\Tool:=tool0);

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",");
        SocketSend client_socket \Str:=("""data"":{""exec_state"":""running"",""mode"":""" + op_mode + """,""run_mode"":""" + r_mode + """,");
        SocketSend client_socket \Str:=("""speed_override"":" + NumToStr(ovr, 0) + ",""cycle_counter"":" + NumToStr(cycle_counter, 0) + ",");
        SocketSend client_socket \Str:=("""controller"":""IRC5_RW5"",""tcp_mm"":[" + NumToStr(p_curr.x, 1) + "," + NumToStr(p_curr.y, 1) + "," + NumToStr(p_curr.z, 1) + "],");
        SocketSend client_socket \Str:=("""joints"":[" + NumToStr(jt_curr.robax.rax_1, 2) + "," + NumToStr(jt_curr.robax.rax_2, 2) + "," + NumToStr(jt_curr.robax.rax_3, 2) + ",");
        SocketSend client_socket \Str:=(NumToStr(jt_curr.robax.rax_4, 2) + "," + NumToStr(jt_curr.robax.rax_5, 2) + "," + NumToStr(jt_curr.robax.rax_6, 2) + "]},""error"":null}\0A");
        LogTx msg_id, "OK STATUS " + op_mode + " " + NumToStr(ovr, 0) + "%";
        LogJoints "TX#" + NumToStr(msg_id, 0) + " q=", jt_curr;
    ERROR
        SendError msg_id, "ERROR_LECTURA_ESTADO";
        RETURN;
    ENDPROC

    LOCAL PROC HandleGetJoints(num msg_id)
        VAR jointtarget jt_curr;
        jt_curr := CJointT();

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":{""joints"":[");
        SocketSend client_socket \Str:=(NumToStr(jt_curr.robax.rax_1, 2) + "," + NumToStr(jt_curr.robax.rax_2, 2) + "," + NumToStr(jt_curr.robax.rax_3, 2) + ",");
        SocketSend client_socket \Str:=(NumToStr(jt_curr.robax.rax_4, 2) + "," + NumToStr(jt_curr.robax.rax_5, 2) + "," + NumToStr(jt_curr.robax.rax_6, 2) + "]},""error"":null}\0A");
        LogJoints "TX#" + NumToStr(msg_id, 0) + " OK ", jt_curr;
    ERROR
        SendError msg_id, "ERROR_LECTURA_ARTICULACIONES";
        RETURN;
    ENDPROC

    LOCAL PROC HandleMoveJoints(string body, num msg_id)
        VAR num p_curr := 0;
        VAR num p_spd := 0;
        VAR num spd_val := 100;
        VAR string spd_name := "v100";
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

        ! Si "speed" no llega completo (trama recortada a 80 caracteres) se usa v50, la mas lenta
        spd := v50;
        spd_name := "v50";
        p_spd := StrMatch(body, 1, """speed"":");
        IF p_spd <= StrLen(body) THEN
            spd_val := ExtractFloat(body, p_spd + 8);
            IF spd_val <= 50 THEN
                spd := v50;
                spd_name := "v50";
            ELSEIF spd_val <= 100 THEN
                spd := v100;
                spd_name := "v100";
            ELSEIF spd_val <= 200 THEN
                spd := v200;
                spd_name := "v200";
            ELSEIF spd_val <= 500 THEN
                spd := v500;
                spd_name := "v500";
            ELSE
                spd := v1000;
                spd_name := "v1000";
            ENDIF
        ENDIF

        target_jt := [[q1, q2, q3, q4, q5, q6], [9E+9, 9E+9, 9E+9, 9E+9, 9E+9, 9E+9]];
        LogJoints "EXE MoveAbsJ " + spd_name + " ", target_jt;
        ! fine: la respuesta COMPLETED se envia cuando el robot realmente llego al punto
        MoveAbsJ target_jt, spd, fine, tool0;
        cycle_counter := cycle_counter + 1;

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",");
        SocketSend client_socket \Str:=("""data"":{""state"":""COMPLETED"",""joints"":[");
        SocketSend client_socket \Str:=(NumToStr(q1, 2) + "," + NumToStr(q2, 2) + "," + NumToStr(q3, 2) + ",");
        SocketSend client_socket \Str:=(NumToStr(q4, 2) + "," + NumToStr(q5, 2) + "," + NumToStr(q6, 2) + "]},""error"":null}\0A");
        LogTx msg_id, "OK COMPLETED ciclo=" + NumToStr(cycle_counter, 0);
    ERROR
        LogTP "ERR MoveAbsJ errno=" + NumToStr(ERRNO, 0);
        LogDiag "ERR";
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

        LogJoints "EXE Preset " + preset_name + " v100 ", target_jt;
        MoveAbsJ target_jt, v100, fine, tool0;
        cycle_counter := cycle_counter + 1;

        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",");
        SocketSend client_socket \Str:=("""data"":{""state"":""COMPLETED"",""target"":""" + preset_name + """},""error"":null}\0A");
        LogTx msg_id, "OK COMPLETED " + preset_name;
    ERROR
        LogTP "ERR Preset errno=" + NumToStr(ERRNO, 0);
        LogDiag "ERR";
        SendError msg_id, "FALLO_EJECUCION_PRESET";
        RETURN;
    ENDPROC

    ! NOTA: GET_DI / GET_DO / SET_DO aun responden valores fijos (no tocan senales reales del EIO)
    LOCAL PROC HandleGetDI(string body, num msg_id)
        IF Contains(body, "di_pieza_presente") OR Contains(body, "di_robot_listo") OR Contains(body, "di_pinza_abierta") OR Contains(body, "di1") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":1,""error"":null}\0A");
            LogTP "  >> OK DI=1 (simulado)";
        ELSEIF Contains(body, "di_sensor_inductivo") OR Contains(body, "di_sensor_capacitivo") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":0,""error"":null}\0A");
            LogTP "  >> OK DI=0 (simulado)";
        ELSEIF Contains(body, "di_ciclo_inicio") OR Contains(body, "di_parada_celda") OR Contains(body, "di_pinza_cerrada") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":0,""error"":null}\0A");
            LogTP "  >> OK DI=0 (simulado)";
        ELSE
            SendError msg_id, "SENAL_DI_NO_CONFIGURADA";
        ENDIF
    ENDPROC

    LOCAL PROC HandleGetDO(string body, num msg_id)
        IF Contains(body, "do_indicador_verde") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":1,""error"":null}\0A");
            LogTP "  >> OK DO=1 (simulado)";
        ELSEIF Contains(body, "do_valvula_aire") OR Contains(body, "do_pinza_actuar") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":0,""error"":null}\0A");
            LogTP "  >> OK DO=0 (simulado)";
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
            LogTP "  >> OK SET_DO=" + NumToStr(val, 0) + " (simulado)";
        ELSE
            SendError msg_id, "SALIDA_NO_AUTORIZADA";
        ENDIF
    ENDPROC

    LOCAL PROC HandleGetVar(string body, num msg_id)
        IF Contains(body, "cycle_counter") OR Contains(body, "cycle_count") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":" + NumToStr(cycle_counter, 0) + ",""error"":null}\0A");
            LogTP "  >> OK cycle_counter=" + NumToStr(cycle_counter, 0);
        ELSEIF Contains(body, "current_speed") OR Contains(body, "speed_override") THEN
            SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""OK"",""data"":" + NumToStr(current_speed, 0) + ",""error"":null}\0A");
            LogTP "  >> OK current_speed=" + NumToStr(current_speed, 0);
        ELSE
            SendError msg_id, "VARIABLE_NO_ENCONTRADA";
        ENDIF
    ENDPROC

    LOCAL PROC SendError(num msg_id, string err_desc)
        SocketSend client_socket \Str:=("{""id"":" + NumToStr(msg_id, 0) + ",""status"":""ERROR"",""data"":null,");
        SocketSend client_socket \Str:=("""error"":""" + err_desc + """}\0A");
        LogTx msg_id, "ERROR " + err_desc;
    ENDPROC

    ! ---------------- Bitacora (FlexPendant + Salida RobotStudio) ----------------

    LOCAL PROC LogTP(string s)
        VAR string msg;
        VAR string hdr;

        IF NOT LOG_TP RETURN;
        msg := s;
        IF StrLen(msg) > 80 THEN
            msg := StrPart(msg, 1, 80);
        ENDIF
        hdr := msg;
        IF StrLen(hdr) > 40 THEN
            hdr := StrPart(hdr, 1, 40);
        ENDIF
        TPWrite msg;
        ErrWrite \I, hdr, msg;
    ENDPROC

    LOCAL PROC LogTx(num msg_id, string body_txt)
        VAR string prefix;
        VAR string clean;
        VAR num room;

        IF NOT LOG_TP RETURN;
        prefix := "TX#" + NumToStr(msg_id, 0) + " ";
        clean := body_txt;
        room := 80 - StrLen(prefix);
        IF StrLen(clean) > room THEN
            clean := StrPart(clean, 1, room);
        ENDIF
        LogTP prefix + clean;
    ENDPROC

    ! Registra modo de operacion (auto/T1/T2), velocidad % del FlexPendant y modo de ciclo
    LOCAL PROC LogDiag(string tag)
        VAR string m := "auto";
        VAR string r := "cont";
        VAR num ovr := 100;

        IF NOT LOG_TP RETURN;
        IF OpMode() = OP_MAN_PROG THEN
            m := "manual_T1";
        ELSEIF OpMode() = OP_MAN_TEST THEN
            m := "manual_T2";
        ELSEIF OpMode() <> OP_AUTO THEN
            m := "otro";
        ENDIF
        IF RunMode() = RUN_STEP_MOVE THEN
            r := "paso";
        ENDIF
        ovr := CSpeedOverride();
        LogTP tag + " modo=" + m + " vel=" + NumToStr(ovr, 0) + "% ciclo=" + r;
    ENDPROC

    ! Muestra la trama cruda recibida: "RX#12 {"id":12,"cmd":"PING","params":{}}"
    ! Concatenar mas de 80 caracteres en RAPID da error, por eso se recorta ANTES de unir
    LOCAL PROC LogRx(string hdr, num n_bytes)
        VAR string prefix;
        VAR string clean;
        VAR num room;

        IF NOT LOG_TP RETURN;
        prefix := "RX#" + NumToStr(rx_count, 0) + " ";
        clean := CleanLine(hdr);
        room := 80 - StrLen(prefix);
        IF StrLen(clean) > room THEN
            clean := StrPart(clean, 1, room);
        ENDIF
        LogTP prefix + clean;
        IF n_bytes > 80 THEN
            LogTP "  (trama de " + NumToStr(n_bytes, 0) + " bytes, se muestran 80)";
        ENDIF
    ENDPROC

    LOCAL PROC LogJoints(string prefix, jointtarget jt)
        VAR string s;

        IF NOT LOG_TP RETURN;
        s := "[" + NumToStr(jt.robax.rax_1, 1) + "," + NumToStr(jt.robax.rax_2, 1) + "," + NumToStr(jt.robax.rax_3, 1);
        s := s + "," + NumToStr(jt.robax.rax_4, 1) + "," + NumToStr(jt.robax.rax_5, 1) + "," + NumToStr(jt.robax.rax_6, 1) + "]";
        IF StrLen(prefix) + StrLen(s) > 80 THEN
            LogTP prefix;
            LogTP "  " + s;
        ELSE
            LogTP prefix + s;
        ENDIF
    ENDPROC

    ! Quita el salto de linea final (\0A / \0D) para que se vea limpio en pantalla
    LOCAL FUNC string CleanLine(string s)
        VAR string r;
        VAR num p;

        r := s;
        p := StrMatch(r, 1, "\0A");
        IF p <= StrLen(r) THEN
            IF p > 1 THEN
                r := StrPart(r, 1, p - 1);
            ELSE
                r := "";
            ENDIF
        ENDIF
        p := StrMatch(r, 1, "\0D");
        IF p <= StrLen(r) THEN
            IF p > 1 THEN
                r := StrPart(r, 1, p - 1);
            ELSE
                r := "";
            ENDIF
        ENDIF
        RETURN r;
    ENDFUNC

    ! ---------------- Utilidades de parseo ----------------

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
