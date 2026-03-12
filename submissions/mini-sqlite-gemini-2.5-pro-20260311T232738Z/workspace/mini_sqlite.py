#!/usr/bin/env python3

import sys
import os
import re
import json
import copy
import shutil
from collections import namedtuple
from functools import total_ordering

# ==============================================================================
# ---  Exceptions  -------------------------------------------------------------
# ==============================================================================

class MiniSQLiteError(Exception):
    """Base exception for all project-specific errors."""
    pass

class SQLError(MiniSQLiteError):
    """Base exception for SQL-related errors."""
    def __init__(self, message):
        self.message = message
        super().__init__(message)

class SQLSyntaxError(SQLError):
    pass

class SQLUnsupportedError(SQLError):
    pass

class NoTableError(SQLError):
    pass

class NoColumnError(SQLError):
    pass

class AmbiguousColumnError(SQLError):
    pass

class DuplicateColumnError(SQLError):
    pass

class TypeError(SQLError):
    pass

class TransactionError(SQLError):
    pass

class IOError(MiniSQLiteError):
    pass

# ==============================================================================
# ---  Tokenizer (Lexer)  ------------------------------------------------------
# ==============================================================================

Token = namedtuple('Token', ['type', 'value', 'line', 'column'])

class Tokenizer:
    """
    Splits a SQL string into a stream of tokens.
    """
    def __init__(self, code):
        self.code = code
        self.keywords = {
            'SELECT', 'FROM', 'WHERE', 'INSERT', 'INTO', 'VALUES', 'CREATE', 'TABLE',
            'DROP', 'DELETE', 'UPDATE', 'SET', 'ORDER', 'BY', 'ASC', 'DESC', 'LIMIT',
            'OFFSET', 'INTEGER', 'REAL', 'TEXT', 'NULL', 'AND', 'OR', 'NOT', 'IS',
            'JOIN', 'ON', 'INNER', 'LEFT', 'GROUP', 'HAVING', 'COUNT', 'SUM', 'AVG',
            'MIN', 'MAX', 'BEGIN', 'COMMIT', 'ROLLBACK'
        }

    def tokenize(self):
        token_specification = [
            ('STRING',   r"'[^']*'"),
            ('NUMBER',   r'\d+(\.\d*)?'),
            ('ID',       r'[A-Za-z_][A-Za-z0-9_]*'),
            ('OP',       r'!=|<=|>=|<>|<|>|=|\(|\)|,|\*|;'),
            ('NEWLINE',  r'\n'),
            ('SKIP',     r'[ \t]+'),
            ('MISMATCH', r'.'),
        ]
        tok_regex = '|'.join('(?P<%s>%s)' % pair for pair in token_specification)
        line_num = 1
        line_start = 0
        for mo in re.finditer(tok_regex, self.code):
            kind = mo.lastgroup
            value = mo.group()
            column = mo.start() - line_start
            if kind == 'ID':
                if value.upper() in self.keywords:
                    kind = 'KEYWORD'
                yield Token(kind, value, line_num, column)
            elif kind == 'NUMBER':
                yield Token(kind, value, line_num, column)
            elif kind == 'STRING':
                yield Token(kind, value[1:-1], line_num, column) # Strip quotes
            elif kind == 'OP':
                yield Token(kind, value, line_num, column)
            elif kind == 'NEWLINE':
                line_start = mo.end()
                line_num += 1
            elif kind == 'SKIP':
                pass
            elif kind == 'MISMATCH':
                raise SQLSyntaxError(f"syntax error near '{value}'")
        yield Token('EOF', '', line_num, len(self.code) - line_start)

# ==============================================================================
# ---  Parser (AST)  -----------------------------------------------------------
# ==============================================================================

# --- AST Node Definitions ---
# These namedtuples represent the structure of a parsed SQL query.

# Statements
CreateTable = namedtuple('CreateTable', ['table_name', 'columns'])
ColumnDef = namedtuple('ColumnDef', ['name', 'type'])
DropTable = namedtuple('DropTable', ['table_name'])
Insert = namedtuple('Insert', ['table_name', 'columns', 'values'])
Select = namedtuple('Select', ['columns', 'table', 'join', 'where', 'group_by', 'having', 'order_by', 'limit', 'offset'])
Update = namedtuple('Update', ['table_name', 'assignments', 'where'])
Delete = namedtuple('Delete', ['table_name', 'where'])
Transaction = namedtuple('Transaction', ['command']) # command: BEGIN, COMMIT, ROLLBACK

# Clauses
Join = namedtuple('Join', ['type', 'table', 'on_condition'])
OrderBy = namedtuple('OrderBy', ['column', 'direction'])

# Expressions
BinOp = namedtuple('BinOp', ['left', 'op', 'right'])
UnaryOp = namedtuple('UnaryOp', ['op', 'expr'])
Literal = namedtuple('Literal', ['value'])
Identifier = namedtuple('Identifier', ['name'])
FunctionCall = namedtuple('FunctionCall', ['name', 'args'])
IsNullExpr = namedtuple('IsNullExpr', ['expr', 'is_not'])

class Parser:
    """
    Parses a stream of tokens into an Abstract Syntax Tree (AST).
    """
    def __init__(self, tokens):
        self.tokens = iter(tokens)
        self.current_token = None
        self.next_token = None
        self._advance()
        self._advance()

    def _advance(self):
        self.current_token = self.next_token
        try:
            self.next_token = next(self.tokens)
        except StopIteration:
            self.next_token = None

    def _eat(self, token_type, token_value=None):
        if self.current_token is None:
            raise SQLSyntaxError("Unexpected end of input")
        if self.current_token.type == token_type and \
           (token_value is None or self.current_token.value.upper() == token_value.upper()):
            token = self.current_token
            self._advance()
            return token
        else:
            expected = f"'{token_value}'" if token_value else token_type
            raise SQLSyntaxError(f"syntax error near '{self.current_token.value}', expected {expected}")

    def parse(self):
        stmt = self.parse_statement()
        if self.current_token and self.current_token.type != 'EOF':
             self._eat('OP', ';') # Optional semicolon
        self._eat('EOF')
        return stmt

    def parse_statement(self):
        if self.current_token.type == 'KEYWORD':
            keyword = self.current_token.value.upper()
            if keyword == 'CREATE':
                return self.parse_create_table()
            if keyword == 'DROP':
                return self.parse_drop_table()
            if keyword == 'INSERT':
                return self.parse_insert()
            if keyword == 'SELECT':
                return self.parse_select()
            if keyword == 'UPDATE':
                return self.parse_update()
            if keyword == 'DELETE':
                return self.parse_delete()
            if keyword in ('BEGIN', 'COMMIT', 'ROLLBACK'):
                return self.parse_transaction()
        raise SQLSyntaxError(f"syntax error near '{self.current_token.value}'")

    def parse_transaction(self):
        command = self._eat('KEYWORD').value.upper()
        return Transaction(command)

    def parse_create_table(self):
        self._eat('KEYWORD', 'CREATE')
        self._eat('KEYWORD', 'TABLE')
        table_name = self._eat('ID').value
        self._eat('OP', '(')
        columns = []
        while self.current_token.type != 'OP' or self.current_token.value != ')':
            col_name = self._eat('ID').value
            col_type = self._eat('KEYWORD').value.upper()
            if col_type not in ('INTEGER', 'REAL', 'TEXT', 'NULL'):
                raise SQLSyntaxError(f"unknown type '{col_type}'")
            columns.append(ColumnDef(col_name, col_type))
            if self.current_token.value == ',':
                self._eat('OP', ',')
        self._eat('OP', ')')
        return CreateTable(table_name, columns)

    def parse_drop_table(self):
        self._eat('KEYWORD', 'DROP')
        self._eat('KEYWORD', 'TABLE')
        table_name = self._eat('ID').value
        return DropTable(table_name)

    def parse_insert(self):
        self._eat('KEYWORD', 'INSERT')
        self._eat('KEYWORD', 'INTO')
        table_name = self._eat('ID').value
        columns = None
        if self.current_token.value == '(':
            self._eat('OP', '(')
            columns = []
            while self.current_token.value != ')':
                columns.append(self._eat('ID').value)
                if self.current_token.value == ',':
                    self._eat('OP', ',')
            self._eat('OP', ')')

        self._eat('KEYWORD', 'VALUES')
        self._eat('OP', '(')
        values = []
        while self.current_token.value != ')':
            values.append(self.parse_literal())
            if self.current_token.value == ',':
                self._eat('OP', ',')
        self._eat('OP', ')')
        return Insert(table_name, columns, values)

    def parse_delete(self):
        self._eat('KEYWORD', 'DELETE')
        self._eat('KEYWORD', 'FROM')
        table_name = self._eat('ID').value
        where_clause = None
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'WHERE':
            where_clause = self.parse_where()
        return Delete(table_name, where_clause)

    def parse_update(self):
        self._eat('KEYWORD', 'UPDATE')
        table_name = self._eat('ID').value
        self._eat('KEYWORD', 'SET')
        assignments = []
        while True:
            col_name = self._eat('ID').value
            self._eat('OP', '=')
            value = self.parse_expression()
            assignments.append((col_name, value))
            if self.current_token.value == ',':
                self._eat('OP', ',')
            else:
                break
        where_clause = None
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'WHERE':
            where_clause = self.parse_where()
        return Update(table_name, assignments, where_clause)

    def parse_select(self):
        self._eat('KEYWORD', 'SELECT')
        columns = []
        if self.current_token.value == '*':
            self._eat('OP', '*')
            columns.append(Identifier('*'))
        else:
            while True:
                columns.append(self.parse_selectable_expression())
                if self.current_token.value == ',':
                    self._eat('OP', ',')
                else:
                    break
        self._eat('KEYWORD', 'FROM')
        table = self._eat('ID').value
        join_clause = self.parse_join()
        where_clause = self.parse_where()
        group_by_clause = self.parse_group_by()
        having_clause = self.parse_having()
        order_by_clause = self.parse_order_by()
        limit, offset = self.parse_limit_offset()
        return Select(columns, table, join_clause, where_clause, group_by_clause, having_clause, order_by_clause, limit, offset)

    def parse_selectable_expression(self):
        if self.next_token and self.next_token.value == '(':
            return self.parse_function_call()
        return self.parse_identifier()

    def parse_function_call(self):
        name = self._eat('KEYWORD').value.upper()
        self._eat('OP', '(')
        args = []
        if self.current_token.value != ')':
            if self.current_token.value == '*':
                args.append(Identifier(self._eat('OP').value))
            else:
                args.append(self.parse_identifier())
        self._eat('OP', ')')
        return FunctionCall(name, args)

    def parse_join(self):
        if self.current_token.type != 'KEYWORD' or self.current_token.value.upper() not in ('INNER', 'LEFT'):
            return None
        join_type = self._eat('KEYWORD').value.upper()
        if join_type == 'LEFT':
            self._eat('KEYWORD', 'JOIN')
        elif join_type == 'INNER':
            self._eat('KEYWORD', 'JOIN')
        else: # Should not happen
            return None
        table = self._eat('ID').value
        self._eat('KEYWORD', 'ON')
        condition = self.parse_expression()
        return Join(join_type, table, condition)

    def parse_where(self):
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'WHERE':
            self._eat('KEYWORD', 'WHERE')
            return self.parse_expression()
        return None

    def parse_group_by(self):
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'GROUP':
            self._eat('KEYWORD', 'GROUP')
            self._eat('KEYWORD', 'BY')
            columns = []
            while True:
                columns.append(self.parse_identifier())
                if self.current_token.value == ',':
                    self._eat('OP', ',')
                else:
                    break
            return columns
        return None

    def parse_having(self):
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'HAVING':
            self._eat('KEYWORD', 'HAVING')
            return self.parse_expression()
        return None

    def parse_order_by(self):
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'ORDER':
            self._eat('KEYWORD', 'ORDER')
            self._eat('KEYWORD', 'BY')
            column = self.parse_identifier()
            direction = 'ASC'
            if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() in ('ASC', 'DESC'):
                direction = self._eat('KEYWORD').value.upper()
            return OrderBy(column, direction)
        return None

    def parse_limit_offset(self):
        limit, offset = None, None
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'LIMIT':
            self._eat('KEYWORD', 'LIMIT')
            limit = int(self._eat('NUMBER').value)
        if self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'OFFSET':
            self._eat('KEYWORD', 'OFFSET')
            offset = int(self._eat('NUMBER').value)
        # Handle OFFSET appearing before LIMIT
        if limit is None and self.current_token.type == 'KEYWORD' and self.current_token.value.upper() == 'LIMIT':
            self._eat('KEYWORD', 'LIMIT')
            limit = int(self._eat('NUMBER').value)
        return limit, offset

    def parse_expression(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.current_token and self.current_token.value.upper() == 'OR':
            op = self._eat('KEYWORD').value
            node = BinOp(node, op, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.current_token and self.current_token.value.upper() == 'AND':
            op = self._eat('KEYWORD').value
            node = BinOp(node, op, self.parse_not())
        return node

    def parse_not(self):
        if self.current_token and self.current_token.value.upper() == 'NOT':
            op = self._eat('KEYWORD').value
            return UnaryOp(op, self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        node = self.parse_primary()
        if self.current_token and self.current_token.type == 'OP' and self.current_token.value in ('=', '!=', '<>', '<', '>', '<=', '>='):
            op = self._eat('OP').value
            if op == '<>': op = '!='
            return BinOp(node, op, self.parse_primary())
        if self.current_token and self.current_token.value.upper() == 'IS':
            self._eat('KEYWORD', 'IS')
            is_not = False
            if self.current_token.value.upper() == 'NOT':
                self._eat('KEYWORD', 'NOT')
                is_not = True
            self._eat('KEYWORD', 'NULL')
            return IsNullExpr(node, is_not)
        return node

    def parse_primary(self):
        if self.current_token.value == '(':
            self._eat('OP', '(')
            node = self.parse_expression()
            self._eat('OP', ')')
            return node
        elif self.current_token.type in ('STRING', 'NUMBER') or self.current_token.value.upper() == 'NULL':
            return self.parse_literal()
        else:
            return self.parse_identifier()

    def parse_literal(self):
        token = self.current_token
        if token.type == 'STRING':
            self._advance()
            return Literal(token.value)
        if token.type == 'NUMBER':
            self._advance()
            if '.' in token.value:
                return Literal(float(token.value))
            return Literal(int(token.value))
        if token.type == 'KEYWORD' and token.value.upper() == 'NULL':
            self._advance()
            return Literal(None)
        raise SQLSyntaxError(f"unexpected literal '{token.value}'")

    def parse_identifier(self):
        return Identifier(self._eat('ID').value)

# ==============================================================================
# ---  Storage Engine  ---------------------------------------------------------
# ==============================================================================

class StorageEngine:
    """
    Manages the on-disk database file and transactions.
    """
    def __init__(self, db_path):
        self.db_path = db_path
        self.backup_path = db_path + ".bak"
        self.db = None
        self.in_transaction = os.path.exists(self.backup_path)

    def _load_db(self):
        if self.db is not None:
            return
        try:
            if not os.path.exists(self.db_path):
                self.db = {'tables': {}}
            else:
                with open(self.db_path, 'r') as f:
                    self.db = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise IOError(f"could not read database file: {e}")

    def _save_db(self):
        try:
            temp_path = self.db_path + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(self.db, f, indent=4)
            os.rename(temp_path, self.db_path)
        except OSError as e:
            raise IOError(f"could not write to database file: {e}")

    def _execute_in_context(self, func, read_only=False):
        self._load_db()
        if self.in_transaction or read_only:
            return func(self.db)
        
        # Auto-commit mode
        db_copy = copy.deepcopy(self.db)
        result = func(db_copy)
        self.db = db_copy
        self._save_db()
        return result

    def begin_transaction(self):
        if self.in_transaction:
            raise TransactionError("transaction already in progress")
        if os.path.exists(self.db_path):
            try:
                shutil.copy(self.db_path, self.backup_path)
            except OSError as e:
                raise IOError(f"could not create backup file: {e}")
        else: # Create empty backup if db doesn't exist
             with open(self.backup_path, 'w') as f:
                f.write("")
        self.in_transaction = True
        return "OK"

    def commit(self):
        if not self.in_transaction:
            raise TransactionError("no transaction to commit")
        try:
            if os.path.exists(self.backup_path):
                os.remove(self.backup_path)
        except OSError as e:
            raise IOError(f"could not remove backup file: {e}")
        self.in_transaction = False
        return "OK"

    def rollback(self):
        if not self.in_transaction:
            raise TransactionError("no transaction to rollback")
        try:
            if os.path.getsize(self.backup_path) > 0:
                shutil.move(self.backup_path, self.db_path)
            else: # Backup was empty, so original db didn't exist
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                os.remove(self.backup_path)
        except OSError as e:
            raise IOError(f"could not restore from backup file: {e}")
        self.in_transaction = False
        self.db = None # Force reload on next access
        return "OK"

    def create_table(self, name, columns):
        def _op(db):
            if name in db['tables']:
                raise SQLError(f"table {name} already exists")
            
            col_names = {c.name for c in columns}
            if len(col_names) != len(columns):
                raise DuplicateColumnError("duplicate column name")

            db['tables'][name] = {
                'schema': [{'name': c.name, 'type': c.type} for c in columns],
                'rows': []
            }
            return "OK"
        return self._execute_in_context(_op)

    def drop_table(self, name):
        def _op(db):
            if name not in db['tables']:
                raise NoTableError(f"no such table: {name}")
            del db['tables'][name]
            return "OK"
        return self._execute_in_context(_op)

    def get_table(self, name):
        def _op(db):
            if name not in db['tables']:
                raise NoTableError(f"no such table: {name}")
            return db['tables'][name]
        return self._execute_in_context(_op, read_only=True)

    def insert_row(self, table_name, row):
        def _op(db):
            if table_name not in db['tables']:
                raise NoTableError(f"no such table: {table_name}")
            db['tables'][table_name]['rows'].append(row)
            return "1 row affected"
        return self._execute_in_context(_op)

    def update_rows(self, table_name, update_func):
        def _op(db):
            if table_name not in db['tables']:
                raise NoTableError(f"no such table: {table_name}")
            
            table = db['tables'][table_name]
            affected_count = 0
            new_rows = []
            for row in table['rows']:
                updated_row, was_updated = update_func(row)
                new_rows.append(updated_row)
                if was_updated:
                    affected_count += 1
            table['rows'] = new_rows
            return f"{affected_count} rows affected"
        return self._execute_in_context(_op)

    def delete_rows(self, table_name, filter_func):
        def _op(db):
            if table_name not in db['tables']:
                raise NoTableError(f"no such table: {table_name}")
            
            table = db['tables'][table_name]
            initial_count = len(table['rows'])
            table['rows'] = [row for row in table['rows'] if not filter_func(row)]
            affected_count = initial_count - len(table['rows'])
            return f"{affected_count} rows affected"
        return self._execute_in_context(_op)

# ==============================================================================
# ---  Execution Engine  -------------------------------------------------------
# ==============================================================================

@total_ordering
class Descending:
    """Wrapper class for descending order sorting where NULLs are last."""
    def __init__(self, value):
        self.value = value
    def __eq__(self, other):
        return self.value == other.value
    def __lt__(self, other):
        if self.value is None and other.value is None: return False
        if self.value is None: return False
        if other.value is None: return True
        return self.value > other.value

class ExecutionEngine:
    """
    Executes an AST against the storage engine.
    """
    def __init__(self, storage):
        self.storage = storage

    def execute(self, node):
        method_name = f'_execute_{type(node).__name__.lower()}'
        if hasattr(self, method_name):
            return getattr(self, method_name)(node)
        raise SQLUnsupportedError(f"unsupported statement type '{type(node).__name__}'")

    def _execute_transaction(self, node):
        if node.command == 'BEGIN':
            return self.storage.begin_transaction()
        if node.command == 'COMMIT':
            return self.storage.commit()
        if node.command == 'ROLLBACK':
            return self.storage.rollback()

    def _execute_createtable(self, node):
        return self.storage.create_table(node.table_name, node.columns)

    def _execute_droptable(self, node):
        return self.storage.drop_table(node.table_name)

    def _execute_insert(self, node):
        table = self.storage.get_table(node.table_name)
        schema = table['schema']
        
        if node.columns:
            if len(node.columns) != len(node.values):
                raise SQLError("number of columns does not match number of values")
            
            col_map = {col['name']: i for i, col in enumerate(schema)}
            row = [None] * len(schema)
            for col_name, value_expr in zip(node.columns, node.values):
                if col_name not in col_map:
                    raise NoColumnError(f"no such column: {col_name}")
                idx = col_map[col_name]
                value = self._evaluate_literal(value_expr)
                row[idx] = self._cast(value, schema[idx]['type'])
        else:
            if len(schema) != len(node.values):
                raise SQLError("number of columns does in match number of values")
            row = [self._cast(self._evaluate_literal(v), s['type']) for v, s in zip(node.values, schema)]
        
        return self.storage.insert_row(node.table_name, row)

    def _execute_delete(self, node):
        if not node.where:
            return self.storage.delete_rows(node.table_name, lambda row: True)

        table = self.storage.get_table(node.table_name)
        schema = table['schema']
        
        def filter_func(row):
            context = self._create_row_context(schema, row)
            return self._evaluate_expr(node.where, context)

        return self.storage.delete_rows(node.table_name, filter_func)

    def _execute_update(self, node):
        table = self.storage.get_table(node.table_name)
        schema = table['schema']
        col_map = {col['name']: i for i, col in enumerate(schema)}

        for col_name, _ in node.assignments:
            if col_name not in col_map:
                raise NoColumnError(f"no such column: {col_name}")

        def update_func(row):
            context = self._create_row_context(schema, row)
            if not node.where or self._evaluate_expr(node.where, context):
                new_row = list(row)
                for col_name, value_expr in node.assignments:
                    idx = col_map[col_name]
                    value = self._evaluate_expr(value_expr, context)
                    new_row[idx] = self._cast(value, schema[idx]['type'])
                return new_row, True
            return row, False

        return self.storage.update_rows(node.table_name, update_func)

    def _execute_select(self, node):
        # 1. FROM / JOIN
        from_table = self.storage.get_table(node.table)
        from_schema = from_table['schema']
        rows = from_table['rows']
        schema = from_schema

        if node.join:
            join_table = self.storage.get_table(node.join.table)
            join_schema = join_table['schema']
            combined_schema = from_schema + join_schema
            
            joined_rows = []
            if node.join.type == 'INNER':
                for r1 in rows:
                    for r2 in join_table['rows']:
                        context = self._create_row_context(combined_schema, r1 + r2)
                        if self._evaluate_expr(node.join.on_condition, context):
                            joined_rows.append(r1 + r2)
            elif node.join.type == 'LEFT':
                for r1 in rows:
                    found_match = False
                    for r2 in join_table['rows']:
                        context = self._create_row_context(combined_schema, r1 + r2)
                        if self._evaluate_expr(node.join.on_condition, context):
                            joined_rows.append(r1 + r2)
                            found_match = True
                    if not found_match:
                        joined_rows.append(r1 + [None] * len(join_schema))
            rows = joined_rows
            schema = combined_schema

        # 2. WHERE
        if node.where:
            rows = [row for row in rows if self._evaluate_expr(node.where, self._create_row_context(schema, row))]

        # 3. GROUP BY / HAVING
        if node.group_by:
            groups, agg_funcs = self._perform_group_by(node, schema, rows)
            
            # 4. HAVING
            if node.having:
                groups = {k: v for k, v in groups.items() if self._evaluate_expr(node.having, v['context'])}
            
            # 5. PROJECTION (from groups)
            header, result_rows = self._project_groups(node, groups, agg_funcs)
        else:
            # 5. PROJECTION (from rows)
            header, result_rows = self._project_rows(node, schema, rows)

        # 6. ORDER BY
        if node.order_by:
            col_name = node.order_by.column.name
            if col_name not in header:
                raise NoColumnError(f"no such column: {col_name}")
            col_idx = header.index(col_name)
            is_desc = node.order_by.direction == 'DESC'
            
            if is_desc:
                result_rows.sort(key=lambda r: Descending(r[col_idx]))
            else:
                result_rows.sort(key=lambda r: (r[col_idx] is None, r[col_idx]))

        # 7. LIMIT / OFFSET
        offset = node.offset or 0
        if node.limit is not None:
            result_rows = result_rows[offset : offset + node.limit]
        elif offset > 0:
            result_rows = result_rows[offset:]

        return header, result_rows

    def _perform_group_by(self, node, schema, rows):
        group_by_cols = [c.name for c in node.group_by]
        col_map = {c['name']: i for i, c in enumerate(schema)}
        group_by_indices = [col_map[name] for name in group_by_cols]

        agg_funcs = [c for c in node.columns if isinstance(c, FunctionCall)]
        
        groups = {}
        for row in rows:
            key = tuple(row[i] for i in group_by_indices)
            if key not in groups:
                groups[key] = {
                    'aggregates': [None] * len(agg_funcs),
                    'counts': [0] * len(agg_funcs), # For AVG
                    'row_count': 0
                }
            
            group = groups[key]
            group['row_count'] += 1
            context = self._create_row_context(schema, row)

            for i, func in enumerate(agg_funcs):
                if func.name == 'COUNT' and isinstance(func.args[0], Identifier) and func.args[0].name == '*':
                    val = 1 # any non-null value
                else:
                    val = self._evaluate_expr(func.args[0], context)

                if val is None:
                    continue

                agg_val = group['aggregates'][i]
                if func.name == 'COUNT':
                    group['aggregates'][i] = 1 if agg_val is None else agg_val + 1
                elif func.name == 'SUM':
                    group['aggregates'][i] = val if agg_val is None else agg_val + val
                    group['counts'][i] += 1
                elif func.name == 'AVG':
                    group['aggregates'][i] = val if agg_val is None else agg_val + val
                    group['counts'][i] += 1
                elif func.name == 'MIN':
                    group['aggregates'][i] = val if agg_val is None else min(agg_val, val)
                elif func.name == 'MAX':
                    group['aggregates'][i] = val if agg_val is None else max(agg_val, val)

        # Finalize aggregates and create context for HAVING
        for key, group in groups.items():
            group_context = {name: val for name, val in zip(group_by_cols, key)}
            for i, func in enumerate(agg_funcs):
                if func.name == 'AVG' and group['counts'][i] > 0:
                    group['aggregates'][i] /= group['counts'][i]
                elif func.name == 'AVG' and group['counts'][i] == 0:
                    group['aggregates'][i] = None
                
                func_str = f"{func.name}({func.args[0].name})"
                group_context[func_str] = group['aggregates'][i]
            group['context'] = group_context

        return groups, agg_funcs

    def _project_groups(self, node, groups, agg_funcs):
        header = []
        group_by_cols = [c.name for c in node.group_by]
        
        for col in node.columns:
            if isinstance(col, Identifier):
                if col.name not in group_by_cols:
                    raise SQLError(f"column '{col.name}' must appear in the GROUP BY clause or be used in an aggregate function")
                header.append(col.name)
            elif isinstance(col, FunctionCall):
                header.append(f"{col.name}({col.args[0].name})")

        result_rows = []
        for key, group in groups.items():
            row = []
            key_idx = 0
            agg_idx = 0
            for col in node.columns:
                if isinstance(col, Identifier):
                    row.append(key[key_idx])
                    key_idx += 1
                elif isinstance(col, FunctionCall):
                    row.append(group['aggregates'][agg_idx])
                    agg_idx += 1
            result_rows.append(row)
        
        return header, result_rows

    def _project_rows(self, node, schema, rows):
        if len(node.columns) == 1 and isinstance(node.columns[0], Identifier) and node.columns[0].name == '*':
            header = [c['name'] for c in schema]
            return header, rows

        header = []
        for col in node.columns:
            if isinstance(col, Identifier):
                header.append(col.name)
            elif isinstance(col, FunctionCall):
                 raise SQLError("aggregate functions are not allowed without a GROUP BY clause")

        col_map = {c['name']: i for i, c in enumerate(schema)}
        for h in header:
            if h not in col_map:
                raise NoColumnError(f"no such column: {h}")
        
        indices = [col_map[h] for h in header]
        result_rows = [[row[i] for i in indices] for row in rows]
        return header, result_rows

    def _create_row_context(self, schema, row):
        return {col['name']: val for col, val in zip(schema, row)}

    def _evaluate_expr(self, expr, context):
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, Identifier):
            if expr.name not in context:
                raise NoColumnError(f"no such column: {expr.name}")
            return context[expr.name]
        if isinstance(expr, FunctionCall):
            # This is for HAVING clause
            func_str = f"{expr.name}({expr.args[0].name})"
            if func_str not in context:
                raise SQLError(f"aggregate function '{func_str}' not available in this context")
            return context[func_str]
        if isinstance(expr, UnaryOp):
            val = self._evaluate_expr(expr.expr, context)
            if expr.op.upper() == 'NOT':
                return not val
        if isinstance(expr, BinOp):
            left = self._evaluate_expr(expr.left, context)
            right = self._evaluate_expr(expr.right, context)
            op = expr.op.upper()
            if op == 'AND': return left and right
            if op == 'OR': return left or right
            return self._compare(left, op, right)
        if isinstance(expr, IsNullExpr):
            val = self._evaluate_expr(expr.expr, context)
            is_null = val is None
            return not is_null if expr.is_not else is_null
        raise SQLUnsupportedError(f"unsupported expression type '{type(expr).__name__}'")

    def _evaluate_literal(self, literal_node):
        if not isinstance(literal_node, Literal):
            raise SQLError("expected a literal value")
        return literal_node.value

    def _compare(self, v1, op, v2):
        # NULL semantics for comparisons
        if v1 is None or v2 is None:
            return False

        # Attempt type coercion for comparison
        if isinstance(v1, (int, float)) and isinstance(v2, str):
            try: v2 = float(v2)
            except ValueError: pass
        elif isinstance(v2, (int, float)) and isinstance(v1, str):
            try: v1 = float(v1)
            except ValueError: pass

        if op == '=': return v1 == v2
        if op == '!=': return v1 != v2
        if op == '<': return v1 < v2
        if op == '>': return v1 > v2
        if op == '<=': return v1 <= v2
        if op == '>=': return v1 >= v2
        return False

    def _cast(self, value, type_str):
        if value is None:
            return None
        try:
            if type_str == 'INTEGER':
                return int(value)
            if type_str == 'REAL':
                return float(value)
            if type_str == 'TEXT':
                return str(value)
        except (ValueError, TypeError):
            raise TypeError(f"could not cast value '{value}' to {type_str}")
        return value

# ==============================================================================
# ---  CLI  --------------------------------------------------------------------
# ==============================================================================

def escape_output(value):
    if value is None:
        return ""
    s = str(value)
    s = s.replace('\\', '\\\\')
    s = s.replace('\n', '\\n')
    s = s.replace('|', '\\|')
    return s

def main():
    if len(sys.argv) != 3:
        print("Usage: python mini_sqlite.py <database_file> \"<sql_statement>\"", file=sys.stderr)
        sys.exit(1)

    db_path, sql_query = sys.argv[1], sys.argv[2]

    try:
        storage = StorageEngine(db_path)
        engine = ExecutionEngine(storage)

        tokens = Tokenizer(sql_query).tokenize()
        ast = Parser(list(tokens)).parse()

        result = engine.execute(ast)

        if isinstance(result, str):
            print(result)
        elif isinstance(result, tuple):
            header, rows = result
            print("|".join(header))
            for row in rows:
                print("|".join(escape_output(v) for v in row))

    except IOError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except NoTableError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        sys.exit(1)
    except NoColumnError as e:
        print(f"Error: no such column: {e.message.split(': ')[-1]}", file=sys.stderr)
        sys.exit(1)
    except SQLSyntaxError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        sys.exit(1)
    except SQLUnsupportedError as e:
        print(f"Error: unsupported feature '{e.message}'", file=sys.stderr)
        sys.exit(1)
    except SQLError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        # For unexpected errors during development/testing
        import traceback
        print(f"An unexpected error occurred: {traceback.format_exc()}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
