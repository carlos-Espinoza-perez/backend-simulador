import re
import math
from typing import List, Dict, Any, Tuple, Optional, Union

def _strip_comments(text: str) -> str:
    result = []
    in_string = False
    for ch in text:
        if ch == '"':
            in_string = not in_string
        if ch == '!' and not in_string:
            break
        result.append(ch)
    return ''.join(result)

class Token:
    def __init__(self, ttype: str, val: Any, line: int):
        self.type = ttype
        self.val = val
        self.line = line

    def __repr__(self):
        return f"Token({self.type}, {repr(self.val)})"

class Lexer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.length = len(text)

    def tokenize(self) -> List[Token]:
        tokens = []
        while self.pos < self.length:
            ch = self.text[self.pos]

            if ch == '\n':
                self.line += 1
                self.pos += 1
                continue
            elif ch.isspace():
                self.pos += 1
                continue
            elif ch == '!':
                while self.pos < self.length and self.text[self.pos] != '\n':
                    self.pos += 1
                continue

            if ch == '"':
                start = self.pos + 1
                self.pos += 1
                while self.pos < self.length and self.text[self.pos] != '"':
                    if self.text[self.pos] == '\n':
                        self.line += 1
                    self.pos += 1
                val = self.text[start:self.pos]
                self.pos += 1
                tokens.append(Token('STRING', val, self.line))
                continue

            if ch == ':' and self.pos + 1 < self.length and self.text[self.pos + 1] == '=':
                tokens.append(Token('ASSIGN', ':=', self.line))
                self.pos += 2
                continue
            elif ch == '<' and self.pos + 1 < self.length and self.text[self.pos + 1] == '>':
                tokens.append(Token('NEQ', '<>', self.line))
                self.pos += 2
                continue
            elif ch == '<' and self.pos + 1 < self.length and self.text[self.pos + 1] == '=':
                tokens.append(Token('LTE', '<=', self.line))
                self.pos += 2
                continue
            elif ch == '>' and self.pos + 1 < self.length and self.text[self.pos + 1] == '=':
                tokens.append(Token('GTE', '>=', self.line))
                self.pos += 2
                continue

            if ch in '();,[]':
                tokens.append(Token(ch, ch, self.line))
                self.pos += 1
                continue
            elif ch in '+-*/=<>':
                tokens.append(Token(ch, ch, self.line))
                self.pos += 1
                continue
            elif ch == '\\':
                self.pos += 1
                while self.pos < self.length and (self.text[self.pos].isalnum() or self.text[self.pos] == '_'):
                    self.pos += 1
                continue

            if ch.isdigit() or (ch == '.' and self.pos + 1 < self.length and self.text[self.pos + 1].isdigit()):
                start = self.pos
                while self.pos < self.length and (self.text[self.pos].isdigit() or self.text[self.pos] == '.'):
                    self.pos += 1
                if self.pos < self.length and self.text[self.pos] in 'eE':
                    self.pos += 1
                    if self.pos < self.length and self.text[self.pos] in '+-':
                        self.pos += 1
                    while self.pos < self.length and self.text[self.pos].isdigit():
                        self.pos += 1
                num_str = self.text[start:self.pos]
                num_val = float(num_str) if '.' in num_str or 'e' in num_str.lower() else int(num_str)
                tokens.append(Token('NUM', num_val, self.line))
                continue

            if ch.isalpha() or ch == '_':
                start = self.pos
                while self.pos < self.length and (self.text[self.pos].isalnum() or self.text[self.pos] == '_'):
                    self.pos += 1
                ident = self.text[start:self.pos]
                upper = ident.upper()
                tokens.append(Token('KEYWORD' if upper in KEYWORDS else 'ID', ident, self.line))
                continue

            self.pos += 1

        tokens.append(Token('EOF', None, self.line))
        return tokens

KEYWORDS = {
    'MODULE', 'ENDMODULE', 'PROC', 'ENDPROC', 'FUNC', 'ENDFUNC',
    'CONST', 'VAR', 'PERS', 'LOCAL',
    'FOR', 'FROM', 'TO', 'STEP', 'DO', 'ENDFOR',
    'WHILE', 'ENDWHILE', 'IF', 'THEN', 'ELSEIF', 'ELSE', 'ENDIF',
    'TEST', 'CASE', 'DEFAULT', 'ENDTEST', 'RETURN', 'GOTO',
    'MOVEJ', 'MOVEL', 'MOVEC', 'MOVEABSJ',
    'WAITTIME', 'WAITDI', 'WAITDO', 'SETDO', 'RESET', 'PULSEDO',
    'TPWRITE', 'INCR', 'DECR',
    'ROBTARGET', 'JOINTTARGET', 'NUM', 'BOOL', 'STRING', 'SPEEDDATA', 'ZONEDATA', 'TOOLDATA', 'WOBJDATA',
    'AND', 'OR', 'NOT', 'TRUE', 'FALSE'
}

def rotate_vector_by_quaternion(q: List[float], v: List[float]) -> List[float]:
    w, x, y, z = q[0], q[1], q[2], q[3]
    qv = [x, y, z]
    t0 = 2.0 * (qv[1] * v[2] - qv[2] * v[1])
    t1 = 2.0 * (qv[2] * v[0] - qv[0] * v[2])
    t2 = 2.0 * (qv[0] * v[1] - qv[1] * v[0])
    
    v_prime = [
        v[0] + w * t0 + (qv[1] * t2 - qv[2] * t1),
        v[1] + w * t1 + (qv[2] * t0 - qv[0] * t2),
        v[2] + w * t2 + (qv[0] * t1 - qv[1] * t0)
    ]
    return v_prime

MOTION_TYPE_MAP = {
    "MOVEJ": "MoveJ",
    "MOVEL": "MoveL",
    "MOVEC": "MoveC",
    "MOVEABSJ": "MoveAbsJ"
}

class RapidParser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.idx = 0
        self.length = len(tokens)

    def cur(self) -> Token:
        return self.tokens[self.idx] if self.idx < self.length else self.tokens[-1]

    def peek(self, n=1) -> Token:
        pos = self.idx + n
        return self.tokens[pos] if pos < self.length else self.tokens[-1]

    def eat(self, expected=None) -> Token:
        t = self.cur()
        if expected:
            if isinstance(expected, list):
                if t.type not in expected and t.val.upper() not in [x.upper() for x in expected]:
                    raise SyntaxError(f"Linea {t.line}: Se esperaba uno de {expected}, se encontro {t.val}")
            else:
                if t.type != expected and (not isinstance(t.val, str) or t.val.upper() != expected.upper()):
                    raise SyntaxError(f"Linea {t.line}: Se esperaba {expected}, se encontro {t.val}")
        self.idx += 1
        return t

    def match(self, val_or_type: str) -> bool:
        t = self.cur()
        if t.type == val_or_type:
            return True
        if isinstance(t.val, str) and t.val.upper() == val_or_type.upper():
            return True
        return False

    def skip_semis(self):
        while self.match(';'):
            self.eat(';')

    def parse_program(self) -> Dict[str, Any]:
        module_name = "Unknown"
        declarations = []
        procedures = {}

        self.skip_semis()
        if self.match('MODULE'):
            self.eat('MODULE')
            module_name = self.eat('ID').val
            self.skip_semis()

        while not self.match('EOF') and not self.match('ENDMODULE'):
            self.skip_semis()
            if self.match('ENDMODULE') or self.match('EOF'):
                break

            if self.match('CONST') or self.match('VAR') or self.match('PERS') or self.match('LOCAL'):
                decl = self.parse_declaration()
                declarations.append(decl)
            elif self.match('PROC'):
                proc = self.parse_procedure()
                procedures[proc['name'].lower()] = proc
            else:
                self.eat()

        return {
            "module": module_name,
            "declarations": declarations,
            "procedures": procedures
        }

    def parse_declaration(self) -> Dict[str, Any]:
        kind = self.eat().val.upper()
        if kind == 'LOCAL':
            kind = f"LOCAL_{self.eat().val.upper()}"
        
        dtype = self.eat().val.lower()
        name = self.eat('ID').val
        val_expr = None
        if self.match('ASSIGN'):
            self.eat('ASSIGN')
            val_expr = self.parse_expression()
        self.skip_semis()
        return {
            "kind": kind,
            "type": dtype,
            "name": name,
            "expr": val_expr
        }

    def parse_procedure(self) -> Dict[str, Any]:
        self.eat('PROC')
        name = self.eat('ID').val
        params = []
        if self.match('('):
            self.eat('(')
            while not self.match(')') and not self.match('EOF'):
                pname = self.eat().val
                params.append(pname)
                if self.match(','):
                    self.eat(',')
            self.eat(')')
        self.skip_semis()

        body = []
        while not self.match('ENDPROC') and not self.match('EOF'):
            self.skip_semis()
            if self.match('ENDPROC') or self.match('EOF'):
                break
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
        
        if self.match('ENDPROC'):
            self.eat('ENDPROC')
        self.skip_semis()

        return {
            "name": name,
            "params": params,
            "body": body
        }

    def parse_statement(self) -> Optional[Dict[str, Any]]:
        self.skip_semis()
        t = self.cur()

        if self.match('FOR'):
            return self.parse_for()
        if self.match('WHILE'):
            return self.parse_while()
        if self.match('IF'):
            return self.parse_if()
        if self.match('MOVEJ') or self.match('MOVEL') or self.match('MOVEC') or self.match('MOVEABSJ'):
            return self.parse_motion()
        if self.match('WAITTIME'):
            self.eat('WAITTIME')
            time_expr = self.parse_expression()
            self.skip_semis()
            return {"type": "WaitTime", "expr": time_expr}
        if self.match('WAITDI'):
            self.eat('WAITDI')
            sig = self.eat().val
            self.eat(',')
            val_expr = self.parse_expression()
            self.skip_semis()
            return {"type": "WaitDI", "signal": sig, "expr": val_expr}
        if self.match('SETDO'):
            self.eat('SETDO')
            sig = self.eat().val
            self.eat(',')
            val_expr = self.parse_expression()
            self.skip_semis()
            return {"type": "SetDO", "signal": sig, "expr": val_expr}
        if self.match('RESET'):
            self.eat('RESET')
            sig = self.eat().val
            self.skip_semis()
            return {"type": "Reset", "signal": sig, "value": 0}
        if self.match('PULSEDO'):
            self.eat('PULSEDO')
            sig = self.eat().val
            self.skip_semis()
            return {"type": "PulseDO", "signal": sig}
        if self.match('TPWRITE'):
            self.eat('TPWRITE')
            msg_expr = self.parse_expression()
            self.skip_semis()
            return {"type": "TPWrite", "expr": msg_expr}
        if self.match('INCR'):
            self.eat('INCR')
            vname = self.eat('ID').val
            self.skip_semis()
            return {"type": "Incr", "name": vname}
        if self.match('DECR'):
            self.eat('DECR')
            vname = self.eat('ID').val
            self.skip_semis()
            return {"type": "Decr", "name": vname}

        if t.type == 'ID':
            nxt = self.peek()
            if nxt.type == 'ASSIGN':
                name = self.eat('ID').val
                self.eat('ASSIGN')
                expr = self.parse_expression()
                self.skip_semis()
                return {"type": "Assign", "name": name, "expr": expr}
            elif nxt.type == '(':
                pname = self.eat('ID').val
                self.eat('(')
                args = []
                while not self.match(')') and not self.match('EOF'):
                    args.append(self.parse_expression())
                    if self.match(','):
                        self.eat(',')
                self.eat(')')
                self.skip_semis()
                return {"type": "Call", "name": pname, "args": args}
            else:
                pname = self.eat('ID').val
                self.skip_semis()
                return {"type": "Call", "name": pname, "args": []}

        self.eat()
        return None

    def parse_for(self) -> Dict[str, Any]:
        self.eat('FOR')
        var_name = self.eat('ID').val
        self.eat('FROM')
        start_expr = self.parse_expression()
        self.eat('TO')
        end_expr = self.parse_expression()
        step_expr = None
        if self.match('STEP'):
            self.eat('STEP')
            step_expr = self.parse_expression()
        self.eat('DO')
        self.skip_semis()

        body = []
        while not self.match('ENDFOR') and not self.match('EOF'):
            self.skip_semis()
            if self.match('ENDFOR') or self.match('EOF'):
                break
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
        if self.match('ENDFOR'):
            self.eat('ENDFOR')
        self.skip_semis()

        return {
            "type": "For",
            "var": var_name,
            "start": start_expr,
            "end": end_expr,
            "step": step_expr,
            "body": body
        }

    def parse_while(self) -> Dict[str, Any]:
        self.eat('WHILE')
        cond = self.parse_expression()
        self.eat('DO')
        self.skip_semis()

        body = []
        while not self.match('ENDWHILE') and not self.match('EOF'):
            self.skip_semis()
            if self.match('ENDWHILE') or self.match('EOF'):
                break
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
        if self.match('ENDWHILE'):
            self.eat('ENDWHILE')
        self.skip_semis()

        return {
            "type": "While",
            "condition": cond,
            "body": body
        }

    def parse_if(self) -> Dict[str, Any]:
        self.eat('IF')
        cond = self.parse_expression()
        self.eat('THEN')
        self.skip_semis()

        branches = [(cond, [])]
        else_branch = []

        while not self.match('ENDIF') and not self.match('EOF'):
            self.skip_semis()
            if self.match('ELSEIF'):
                self.eat('ELSEIF')
                e_cond = self.parse_expression()
                self.eat('THEN')
                self.skip_semis()
                branches.append((e_cond, []))
                continue
            elif self.match('ELSE'):
                self.eat('ELSE')
                self.skip_semis()
                while not self.match('ENDIF') and not self.match('EOF'):
                    self.skip_semis()
                    if self.match('ENDIF') or self.match('EOF'):
                        break
                    stmt = self.parse_statement()
                    if stmt:
                        else_branch.append(stmt)
                break
            elif self.match('ENDIF'):
                break

            stmt = self.parse_statement()
            if stmt:
                branches[-1][1].append(stmt)

        if self.match('ENDIF'):
            self.eat('ENDIF')
        self.skip_semis()

        return {
            "type": "If",
            "branches": branches,
            "else": else_branch
        }

    def parse_motion(self) -> Dict[str, Any]:
        mtype = self.eat().val
        upper = mtype.upper()

        if upper == 'MOVEC':
            via_expr = self.parse_expression()
            self.eat(',')
            to_expr = self.parse_expression()
            self.eat(',')
            speed = self.parse_expression()
            self.eat(',')
            zone = self.parse_expression()
            self.eat(',')
            tool = self.parse_expression()
            self.skip_semis()
            return {
                "type": "MoveC",
                "via": via_expr,
                "to": to_expr,
                "speed": speed,
                "zone": zone,
                "tool": tool
            }

        target_expr = self.parse_expression()
        self.eat(',')
        speed = self.parse_expression()
        self.eat(',')
        zone = self.parse_expression()
        self.eat(',')
        tool = self.parse_expression()
        self.skip_semis()

        return {
            "type": upper,
            "target": target_expr,
            "speed": speed,
            "zone": zone,
            "tool": tool
        }

    def parse_expression(self) -> Any:
        return self.parse_or()

    def parse_or(self) -> Any:
        left = self.parse_and()
        while self.match('OR'):
            op = self.eat('OR').val
            right = self.parse_and()
            left = {"op": "OR", "left": left, "right": right}
        return left

    def parse_and(self) -> Any:
        left = self.parse_comp()
        while self.match('AND'):
            op = self.eat('AND').val
            right = self.parse_comp()
            left = {"op": "AND", "left": left, "right": right}
        return left

    def parse_comp(self) -> Any:
        left = self.parse_additive()
        if self.cur().type in ['=', '<', '>', 'LTE', 'GTE', 'NEQ']:
            op = self.eat().val
            right = self.parse_additive()
            return {"op": op, "left": left, "right": right}
        return left

    def parse_additive(self) -> Any:
        left = self.parse_multiplicative()
        while self.cur().type in ['+', '-']:
            op = self.eat().val
            right = self.parse_multiplicative()
            left = {"op": op, "left": left, "right": right}
        return left

    def parse_multiplicative(self) -> Any:
        left = self.parse_unary()
        while self.cur().type in ['*', '/']:
            op = self.eat().val
            right = self.parse_unary()
            left = {"op": op, "left": left, "right": right}
        return left

    def parse_unary(self) -> Any:
        if self.match('-'):
            self.eat('-')
            operand = self.parse_unary()
            return {"op": "NEG", "operand": operand}
        if self.match('NOT'):
            self.eat('NOT')
            operand = self.parse_unary()
            return {"op": "NOT", "operand": operand}
        return self.parse_primary()

    def parse_primary(self) -> Any:
        t = self.cur()
        if t.type == 'NUM':
            self.eat('NUM')
            return {"type": "Literal", "value": t.val}
        if t.type == 'STRING':
            self.eat('STRING')
            return {"type": "Literal", "value": t.val}
        if self.match('TRUE'):
            self.eat('TRUE')
            return {"type": "Literal", "value": True}
        if self.match('FALSE'):
            self.eat('FALSE')
            return {"type": "Literal", "value": False}
        if self.match('('):
            self.eat('(')
            expr = self.parse_expression()
            self.eat(')')
            return expr
        if self.match('['):
            return self.parse_array_literal()

        if t.type == 'ID' or t.type == 'KEYWORD':
            name = self.eat().val
            if self.match('('):
                self.eat('(')
                args = []
                while not self.match(')') and not self.match('EOF'):
                    args.append(self.parse_expression())
                    if self.match(','):
                        self.eat(',')
                self.eat(')')
                return {"type": "Call", "name": name, "args": args}
            return {"type": "Var", "name": name}

        return {"type": "Literal", "value": self.eat().val}

    def parse_array_literal(self) -> Dict[str, Any]:
        self.eat('[')
        elements = []
        while not self.match(']') and not self.match('EOF'):
            elements.append(self.parse_expression())
            if self.match(','):
                self.eat(',')
        self.eat(']')
        return {"type": "Array", "elements": elements}


class RapidInterpreter:
    def __init__(self, ast: Dict[str, Any]):
        self.ast = ast
        self.globals: Dict[str, Any] = {}
        self.procedures = ast.get("procedures", {})
        self.module_name = ast.get("module", "Unknown")
        self.executed_movements: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.step_count = 0
        self.max_steps = 5000

    def run(self) -> Dict[str, Any]:
        for decl in self.ast.get("declarations", []):
            name = decl["name"]
            val = self.eval_expr(decl["expr"], self.globals) if decl["expr"] else None
            dtype = decl["type"]
            self.globals[name] = self._normalize_data(dtype, val)

        entry_proc = "main"
        if "main" not in self.procedures:
            if self.procedures:
                entry_proc = list(self.procedures.keys())[0]
                self.warnings.append(f"No se encontro PROC main, ejecutando {entry_proc}")
            else:
                return {
                    "success": True,
                    "module": self.module_name,
                    "constants": self.globals,
                    "procedures": [],
                    "movements": [],
                    "total_steps": 0,
                    "warnings": self.warnings
                }

        self.call_procedure(entry_proc, [], {})

        return {
            "success": True,
            "module": self.module_name,
            "constants": self.globals,
            "procedures": list(self.procedures.keys()),
            "movements": self.executed_movements,
            "total_steps": len(self.executed_movements),
            "warnings": self.warnings
        }

    def call_procedure(self, name: str, args: List[Any], parent_env: Dict[str, Any]):
        key = name.lower()
        if key not in self.procedures:
            self.warnings.append(f"Procedimiento '{name}' no encontrado")
            return

        proc = self.procedures[key]
        env = dict(self.globals)
        for param, arg in zip(proc.get("params", []), args):
            env[param] = arg

        self.execute_block(proc.get("body", []), env)

    def execute_block(self, stmts: List[Dict[str, Any]], env: Dict[str, Any]):
        for stmt in stmts:
            if self.step_count >= self.max_steps:
                self.warnings.append("Limite maximo de 5000 pasos alcanzado (seguridad contra bucle infinito)")
                break
            self.step_count += 1
            self.execute_statement(stmt, env)

    def execute_statement(self, stmt: Dict[str, Any], env: Dict[str, Any]):
        stype = stmt.get("type")

        if stype == "Assign":
            val = self.eval_expr(stmt["expr"], env)
            name = stmt["name"]
            env[name] = val
            if name in self.globals:
                self.globals[name] = val

        elif stype == "Incr":
            name = stmt["name"]
            env[name] = env.get(name, 0) + 1
            if name in self.globals:
                self.globals[name] = env[name]

        elif stype == "Decr":
            name = stmt["name"]
            env[name] = env.get(name, 0) - 1
            if name in self.globals:
                self.globals[name] = env[name]

        elif stype == "For":
            start_val = int(self.eval_expr(stmt["start"], env))
            end_val = int(self.eval_expr(stmt["end"], env))
            step_val = int(self.eval_expr(stmt["step"], env)) if stmt.get("step") else 1
            vname = stmt["var"]

            for i in range(start_val, end_val + 1, step_val):
                if self.step_count >= self.max_steps:
                    break
                env[vname] = i
                self.execute_block(stmt.get("body", []), env)

        elif stype == "While":
            while bool(self.eval_expr(stmt["condition"], env)):
                if self.step_count >= self.max_steps:
                    break
                self.execute_block(stmt.get("body", []), env)

        elif stype == "If":
            matched = False
            for cond_expr, body in stmt.get("branches", []):
                if bool(self.eval_expr(cond_expr, env)):
                    self.execute_block(body, env)
                    matched = True
                    break
            if not matched and stmt.get("else"):
                self.execute_block(stmt["else"], env)

        elif stype in ["MOVEJ", "MOVEL", "MOVEABSJ"]:
            target_data = self.eval_expr(stmt["target"], env)
            speed_val = self.eval_expr(stmt["speed"], env)
            zone_val = self.eval_expr(stmt["zone"], env)

            movement = self._format_movement(
                MOTION_TYPE_MAP.get(stype.upper(), stype),
                target_data,
                speed_val,
                zone_val,
                stmt["target"]
            )
            if movement:
                self.executed_movements.append(movement)

        elif stype == "MoveC":
            via_data = self.eval_expr(stmt["via"], env)
            to_data = self.eval_expr(stmt["to"], env)
            speed_val = self.eval_expr(stmt["speed"], env)
            zone_val = self.eval_expr(stmt["zone"], env)

            via_pos, via_quat = self._extract_pose(via_data)
            to_pos, to_quat = self._extract_pose(to_data)

            if via_pos and to_pos:
                self.executed_movements.append({
                    "type": "MoveC",
                    "via_point": "via",
                    "to_point": "to",
                    "via_data": {"position": via_pos, "quaternion": via_quat},
                    "to_data": {"position": to_pos, "quaternion": to_quat},
                    "speed": str(speed_val),
                    "zone": str(zone_val)
                })

        elif stype == "WaitTime":
            t_val = self.eval_expr(stmt["expr"], env)
            self.executed_movements.append({
                "type": "WaitTime",
                "time": float(t_val)
            })

        elif stype == "WaitDI":
            val = self.eval_expr(stmt["expr"], env)
            self.executed_movements.append({
                "type": "WaitDI",
                "signal": stmt["signal"],
                "value": int(val)
            })

        elif stype in ["SetDO", "Reset"]:
            val = self.eval_expr(stmt.get("expr"), env) if "expr" in stmt else stmt.get("value", 0)
            self.executed_movements.append({
                "type": stype,
                "signal": stmt["signal"],
                "value": int(val)
            })

        elif stype == "TPWrite":
            msg = self.eval_expr(stmt["expr"], env)
            self.executed_movements.append({
                "type": "TPWrite",
                "message": str(msg)
            })

        elif stype == "Call":
            arg_vals = [self.eval_expr(arg, env) for arg in stmt.get("args", [])]
            self.call_procedure(stmt["name"], arg_vals, env)

    def eval_expr(self, expr: Any, env: Dict[str, Any]) -> Any:
        if expr is None:
            return None
        if not isinstance(expr, dict):
            return expr

        etype = expr.get("type")
        if etype == "Literal":
            return expr["value"]
        if etype == "Var":
            name = expr["name"]
            return env.get(name, self.globals.get(name, name))
        if etype == "Array":
            return [self.eval_expr(el, env) for el in expr.get("elements", [])]

        if "op" in expr:
            op = expr["op"]
            if op == "NEG":
                return -self.eval_expr(expr["operand"], env)
            if op == "NOT":
                return not self.eval_expr(expr["operand"], env)

            l = self.eval_expr(expr["left"], env)
            r = self.eval_expr(expr["right"], env)

            if op == "+": return l + r
            if op == "-": return l - r
            if op == "*": return l * r
            if op == "/": return l / r if r != 0 else 0
            if op == "=": return l == r
            if op == "<>": return l != r
            if op == "<": return l < r
            if op == "<=": return l <= r
            if op == ">": return l > r
            if op == ">=": return l >= r
            if op == "AND": return bool(l and r)
            if op == "OR": return bool(l or r)

        if etype == "Call":
            fname = expr["name"].upper()
            args = [self.eval_expr(a, env) for a in expr.get("args", [])]

            if fname == "OFFS" and len(args) >= 4:
                return self._eval_offs(args[0], float(args[1]), float(args[2]), float(args[3]))
            if fname == "RELTOOL" and len(args) >= 4:
                return self._eval_reltool(args[0], float(args[1]), float(args[2]), float(args[3]))
            if fname == "SIN": return math.sin(math.radians(float(args[0])))
            if fname == "COS": return math.cos(math.radians(float(args[0])))
            if fname == "SQRT": return math.sqrt(float(args[0]))
            if fname == "ABS": return abs(args[0])
            if fname == "ROUND": return round(args[0])
            if fname == "TRUNC": return math.trunc(args[0])

        return expr

    def _eval_offs(self, target: Any, dx: float, dy: float, dz: float) -> Dict[str, Any]:
        pos, quat = self._extract_pose(target)
        if pos:
            new_pos = [pos[0] + dx, pos[1] + dy, pos[2] + dz]
            return {
                "type": "cartesian",
                "position": new_pos,
                "quaternion": quat or [1.0, 0.0, 0.0, 0.0]
            }
        return target

    def _eval_reltool(self, target: Any, dx: float, dy: float, dz: float) -> Dict[str, Any]:
        pos, quat = self._extract_pose(target)
        if pos and quat:
            rotated_delta = rotate_vector_by_quaternion(quat, [dx, dy, dz])
            new_pos = [pos[0] + rotated_delta[0], pos[1] + rotated_delta[1], pos[2] + rotated_delta[2]]
            return {
                "type": "cartesian",
                "position": new_pos,
                "quaternion": quat
            }
        return target

    def _extract_pose(self, data: Any) -> Tuple[Optional[List[float]], Optional[List[float]]]:
        if isinstance(data, dict):
            if "position" in data:
                return data["position"], data.get("quaternion", [1.0, 0.0, 0.0, 0.0])
            if "data" in data and isinstance(data["data"], dict):
                return data["data"].get("position"), data["data"].get("quaternion")
        elif isinstance(data, list) and len(data) >= 2:
            if isinstance(data[0], list) and isinstance(data[1], list):
                pos = [float(x) for x in data[0][:3]]
                quat = [float(x) for x in data[1][:4]]
                return pos, quat
        return None, None

    def _normalize_data(self, dtype: str, val: Any) -> Any:
        if dtype == "robtarget":
            pos, quat = self._extract_pose(val)
            if pos:
                return {
                    "type": "cartesian",
                    "position": pos,
                    "quaternion": quat or [1.0, 0.0, 0.0, 0.0]
                }
        elif dtype == "jointtarget":
            if isinstance(val, list) and len(val) >= 1 and isinstance(val[0], list):
                return {
                    "type": "joint",
                    "joints": [float(x) for x in val[0]]
                }
            elif isinstance(val, dict) and "joints" in val:
                return val
        return val

    def _format_movement(self, mtype: str, target_data: Any, speed: Any, zone: Any, target_expr: Any) -> Optional[Dict[str, Any]]:
        target_name = target_expr.get("name", "inline") if isinstance(target_expr, dict) else str(target_expr)

        if isinstance(target_data, dict):
            if target_data.get("type") == "joint" or "joints" in target_data:
                return {
                    "type": mtype,
                    "target": target_name,
                    "joints": target_data.get("joints"),
                    "speed": str(speed),
                    "zone": str(zone)
                }
            elif target_data.get("type") == "cartesian" or "position" in target_data:
                return {
                    "type": mtype,
                    "target": target_name,
                    "target_type": "cartesian",
                    "data": {
                        "type": "cartesian",
                        "position": target_data.get("position"),
                        "quaternion": target_data.get("quaternion", [1.0, 0.0, 0.0, 0.0])
                    },
                    "speed": str(speed),
                    "zone": str(zone)
                }

        pos, quat = self._extract_pose(target_data)
        if pos:
            return {
                "type": mtype,
                "target": target_name,
                "target_type": "cartesian",
                "data": {
                    "type": "cartesian",
                    "position": pos,
                    "quaternion": quat or [1.0, 0.0, 0.0, 0.0]
                },
                "speed": str(speed),
                "zone": str(zone)
            }

        return None

def parse_rapid_code(rapid_code: str) -> Dict[str, Any]:
    try:
        lexer = Lexer(rapid_code)
        tokens = lexer.tokenize()
        parser = RapidParser(tokens)
        ast = parser.parse_program()
        interpreter = RapidInterpreter(ast)
        return interpreter.run()
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "movements": [],
            "warnings": [f"Error sintactico RAPID: {e}"]
        }
