import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class SQLExecutionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SQLSyntaxError(SQLExecutionError):
    pass


class UnsupportedFeatureError(SQLExecutionError):
    pass


class SQLError(SQLExecutionError):
    pass


class StorageError(Exception):
    pass


def syntax_error(token: str) -> SQLSyntaxError:
    return SQLSyntaxError(f"Error: syntax error near '{token}'")


def unsupported(feature: str) -> UnsupportedFeatureError:
    return UnsupportedFeatureError(f"Error: unsupported feature '{feature}'")


def escape_output_value(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\\", "\\\\")
    s = s.replace("|", "\\|")
    s = s.replace("\n", "\\n")
    return s


def sql_equals(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    return a == b


def compare_values(a: Any, b: Any, op: str) -> bool:
    if a is None or b is None:
        return False
    try:
        if op == "=":
            return a == b
        if op == "!=":
            return a != b
        if op == "<":
            return a < b
        if op == ">":
            return a > b
        if op == "<=":
            return a <= b
        if op == ">=":
            return a >= b
    except TypeError:
        raise SQLError("Error: type error")
    raise SQLError("Error: type error")


@dataclass
class Token:
    type: str
    value: Any
    raw: str
    pos: int


class Lexer:
    KEYWORDS = {
        "CREATE", "TABLE", "DROP", "INSERT", "INTO", "VALUES", "SELECT", "FROM",
        "DELETE", "WHERE", "UPDATE", "SET", "ORDER", "BY", "ASC", "DESC", "LIMIT",
        "OFFSET", "INNER", "LEFT", "JOIN", "ON", "GROUP", "HAVING", "COUNT", "SUM",
        "AVG", "MIN", "MAX", "BEGIN", "COMMIT", "ROLLBACK", "AND", "OR", "NOT",
        "IS", "NULL", "AS", "INTEGER", "REAL", "TEXT",
    }

    def __init__(self, sql: str):
        self.sql = sql
        self.pos = 0
        self.length = len(sql)

    def tokenize(self) -> List[Token]:
        tokens = []
        while self.pos < self.length:
            ch = self.sql[self.pos]
            if ch.isspace():
                self.pos += 1
                continue
            start = self.pos
            if ch in "(),*;":
                token_type = {
                    "(": "LPAREN",
                    ")": "RPAREN",
                    ",": "COMMA",
                    "*": "STAR",
                    ";": "SEMICOLON",
                }[ch]
                tokens.append(Token(token_type, ch, ch, start))
                self.pos += 1
                continue
            if ch == ".":
                tokens.append(Token("DOT", ".", ".", start))
                self.pos += 1
                continue
            if ch in "=<>!":
                if self.pos + 1 < self.length:
                    two = self.sql[self.pos:self.pos + 2]
                    if two in ("!=", "<=", ">="):
                        tokens.append(Token("OP", two, two, start))
                        self.pos += 2
                        continue
                if ch in "=<>":
                    tokens.append(Token("OP", ch, ch, start))
                    self.pos += 1
                    continue
                raise syntax_error(ch)
            if ch == "'":
                self.pos += 1
                chars = []
                while self.pos < self.length:
                    c = self.sql[self.pos]
                    if c == "'":
                        if self.pos + 1 < self.length and self.sql[self.pos + 1] == "'":
                            chars.append("'")
                            self.pos += 2
                            continue
                        self.pos += 1
                        break
                    chars.append(c)
                    self.pos += 1
                else:
                    raise syntax_error("'")
                val = "".join(chars)
                raw = self.sql[start:self.pos]
                tokens.append(Token("STRING", val, raw, start))
                continue
            if ch.isdigit() or (ch == "-" and self.pos + 1 < self.length and self.sql[self.pos + 1].isdigit()):
                m = re.match(r"-?\d+(\.\d+)?", self.sql[self.pos:])
                if not m:
                    raise syntax_error(ch)
                raw = m.group(0)
                self.pos += len(raw)
                if "." in raw:
                    tokens.append(Token("NUMBER", float(raw), raw, start))
                else:
                    tokens.append(Token("NUMBER", int(raw), raw, start))
                continue
            if ch.isalpha() or ch == "_":
                m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", self.sql[self.pos:])
                raw = m.group(0)
                self.pos += len(raw)
                upper = raw.upper()
                if upper in self.KEYWORDS:
                    if upper == "NULL":
                        tokens.append(Token("NULL", None, raw, start))
                    else:
                        tokens.append(Token("KEYWORD", upper, raw, start))
                else:
                    tokens.append(Token("IDENT", raw, raw, start))
                continue
            raise syntax_error(ch)
        tokens.append(Token("EOF", None, "", self.pos))
        return tokens


@dataclass
class ColumnRef:
    table: Optional[str]
    name: str

    @property
    def label(self) -> str:
        return self.name


@dataclass
class Literal:
    value: Any


@dataclass
class UnaryOp:
    op: str
    expr: Any


@dataclass
class BinaryOp:
    left: Any
    op: str
    right: Any


@dataclass
class IsNullOp:
    expr: Any
    negate: bool


@dataclass
class AggregateExpr:
    func: str
    arg: Optional[Any]
    star: bool = False

    @property
    def label(self) -> str:
        if self.star:
            return f"{self.func}(*)"
        if isinstance(self.arg, ColumnRef):
            if self.arg.table:
                return f"{self.func}({self.arg.table}.{self.arg.name})"
            return f"{self.func}({self.arg.name})"
        return f"{self.func}(expr)"


@dataclass
class SelectItem:
    expr: Any
    alias: Optional[str] = None


@dataclass
class JoinSpec:
    join_type: str
    table: str
    on: Any


@dataclass
class CreateTableStmt:
    name: str
    columns: List[Tuple[str, str]]


@dataclass
class DropTableStmt:
    name: str


@dataclass
class InsertStmt:
    table: str
    columns: Optional[List[str]]
    values: List[Any]


@dataclass
class SelectStmt:
    items: List[SelectItem]
    from_table: str
    joins: List[JoinSpec]
    where: Optional[Any]
    group_by: List[ColumnRef]
    having: Optional[Any]
    order_by: List[Tuple[ColumnRef, str]]
    limit: Optional[int]
    offset: int


@dataclass
class DeleteStmt:
    table: str
    where: Optional[Any]


@dataclass
class UpdateStmt:
    table: str
    assignments: List[Tuple[str, Any]]
    where: Optional[Any]


@dataclass
class BeginStmt:
    pass


@dataclass
class CommitStmt:
    pass


@dataclass
class RollbackStmt:
    pass


class Parser:
    AGG_FUNCS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def current(self) -> Token:
        return self.tokens[self.pos]

    def consume(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def match_keyword(self, word: str) -> bool:
        t = self.current()
        if t.type == "KEYWORD" and t.value == word:
            self.pos += 1
            return True
        return False

    def expect_keyword(self, word: str) -> Token:
        t = self.current()
        if t.type == "KEYWORD" and t.value == word:
            self.pos += 1
            return t
        raise syntax_error(t.raw or "EOF")

    def match_type(self, token_type: str) -> Optional[Token]:
        t = self.current()
        if t.type == token_type:
            self.pos += 1
            return t
        return None

    def expect_type(self, token_type: str) -> Token:
        t = self.current()
        if t.type == token_type:
            self.pos += 1
            return t
        raise syntax_error(t.raw or "EOF")

    def parse_identifier(self) -> str:
        t = self.current()
        if t.type in ("IDENT",):
            self.pos += 1
            return t.value
        raise syntax_error(t.raw or "EOF")

    def parse(self) -> Any:
        t = self.current()
        if t.type == "KEYWORD":
            kw = t.value
            if kw == "CREATE":
                stmt = self.parse_create_table()
            elif kw == "DROP":
                stmt = self.parse_drop_table()
            elif kw == "INSERT":
                stmt = self.parse_insert()
            elif kw == "SELECT":
                stmt = self.parse_select()
            elif kw == "DELETE":
                stmt = self.parse_delete()
            elif kw == "UPDATE":
                stmt = self.parse_update()
            elif kw == "BEGIN":
                self.consume()
                stmt = BeginStmt()
            elif kw == "COMMIT":
                self.consume()
                stmt = CommitStmt()
            elif kw == "ROLLBACK":
                self.consume()
                stmt = RollbackStmt()
            else:
                raise syntax_error(t.raw)
        else:
            raise syntax_error(t.raw or "EOF")

        if self.match_type("SEMICOLON"):
            pass
        if self.current().type != "EOF":
            raise syntax_error(self.current().raw or "EOF")
        return stmt

    def parse_create_table(self) -> CreateTableStmt:
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        name = self.parse_identifier()
        self.expect_type("LPAREN")
        cols = []
        while True:
            col_name = self.parse_identifier()
            t = self.current()
            if t.type == "KEYWORD" and t.value in ("INTEGER", "REAL", "TEXT", "NULL"):
                col_type = t.value
                self.consume()
            else:
                raise syntax_error(t.raw or "EOF")
            cols.append((col_name, col_type))
            if self.match_type("COMMA"):
                continue
            break
        self.expect_type("RPAREN")
        return CreateTableStmt(name, cols)

    def parse_drop_table(self) -> DropTableStmt:
        self.expect_keyword("DROP")
        self.expect_keyword("TABLE")
        return DropTableStmt(self.parse_identifier())

    def parse_insert(self) -> InsertStmt:
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.parse_identifier()
        columns = None
        if self.match_type("LPAREN"):
            columns = []
            while True:
                columns.append(self.parse_identifier())
                if self.match_type("COMMA"):
                    continue
                break
            self.expect_type("RPAREN")
        self.expect_keyword("VALUES")
        self.expect_type("LPAREN")
        values = []
        while True:
            values.append(self.parse_literal_value())
            if self.match_type("COMMA"):
                continue
            break
        self.expect_type("RPAREN")
        return InsertStmt(table, columns, values)

    def parse_select(self) -> SelectStmt:
        self.expect_keyword("SELECT")
        items = self.parse_select_list()
        self.expect_keyword("FROM")
        from_table = self.parse_identifier()
        joins = []
        while True:
            if self.match_keyword("INNER"):
                self.expect_keyword("JOIN")
                table = self.parse_identifier()
                self.expect_keyword("ON")
                cond = self.parse_expression()
                joins.append(JoinSpec("INNER", table, cond))
            elif self.match_keyword("LEFT"):
                self.expect_keyword("JOIN")
                table = self.parse_identifier()
                self.expect_keyword("ON")
                cond = self.parse_expression()
                joins.append(JoinSpec("LEFT", table, cond))
            else:
                break
        where = None
        if self.match_keyword("WHERE"):
            where = self.parse_expression()
        group_by = []
        having = None
        if self.match_keyword("GROUP"):
            self.expect_keyword("BY")
            while True:
                group_by.append(self.parse_column_ref())
                if self.match_type("COMMA"):
                    continue
                break
            if self.match_keyword("HAVING"):
                having = self.parse_expression()
        order_by = []
        if self.match_keyword("ORDER"):
            self.expect_keyword("BY")
            while True:
                col = self.parse_column_ref()
                direction = "ASC"
                if self.current().type == "KEYWORD" and self.current().value in ("ASC", "DESC"):
                    direction = self.consume().value
                order_by.append((col, direction))
                if self.match_type("COMMA"):
                    continue
                break
        limit = None
        offset = 0
        if self.match_keyword("LIMIT"):
            tok = self.expect_type("NUMBER")
            if not isinstance(tok.value, int):
                raise syntax_error(tok.raw)
            limit = tok.value
            if self.match_keyword("OFFSET"):
                tok2 = self.expect_type("NUMBER")
                if not isinstance(tok2.value, int):
                    raise syntax_error(tok2.raw)
                offset = tok2.value
        return SelectStmt(items, from_table, joins, where, group_by, having, order_by, limit, offset)

    def parse_delete(self) -> DeleteStmt:
        self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.parse_identifier()
        where = None
        if self.match_keyword("WHERE"):
            where = self.parse_expression()
        return DeleteStmt(table, where)

    def parse_update(self) -> UpdateStmt:
        self.expect_keyword("UPDATE")
        table = self.parse_identifier()
        self.expect_keyword("SET")
        assignments = []
        while True:
            col = self.parse_identifier()
            op = self.expect_type("OP")
            if op.value != "=":
                raise syntax_error(op.raw)
            val = self.parse_literal_value()
            assignments.append((col, val))
            if self.match_type("COMMA"):
                continue
            break
        where = None
        if self.match_keyword("WHERE"):
            where = self.parse_expression()
        return UpdateStmt(table, assignments, where)

    def parse_select_list(self) -> List[SelectItem]:
        items = []
        if self.match_type("STAR"):
            return [SelectItem(ColumnRef(None, "*"))]
        while True:
            expr = self.parse_select_expr()
            alias = None
            if self.match_keyword("AS"):
                alias = self.parse_identifier()
            items.append(SelectItem(expr, alias))
            if self.match_type("COMMA"):
                continue
            break
        return items

    def parse_select_expr(self) -> Any:
        t = self.current()
        if t.type == "KEYWORD" and t.value in self.AGG_FUNCS:
            func = self.consume().value
            self.expect_type("LPAREN")
            if self.match_type("STAR"):
                self.expect_type("RPAREN")
                if func != "COUNT":
                    raise unsupported(f"{func}(*)")
                return AggregateExpr(func, None, True)
            arg = self.parse_column_ref()
            self.expect_type("RPAREN")
            return AggregateExpr(func, arg, False)
        return self.parse_column_ref()

    def parse_literal_value(self) -> Any:
        t = self.current()
        if t.type == "STRING":
            self.consume()
            return t.value
        if t.type == "NUMBER":
            self.consume()
            return t.value
        if t.type == "NULL":
            self.consume()
            return None
        raise syntax_error(t.raw or "EOF")

    def parse_column_ref(self) -> ColumnRef:
        first = self.current()
        if first.type not in ("IDENT",):
            raise syntax_error(first.raw or "EOF")
        name1 = self.consume().value
        if self.match_type("DOT"):
            name2 = self.parse_identifier()
            return ColumnRef(name1, name2)
        return ColumnRef(None, name1)

    def parse_expression(self) -> Any:
        return self.parse_or()

    def parse_or(self) -> Any:
        expr = self.parse_and()
        while self.match_keyword("OR"):
            expr = BinaryOp(expr, "OR", self.parse_and())
        return expr

    def parse_and(self) -> Any:
        expr = self.parse_not()
        while self.match_keyword("AND"):
            expr = BinaryOp(expr, "AND", self.parse_not())
        return expr

    def parse_not(self) -> Any:
        if self.match_keyword("NOT"):
            return UnaryOp("NOT", self.parse_not())
        return self.parse_predicate()

    def parse_predicate(self) -> Any:
        if self.match_type("LPAREN"):
            expr = self.parse_expression()
            self.expect_type("RPAREN")
            return expr
        left = self.parse_operand()
        if self.match_keyword("IS"):
            negate = self.match_keyword("NOT")
            self.expect_type("NULL")
            return IsNullOp(left, negate)
        t = self.current()
        if t.type == "OP":
            op = self.consume().value
            right = self.parse_operand()
            return BinaryOp(left, op, right)
        return left

    def parse_operand(self) -> Any:
        t = self.current()
        if t.type == "IDENT":
            return self.parse_column_ref()
        if t.type == "STRING":
            self.consume()
            return Literal(t.value)
        if t.type == "NUMBER":
            self.consume()
            return Literal(t.value)
        if t.type == "NULL":
            self.consume()
            return Literal(None)
        if t.type == "LPAREN":
            self.consume()
            expr = self.parse_expression()
            self.expect_type("RPAREN")
            return expr
        raise syntax_error(t.raw or "EOF")


class StorageEngine:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {"tables": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "tables" not in data:
                raise StorageError("Invalid database file")
            return data
        except OSError as e:
            raise StorageError(str(e))
        except json.JSONDecodeError as e:
            raise StorageError(str(e))

    def save(self, data: Dict[str, Any]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".mini_sqlite_", dir=directory, text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise
        except OSError as e:
            raise StorageError(str(e))


class Database:
    def __init__(self, storage: StorageEngine):
        self.storage = storage
        self.data = self.storage.load()
        self.in_transaction = False
        self.tx_backup = None

    def begin(self) -> None:
        if self.in_transaction:
            raise unsupported("nested transactions")
        self.tx_backup = json.loads(json.dumps(self.data))
        self.in_transaction = True

    def commit(self) -> None:
        if not self.in_transaction:
            self.storage.save(self.data)
            return
        self.storage.save(self.data)
        self.tx_backup = None
        self.in_transaction = False

    def rollback(self) -> None:
        if not self.in_transaction:
            return
        self.data = self.tx_backup
        self.tx_backup = None
        self.in_transaction = False

    def maybe_autosave(self) -> None:
        if not self.in_transaction:
            self.storage.save(self.data)

    def get_table(self, name: str) -> Dict[str, Any]:
        tables = self.data["tables"]
        if name not in tables:
            raise SQLError(f"Error: no such table: {name}")
        return tables[name]

    def create_table(self, name: str, columns: List[Tuple[str, str]]) -> None:
        if name in self.data["tables"]:
            raise SQLError(f"Error: table already exists: {name}")
        seen = set()
        cols = []
        for col_name, col_type in columns:
            if col_name in seen:
                raise SQLError(f"Error: duplicate column: {col_name}")
            seen.add(col_name)
            cols.append({"name": col_name, "type": col_type})
        self.data["tables"][name] = {"columns": cols, "rows": [], "next_rowid": 1}
        self.maybe_autosave()

    def drop_table(self, name: str) -> None:
        if name not in self.data["tables"]:
            raise SQLError(f"Error: no such table: {name}")
        del self.data["tables"][name]
        self.maybe_autosave()


class Executor:
    def __init__(self, db: Database):
        self.db = db

    def execute(self, stmt: Any) -> str:
        if isinstance(stmt, CreateTableStmt):
            self.db.create_table(stmt.name, stmt.columns)
            return "OK\n"
        if isinstance(stmt, DropTableStmt):
            self.db.drop_table(stmt.name)
            return "OK\n"
        if isinstance(stmt, InsertStmt):
            self.execute_insert(stmt)
            return "1 row affected\n"
        if isinstance(stmt, SelectStmt):
            return self.execute_select(stmt)
        if isinstance(stmt, DeleteStmt):
            n = self.execute_delete(stmt)
            return f"{n} rows affected\n"
        if isinstance(stmt, UpdateStmt):
            n = self.execute_update(stmt)
            return f"{n} rows affected\n"
        if isinstance(stmt, BeginStmt):
            self.db.begin()
            return "OK\n"
        if isinstance(stmt, CommitStmt):
            self.db.commit()
            return "OK\n"
        if isinstance(stmt, RollbackStmt):
            self.db.rollback()
            return "OK\n"
        raise unsupported("statement")

    def execute_insert(self, stmt: InsertStmt) -> None:
        table = self.db.get_table(stmt.table)
        schema_cols = [c["name"] for c in table["columns"]]
        schema_types = {c["name"]: c["type"] for c in table["columns"]}
        if stmt.columns is None:
            if len(stmt.values) != len(schema_cols):
                raise SQLError("Error: column count does not match value count")
            row_values = stmt.values[:]
        else:
            for c in stmt.columns:
                if c not in schema_cols:
                    raise SQLError(f"Error: no such column: {c}")
            if len(stmt.columns) != len(stmt.values):
                raise SQLError("Error: column count does not match value count")
            row_map = {col: None for col in schema_cols}
            for c, v in zip(stmt.columns, stmt.values):
                row_map[c] = self.coerce_value(v, schema_types[c])
            row_values = [row_map[c] for c in schema_cols]
            row = {"_rowid": table["next_rowid"], "_values": row_values}
            table["rows"].append(row)
            table["next_rowid"] += 1
            self.db.maybe_autosave()
            return
        coerced = [self.coerce_value(v, schema_types[c]) for c, v in zip(schema_cols, row_values)]
        row = {"_rowid": table["next_rowid"], "_values": coerced}
        table["rows"].append(row)
        table["next_rowid"] += 1
        self.db.maybe_autosave()

    def coerce_value(self, value: Any, target_type: str) -> Any:
        if value is None:
            return None
        if target_type == "NULL":
            if value is not None:
                raise SQLError("Error: type error")
            return None
        if target_type == "INTEGER":
            if isinstance(value, bool) or not isinstance(value, int):
                raise SQLError("Error: type error")
            return value
        if target_type == "REAL":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SQLError("Error: type error")
            return float(value)
        if target_type == "TEXT":
            if not isinstance(value, str):
                raise SQLError("Error: type error")
            return value
        raise SQLError("Error: type error")

    def build_base_rows(self, table_name: str) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
        table = self.db.get_table(table_name)
        schema = [(table_name, c["name"]) for c in table["columns"]]
        rows = []
        for row in table["rows"]:
            data = {}
            for idx, col in enumerate(table["columns"]):
                data[(table_name, col["name"])] = row["_values"][idx]
            rows.append({"data": data, "_order": row["_rowid"]})
        return rows, schema

    def apply_join(self, left_rows: List[Dict[str, Any]], left_schema: List[Tuple[str, str]], join: JoinSpec) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
        right_table = self.db.get_table(join.table)
        right_schema = [(join.table, c["name"]) for c in right_table["columns"]]
        result = []
        for left in left_rows:
            matched = False
            for right_row in right_table["rows"]:
                combined = dict(left["data"])
                for idx, col in enumerate(right_table["columns"]):
                    combined[(join.table, col["name"])] = right_row["_values"][idx]
                ctx = {"data": combined, "schema": left_schema + right_schema}
                cond = self.eval_condition(join.on, ctx, {})
                if cond:
                    matched = True
                    result.append({"data": combined, "_order": left["_order"]})
            if join.join_type == "LEFT" and not matched:
                combined = dict(left["data"])
                for _, col_name in right_schema:
                    combined[(join.table, col_name)] = None
                result.append({"data": combined, "_order": left["_order"]})
        return result, left_schema + right_schema

    def resolve_column(self, ref: ColumnRef, row_data: Dict[Tuple[str, str], Any], schema: List[Tuple[str, str]]) -> Any:
        if ref.name == "*":
            raise SQLError("Error: no such column: *")
        if ref.table is not None:
            key = (ref.table, ref.name)
            if key not in row_data:
                raise SQLError(f"Error: no such column: {ref.table}.{ref.name}")
            return row_data[key]
        matches = []
        for tbl, col in schema:
            if col == ref.name:
                key = (tbl, col)
                if key in row_data:
                    matches.append(key)
        if not matches:
            raise SQLError(f"Error: no such column: {ref.name}")
        return row_data[matches[0]]

    def eval_expr(self, expr: Any, row_ctx: Dict[str, Any], agg_ctx: Dict[str, Any]) -> Any:
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, ColumnRef):
            return self.resolve_column(expr, row_ctx["data"], row_ctx["schema"])
        if isinstance(expr, AggregateExpr):
            key = id(expr)
            if key not in agg_ctx:
                raise SQLError("Error: aggregate used outside grouping")
            return agg_ctx[key]
        if isinstance(expr, UnaryOp):
            if expr.op == "NOT":
                return not bool(self.eval_expr(expr.expr, row_ctx, agg_ctx))
        if isinstance(expr, BinaryOp):
            if expr.op == "AND":
                return bool(self.eval_expr(expr.left, row_ctx, agg_ctx)) and bool(self.eval_expr(expr.right, row_ctx, agg_ctx))
            if expr.op == "OR":
                return bool(self.eval_expr(expr.left, row_ctx, agg_ctx)) or bool(self.eval_expr(expr.right, row_ctx, agg_ctx))
            left = self.eval_expr(expr.left, row_ctx, agg_ctx)
            right = self.eval_expr(expr.right, row_ctx, agg_ctx)
            return compare_values(left, right, expr.op)
        if isinstance(expr, IsNullOp):
            val = self.eval_expr(expr.expr, row_ctx, agg_ctx)
            res = val is None
            return (not res) if expr.negate else res
        return expr

    def eval_condition(self, expr: Any, row_ctx: Dict[str, Any], agg_ctx: Dict[str, Any]) -> bool:
        val = self.eval_expr(expr, row_ctx, agg_ctx)
        return bool(val)

    def execute_select(self, stmt: SelectStmt) -> str:
        rows, schema = self.build_base_rows(stmt.from_table)
        for join in stmt.joins:
            rows, schema = self.apply_join(rows, schema, join)
        if stmt.where is not None:
            filtered = []
            for row in rows:
                ctx = {"data": row["data"], "schema": schema}
                if self.eval_condition(stmt.where, ctx, {}):
                    filtered.append(row)
            rows = filtered

        select_all = len(stmt.items) == 1 and isinstance(stmt.items[0].expr, ColumnRef) and stmt.items[0].expr.name == "*" and stmt.items[0].expr.table is None

        aggregate_present = self.contains_aggregate_items(stmt.items) or (stmt.having is not None and self.contains_aggregate_expr(stmt.having))
        if stmt.group_by or aggregate_present:
            output_headers, result_rows = self.execute_grouped_select(stmt, rows, schema, select_all)
        else:
            output_headers, result_rows = self.execute_simple_select(stmt, rows, schema, select_all)

        if stmt.order_by:
            for order_col, direction in reversed(stmt.order_by):
                idx = self.find_output_column_index(order_col, output_headers, schema if select_all else None)
                reverse = direction == "DESC"
                result_rows = self.stable_sort_rows(result_rows, idx, reverse)
        if stmt.offset:
            result_rows = result_rows[stmt.offset:]
        if stmt.limit is not None:
            result_rows = result_rows[:stmt.limit]

        lines = ["|".join(output_headers)]
        for row in result_rows:
            lines.append("|".join(escape_output_value(v) for v in row))
        return "\n".join(lines) + "\n"

    def contains_aggregate_items(self, items: List[SelectItem]) -> bool:
        return any(isinstance(it.expr, AggregateExpr) for it in items)

    def contains_aggregate_expr(self, expr: Any) -> bool:
        if isinstance(expr, AggregateExpr):
            return True
        if isinstance(expr, UnaryOp):
            return self.contains_aggregate_expr(expr.expr)
        if isinstance(expr, BinaryOp):
            return self.contains_aggregate_expr(expr.left) or self.contains_aggregate_expr(expr.right)
        if isinstance(expr, IsNullOp):
            return self.contains_aggregate_expr(expr.expr)
        return False

    def execute_simple_select(self, stmt: SelectStmt, rows: List[Dict[str, Any]], schema: List[Tuple[str, str]], select_all: bool) -> Tuple[List[str], List[List[Any]]]:
        if select_all:
            headers = [col for _, col in schema]
            out_rows = []
            for row in rows:
                values = [row["data"][(tbl, col)] for tbl, col in schema]
                out_rows.append(values)
            return headers, out_rows
        headers = []
        for item in stmt.items:
            if item.alias:
                headers.append(item.alias)
            elif isinstance(item.expr, ColumnRef):
                headers.append(item.expr.name)
            elif isinstance(item.expr, AggregateExpr):
                headers.append(item.expr.label)
            else:
                headers.append("expr")
        out_rows = []
        for row in rows:
            ctx = {"data": row["data"], "schema": schema}
            out_rows.append([self.eval_expr(item.expr, ctx, {}) for item in stmt.items])
        return headers, out_rows

    def execute_grouped_select(self, stmt: SelectStmt, rows: List[Dict[str, Any]], schema: List[Tuple[str, str]], select_all: bool) -> Tuple[List[str], List[List[Any]]]:
        if select_all:
            raise unsupported("SELECT * with GROUP BY")
        groups = []
        group_map = {}
        if stmt.group_by:
            for row in rows:
                ctx = {"data": row["data"], "schema": schema}
                key = tuple(self.eval_expr(col, ctx, {}) for col in stmt.group_by)
                if key not in group_map:
                    group_map[key] = []
                    groups.append((key, group_map[key]))
                group_map[key].append(row)
        else:
            groups = [((), rows)]

        headers = []
        for item in stmt.items:
            if item.alias:
                headers.append(item.alias)
            elif isinstance(item.expr, ColumnRef):
                headers.append(item.expr.name)
            elif isinstance(item.expr, AggregateExpr):
                headers.append(item.expr.label)
            else:
                headers.append("expr")

        result_rows = []
        for _, group_rows in groups:
            agg_ctx = self.compute_aggregates(stmt, group_rows, schema)
            rep_row = group_rows[0] if group_rows else {"data": {}, "_order": 0}
            row_ctx = {"data": rep_row["data"], "schema": schema}
            if stmt.having is not None and not self.eval_condition(stmt.having, row_ctx, agg_ctx):
                continue
            out = []
            for item in stmt.items:
                if isinstance(item.expr, ColumnRef):
                    out.append(self.eval_expr(item.expr, row_ctx, agg_ctx))
                else:
                    out.append(self.eval_expr(item.expr, row_ctx, agg_ctx))
            result_rows.append(out)
        return headers, result_rows

    def collect_aggregates(self, expr: Any, out: List[AggregateExpr]) -> None:
        if isinstance(expr, AggregateExpr):
            out.append(expr)
        elif isinstance(expr, UnaryOp):
            self.collect_aggregates(expr.expr, out)
        elif isinstance(expr, BinaryOp):
            self.collect_aggregates(expr.left, out)
            self.collect_aggregates(expr.right, out)
        elif isinstance(expr, IsNullOp):
            self.collect_aggregates(expr.expr, out)

    def compute_aggregates(self, stmt: SelectStmt, group_rows: List[Dict[str, Any]], schema: List[Tuple[str, str]]) -> Dict[str, Any]:
        aggs = []
        for item in stmt.items:
            self.collect_aggregates(item.expr, aggs)
        if stmt.having is not None:
            self.collect_aggregates(stmt.having, aggs)
        result = {}
        seen = set()
        for agg in aggs:
            if id(agg) in seen:
                continue
            seen.add(id(agg))
            values = []
            if agg.star:
                result[id(agg)] = len(group_rows)
                continue
            for row in group_rows:
                ctx = {"data": row["data"], "schema": schema}
                values.append(self.eval_expr(agg.arg, ctx, {}))
            non_null = [v for v in values if v is not None]
            if agg.func == "COUNT":
                result[id(agg)] = len(non_null)
            elif agg.func == "SUM":
                result[id(agg)] = sum(non_null) if non_null else None
            elif agg.func == "AVG":
                result[id(agg)] = (sum(non_null) / len(non_null)) if non_null else None
            elif agg.func == "MIN":
                result[id(agg)] = min(non_null) if non_null else None
            elif agg.func == "MAX":
                result[id(agg)] = max(non_null) if non_null else None
            else:
                raise unsupported(agg.func)
        return result

    def find_output_column_index(self, ref: ColumnRef, headers: List[str], select_all_schema: Optional[List[Tuple[str, str]]]) -> int:
        if select_all_schema is not None:
            if ref.table:
                for i, (tbl, col) in enumerate(select_all_schema):
                    if tbl == ref.table and col == ref.name:
                        return i
            else:
                for i, (_, col) in enumerate(select_all_schema):
                    if col == ref.name:
                        return i
            raise SQLError(f"Error: no such column: {ref.name if not ref.table else ref.table + '.' + ref.name}")
        if ref.table:
            target = f"{ref.table}.{ref.name}"
            if target in headers:
                return headers.index(target)
        if ref.name in headers:
            return headers.index(ref.name)
        raise SQLError(f"Error: no such column: {ref.name if not ref.table else ref.table + '.' + ref.name}")

    def stable_sort_rows(self, rows: List[List[Any]], idx: int, reverse: bool) -> List[List[Any]]:
        def keyfunc(item):
            val = item[idx]
            null_rank = 1 if val is None else 0
            return (null_rank, val)
        non_null = [r for r in rows if r[idx] is not None]
        nulls = [r for r in rows if r[idx] is None]
        sorted_non_null = sorted(non_null, key=lambda r: r[idx], reverse=reverse)
        return sorted_non_null + nulls

    def execute_delete(self, stmt: DeleteStmt) -> int:
        table = self.db.get_table(stmt.table)
        if stmt.where is None:
            n = len(table["rows"])
            table["rows"] = []
            self.db.maybe_autosave()
            return n
        schema = [(stmt.table, c["name"]) for c in table["columns"]]
        kept = []
        count = 0
        for row in table["rows"]:
            data = {(stmt.table, c["name"]): row["_values"][i] for i, c in enumerate(table["columns"])}
            ctx = {"data": data, "schema": schema}
            if self.eval_condition(stmt.where, ctx, {}):
                count += 1
            else:
                kept.append(row)
        table["rows"] = kept
        self.db.maybe_autosave()
        return count

    def execute_update(self, stmt: UpdateStmt) -> int:
        table = self.db.get_table(stmt.table)
        schema_cols = [c["name"] for c in table["columns"]]
        schema_types = {c["name"]: c["type"] for c in table["columns"]}
        for col, _ in stmt.assignments:
            if col not in schema_cols:
                raise SQLError(f"Error: no such column: {col}")
        schema = [(stmt.table, c["name"]) for c in table["columns"]]
        count = 0
        for row in table["rows"]:
            data = {(stmt.table, c["name"]): row["_values"][i] for i, c in enumerate(table["columns"])}
            ctx = {"data": data, "schema": schema}
            if stmt.where is None or self.eval_condition(stmt.where, ctx, {}):
                new_values = list(row["_values"])
                for col, val in stmt.assignments:
                    idx = schema_cols.index(col)
                    new_values[idx] = self.coerce_value(val, schema_types[col])
                row["_values"] = new_values
                count += 1
        self.db.maybe_autosave()
        return count


class CLI:
    def run(self, argv: List[str]) -> int:
        if len(argv) != 3:
            print("Usage: python mini_sqlite.py <dbfile> <sql>", file=sys.stderr)
            return 1
        db_path = argv[1]
        sql = argv[2]
        try:
            tokens = Lexer(sql).tokenize()
            stmt = Parser(tokens).parse()
            storage = StorageEngine(db_path)
            db = Database(storage)
            output = Executor(db).execute(stmt)
            sys.stdout.write(output)
            return 0
        except StorageError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        except SQLExecutionError as e:
            print(e.message, file=sys.stderr)
            return 1
        except OSError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2


def main() -> int:
    return CLI().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
