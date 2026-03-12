#!/usr/bin/env python3
"""mini-sqlite: A SQL database engine in a single Python file."""

import sys
import os
import json
import re
import copy
import fcntl

# ============================================================================
# Storage Layer
# ============================================================================

class StorageEngine:
    """Handles reading/writing the database file."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._data = None

    def load(self):
        """Load database from disk."""
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 0:
            try:
                with open(self.db_path, 'r') as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                raise IOError(f"Error: failed to read database: {e}")
        else:
            self._data = {"tables": {}}
        return self._data

    def save(self, data):
        """Save database to disk."""
        try:
            with open(self.db_path, 'w') as f:
                json.dump(data, f)
        except IOError as e:
            raise IOError(f"Error: failed to write database: {e}")

    def get_data(self):
        if self._data is None:
            self.load()
        return self._data


# ============================================================================
# SQL Parser
# ============================================================================

class Token:
    def __init__(self, type_, value):
        self.type = type_
        self.value = value

    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"


class Tokenizer:
    """Tokenize SQL input."""

    KEYWORDS = {
        'SELECT', 'FROM', 'WHERE', 'INSERT', 'INTO', 'VALUES', 'UPDATE',
        'SET', 'DELETE', 'CREATE', 'DROP', 'TABLE', 'AND', 'OR', 'NOT',
        'NULL', 'IS', 'ORDER', 'BY', 'ASC', 'DESC', 'LIMIT', 'OFFSET',
        'INNER', 'LEFT', 'JOIN', 'ON', 'GROUP', 'HAVING', 'BEGIN',
        'COMMIT', 'ROLLBACK', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
        'INTEGER', 'REAL', 'TEXT', 'AS'
    }

    def tokenize(self, sql):
        tokens = []
        i = 0
        sql = sql.strip()
        while i < len(sql):
            # Skip whitespace
            if sql[i].isspace():
                i += 1
                continue

            # Single-line comment
            if sql[i:i+2] == '--':
                while i < len(sql) and sql[i] != '\n':
                    i += 1
                continue

            # Operators
            if sql[i:i+2] in ('<=', '>=', '!='):
                tokens.append(Token('OP', sql[i:i+2]))
                i += 2
                continue

            if sql[i] in ('=', '<', '>'):
                tokens.append(Token('OP', sql[i]))
                i += 1
                continue

            # Punctuation
            if sql[i] in ('(', ')', ',', '*', '|'):
                tokens.append(Token(sql[i], sql[i]))
                i += 1
                continue

            # Semicolon
            if sql[i] == ';':
                i += 1
                continue

            # String literal
            if sql[i] == "'":
                j = i + 1
                s = ""
                while j < len(sql):
                    if sql[j] == "'" and j + 1 < len(sql) and sql[j+1] == "'":
                        s += "'"
                        j += 2
                    elif sql[j] == "'":
                        break
                    else:
                        s += sql[j]
                        j += 1
                if j >= len(sql):
                    raise SyntaxError(f"Error: syntax error near 'unterminated string'")
                tokens.append(Token('STRING', s))
                i = j + 1
                continue

            # Number
            if sql[i].isdigit() or (sql[i] == '-' and i + 1 < len(sql) and (sql[i+1].isdigit() or sql[i+1] == '.')):
                j = i
                if sql[j] == '-':
                    # Check if this is a unary minus (not subtraction)
                    # It's unary if previous token is not a number/string/identifier/closing paren
                    if tokens and tokens[-1].type in ('NUMBER', 'STRING', 'IDENT', ')'):
                        tokens.append(Token('OP', '-'))
                        i += 1
                        continue
                    j += 1
                has_dot = False
                while j < len(sql) and (sql[j].isdigit() or (sql[j] == '.' and not has_dot)):
                    if sql[j] == '.':
                        has_dot = True
                    j += 1
                num_str = sql[i:j]
                if has_dot:
                    tokens.append(Token('NUMBER', float(num_str)))
                else:
                    tokens.append(Token('NUMBER', int(num_str)))
                i = j
                continue

            # Dot for table.column
            if sql[i] == '.':
                tokens.append(Token('.', '.'))
                i += 1
                continue

            # Identifier or keyword
            if sql[i].isalpha() or sql[i] == '_':
                j = i
                while j < len(sql) and (sql[j].isalnum() or sql[j] == '_'):
                    j += 1
                word = sql[i:j]
                upper = word.upper()
                if upper in self.KEYWORDS:
                    tokens.append(Token(upper, upper))
                else:
                    tokens.append(Token('IDENT', word))
                i = j
                continue

            raise SyntaxError(f"Error: syntax error near '{sql[i]}'")

        tokens.append(Token('EOF', None))
        return tokens


class Parser:
    """Parse tokens into AST nodes."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token('EOF', None)

    def peek(self, offset=0):
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token('EOF', None)

    def advance(self):
        t = self.current()
        self.pos += 1
        return t

    def expect(self, type_, value=None):
        t = self.current()
        if t.type != type_ or (value is not None and t.value != value):
            actual = t.value if t.value else t.type
            raise SyntaxError(f"Error: syntax error near '{actual}'")
        self.pos += 1
        return t

    def match(self, type_, value=None):
        t = self.current()
        if t.type == type_ and (value is None or t.value == value):
            self.pos += 1
            return t
        return None

    def parse(self):
        t = self.current()
        if t.type == 'SELECT':
            return self.parse_select()
        elif t.type == 'INSERT':
            return self.parse_insert()
        elif t.type == 'UPDATE':
            return self.parse_update()
        elif t.type == 'DELETE':
            return self.parse_delete()
        elif t.type == 'CREATE':
            return self.parse_create()
        elif t.type == 'DROP':
            return self.parse_drop()
        elif t.type == 'BEGIN':
            self.advance()
            return {'type': 'BEGIN'}
        elif t.type == 'COMMIT':
            self.advance()
            return {'type': 'COMMIT'}
        elif t.type == 'ROLLBACK':
            self.advance()
            return {'type': 'ROLLBACK'}
        else:
            raise SyntaxError(f"Error: syntax error near '{t.value}'")

    def parse_create(self):
        self.expect('CREATE')
        self.expect('TABLE')
        name = self.expect('IDENT').value
        self.expect('(')
        columns = []
        while True:
            col_name = self.expect('IDENT').value
            col_type = self.current()
            if col_type.type in ('INTEGER', 'REAL', 'TEXT', 'NULL'):
                self.advance()
                col_type_str = col_type.value
            else:
                col_type_str = 'TEXT'
            columns.append((col_name, col_type_str))
            if not self.match(','):
                break
        self.expect(')')
        return {'type': 'CREATE_TABLE', 'name': name, 'columns': columns}

    def parse_drop(self):
        self.expect('DROP')
        self.expect('TABLE')
        name = self.expect('IDENT').value
        return {'type': 'DROP_TABLE', 'name': name}

    def parse_insert(self):
        self.expect('INSERT')
        self.expect('INTO')
        name = self.expect('IDENT').value
        col_names = None
        if self.current().type == '(':
            # Could be column list or VALUES
            # Peek ahead to see if next tokens look like column names
            # Save position
            saved = self.pos
            self.advance()  # skip (
            # Check if this looks like identifiers followed by ) VALUES
            # or values
            first = self.current()
            if first.type == 'IDENT':
                # Likely column list
                cols = [first.value]
                self.advance()
                while self.match(','):
                    cols.append(self.expect('IDENT').value)
                self.expect(')')
                col_names = cols
            else:
                # Not column list, restore position
                self.pos = saved

        self.expect('VALUES')
        self.expect('(')
        values = []
        while True:
            values.append(self.parse_value())
            if not self.match(','):
                break
        self.expect(')')
        return {'type': 'INSERT', 'table': name, 'columns': col_names, 'values': values}

    def parse_value(self):
        t = self.current()
        if t.type == 'NUMBER':
            self.advance()
            return t.value
        elif t.type == 'STRING':
            self.advance()
            return t.value
        elif t.type == 'NULL':
            self.advance()
            return None
        elif t.type == 'OP' and t.value == '-':
            self.advance()
            num = self.expect('NUMBER')
            return -num.value
        else:
            raise SyntaxError(f"Error: syntax error near '{t.value}'")

    def parse_select(self):
        self.expect('SELECT')
        columns = self.parse_select_columns()
        self.expect('FROM')
        table = self.expect('IDENT').value
        table_alias = None
        if self.current().type == 'IDENT' and self.current().value.upper() not in (
            'WHERE', 'ORDER', 'LIMIT', 'INNER', 'LEFT', 'JOIN', 'GROUP', 'HAVING'):
            table_alias = self.advance().value
        elif self.match('AS'):
            table_alias = self.expect('IDENT').value

        joins = []
        while self.current().type in ('INNER', 'LEFT', 'JOIN'):
            joins.append(self.parse_join())

        where = None
        if self.match('WHERE'):
            where = self.parse_expression()

        group_by = None
        having = None
        if self.match('GROUP'):
            self.expect('BY')
            group_by = self.parse_column_ref()
            if self.match('HAVING'):
                having = self.parse_expression()

        order_by = None
        if self.match('ORDER'):
            self.expect('BY')
            col = self.parse_column_ref()
            direction = 'ASC'
            if self.match('ASC'):
                direction = 'ASC'
            elif self.match('DESC'):
                direction = 'DESC'
            order_by = (col, direction)

        limit = None
        offset = None
        if self.match('LIMIT'):
            limit = self.expect('NUMBER').value
            if self.match('OFFSET'):
                offset = self.expect('NUMBER').value

        return {
            'type': 'SELECT',
            'columns': columns,
            'table': table,
            'table_alias': table_alias,
            'joins': joins,
            'where': where,
            'group_by': group_by,
            'having': having,
            'order_by': order_by,
            'limit': limit,
            'offset': offset,
        }

    def parse_select_columns(self):
        if self.current().type == '*':
            self.advance()
            return [{'type': 'star'}]

        columns = []
        while True:
            columns.append(self.parse_select_column())
            if not self.match(','):
                break
        return columns

    def parse_select_column(self):
        # Check for aggregate functions
        t = self.current()
        if t.type in ('COUNT', 'SUM', 'AVG', 'MIN', 'MAX'):
            func = t.type
            self.advance()
            self.expect('(')
            if func == 'COUNT' and self.current().type == '*':
                self.advance()
                self.expect(')')
                alias = None
                if self.match('AS'):
                    alias = self.expect('IDENT').value
                return {'type': 'aggregate', 'func': 'COUNT', 'arg': '*', 'alias': alias}
            else:
                col = self.parse_column_ref()
                self.expect(')')
                alias = None
                if self.match('AS'):
                    alias = self.expect('IDENT').value
                return {'type': 'aggregate', 'func': func, 'arg': col, 'alias': alias}

        col = self.parse_column_ref()
        alias = None
        if self.match('AS'):
            alias = self.expect('IDENT').value
        return {'type': 'column', 'ref': col, 'alias': alias}

    def parse_column_ref(self):
        """Parse a column reference which may be table.column or just column."""
        name = self.expect('IDENT').value
        if self.match('.'):
            col = self.expect('IDENT').value
            return {'table': name, 'column': col}
        return {'table': None, 'column': name}

    def parse_join(self):
        join_type = 'INNER'
        if self.match('LEFT'):
            join_type = 'LEFT'
            self.match('JOIN')  # optional JOIN keyword after LEFT
        elif self.match('INNER'):
            join_type = 'INNER'
            self.match('JOIN')
        elif self.match('JOIN'):
            join_type = 'INNER'

        table = self.expect('IDENT').value
        table_alias = None
        if self.current().type == 'IDENT' and self.current().value.upper() not in (
            'ON', 'WHERE', 'ORDER', 'LIMIT', 'INNER', 'LEFT', 'JOIN', 'GROUP', 'HAVING'):
            table_alias = self.advance().value
        elif self.match('AS'):
            table_alias = self.expect('IDENT').value

        self.expect('ON')
        condition = self.parse_expression()
        return {
            'type': join_type,
            'table': table,
            'table_alias': table_alias,
            'on': condition,
        }

    def parse_update(self):
        self.expect('UPDATE')
        table = self.expect('IDENT').value
        self.expect('SET')
        assignments = []
        while True:
            col = self.expect('IDENT').value
            self.expect('OP', '=')
            val = self.parse_expr_value()
            assignments.append((col, val))
            if not self.match(','):
                break
        where = None
        if self.match('WHERE'):
            where = self.parse_expression()
        return {'type': 'UPDATE', 'table': table, 'assignments': assignments, 'where': where}

    def parse_delete(self):
        self.expect('DELETE')
        self.expect('FROM')
        table = self.expect('IDENT').value
        where = None
        if self.match('WHERE'):
            where = self.parse_expression()
        return {'type': 'DELETE', 'table': table, 'where': where}

    def parse_expression(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.match('OR'):
            right = self.parse_and()
            left = {'type': 'binop', 'op': 'OR', 'left': left, 'right': right}
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.match('AND'):
            right = self.parse_not()
            left = {'type': 'binop', 'op': 'AND', 'left': left, 'right': right}
        return left

    def parse_not(self):
        if self.match('NOT'):
            expr = self.parse_not()
            return {'type': 'unop', 'op': 'NOT', 'expr': expr}
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_expr_value()

        # IS NULL / IS NOT NULL
        if self.match('IS'):
            if self.match('NOT'):
                self.expect('NULL')
                return {'type': 'is_not_null', 'expr': left}
            else:
                self.expect('NULL')
                return {'type': 'is_null', 'expr': left}

        if self.current().type == 'OP':
            op = self.advance().value
            right = self.parse_expr_value()
            return {'type': 'comparison', 'op': op, 'left': left, 'right': right}

        return left

    def parse_expr_value(self):
        t = self.current()
        if t.type == '(':
            self.advance()
            expr = self.parse_expression()
            self.expect(')')
            return expr
        if t.type == 'NULL':
            self.advance()
            return {'type': 'literal', 'value': None}
        if t.type == 'NUMBER':
            self.advance()
            return {'type': 'literal', 'value': t.value}
        if t.type == 'STRING':
            self.advance()
            return {'type': 'literal', 'value': t.value}
        if t.type == 'OP' and t.value == '-':
            self.advance()
            num = self.expect('NUMBER')
            return {'type': 'literal', 'value': -num.value}

        # Aggregate in expression context (e.g., HAVING)
        if t.type in ('COUNT', 'SUM', 'AVG', 'MIN', 'MAX'):
            func = t.type
            self.advance()
            self.expect('(')
            if func == 'COUNT' and self.current().type == '*':
                self.advance()
                self.expect(')')
                return {'type': 'aggregate_expr', 'func': 'COUNT', 'arg': '*'}
            else:
                col = self.parse_column_ref()
                self.expect(')')
                return {'type': 'aggregate_expr', 'func': func, 'arg': col}

        if t.type == 'IDENT':
            name = self.advance().value
            if self.match('.'):
                col = self.expect('IDENT').value
                return {'type': 'column_ref', 'table': name, 'column': col}
            return {'type': 'column_ref', 'table': None, 'column': name}

        raise SyntaxError(f"Error: syntax error near '{t.value if t.value else t.type}'")


# ============================================================================
# Executor
# ============================================================================

class Executor:
    """Execute parsed AST against the storage engine."""

    def __init__(self, storage):
        self.storage = storage
        self._transaction_backup = None

    def execute(self, ast):
        stmt_type = ast['type']

        if stmt_type == 'CREATE_TABLE':
            return self.exec_create_table(ast)
        elif stmt_type == 'DROP_TABLE':
            return self.exec_drop_table(ast)
        elif stmt_type == 'INSERT':
            return self.exec_insert(ast)
        elif stmt_type == 'SELECT':
            return self.exec_select(ast)
        elif stmt_type == 'UPDATE':
            return self.exec_update(ast)
        elif stmt_type == 'DELETE':
            return self.exec_delete(ast)
        elif stmt_type == 'BEGIN':
            return self.exec_begin()
        elif stmt_type == 'COMMIT':
            return self.exec_commit()
        elif stmt_type == 'ROLLBACK':
            return self.exec_rollback()
        else:
            raise RuntimeError(f"Error: unsupported feature '{stmt_type}'")

    def exec_begin(self):
        data = self.storage.get_data()
        self._transaction_backup = json.dumps(data)
        return {'type': 'ok'}

    def exec_commit(self):
        self._transaction_backup = None
        self.storage.save(self.storage.get_data())
        return {'type': 'ok'}

    def exec_rollback(self):
        if self._transaction_backup is not None:
            restored = json.loads(self._transaction_backup)
            self.storage._data = restored
            self.storage.save(restored)
            self._transaction_backup = None
        return {'type': 'ok'}

    def exec_create_table(self, ast):
        data = self.storage.get_data()
        name = ast['name']
        if name in data['tables']:
            raise RuntimeError(f"Error: table {name} already exists")
        data['tables'][name] = {
            'columns': ast['columns'],
            'rows': []
        }
        self.storage.save(data)
        return {'type': 'ok'}

    def exec_drop_table(self, ast):
        data = self.storage.get_data()
        name = ast['name']
        if name not in data['tables']:
            raise RuntimeError(f"Error: no such table: {name}")
        del data['tables'][name]
        self.storage.save(data)
        return {'type': 'ok'}

    def exec_insert(self, ast):
        data = self.storage.get_data()
        table_name = ast['table']
        if table_name not in data['tables']:
            raise RuntimeError(f"Error: no such table: {table_name}")

        table = data['tables'][table_name]
        col_defs = table['columns']
        col_names = [c[0] for c in col_defs]
        col_types = {c[0]: c[1] for c in col_defs}

        if ast['columns'] is not None:
            # Named column insert
            for c in ast['columns']:
                if c not in col_names:
                    raise RuntimeError(f"Error: no such column: {c}")
            if len(ast['columns']) != len(ast['values']):
                raise RuntimeError(f"Error: column count mismatch")
            row = [None] * len(col_defs)
            for i, c in enumerate(ast['columns']):
                idx = col_names.index(c)
                row[idx] = self._coerce_value(ast['values'][i], col_types[c])
        else:
            if len(ast['values']) != len(col_defs):
                raise RuntimeError(f"Error: expected {len(col_defs)} values but got {len(ast['values'])}")
            row = []
            for i, v in enumerate(ast['values']):
                row.append(self._coerce_value(v, col_defs[i][1]))

        table['rows'].append(row)
        self.storage.save(data)
        return {'type': 'rows_affected', 'count': 1}

    def _coerce_value(self, val, col_type):
        if val is None:
            return None
        if col_type == 'INTEGER':
            if isinstance(val, float):
                return int(val)
            if isinstance(val, int):
                return val
            if isinstance(val, str):
                try:
                    return int(val)
                except ValueError:
                    raise RuntimeError(f"Error: cannot convert '{val}' to INTEGER")
        elif col_type == 'REAL':
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                try:
                    return float(val)
                except ValueError:
                    raise RuntimeError(f"Error: cannot convert '{val}' to REAL")
        elif col_type == 'TEXT':
            if isinstance(val, str):
                return val
            return str(val)
        return val

    def exec_select(self, ast):
        data = self.storage.get_data()
        table_name = ast['table']
        if table_name not in data['tables']:
            raise RuntimeError(f"Error: no such table: {table_name}")

        table = data['tables'][table_name]
        col_defs = table['columns']
        table_alias = ast.get('table_alias') or table_name

        # Build combined column info
        all_columns = []  # list of (table_or_alias, col_name, col_type)
        for c in col_defs:
            all_columns.append((table_alias, c[0], c[1]))

        # Build rows as list of dicts with qualified names
        rows = []
        for row in table['rows']:
            r = {}
            for i, c in enumerate(col_defs):
                r[(table_alias, c[0])] = row[i]
                # Also store unqualified for convenience
                r[(None, c[0])] = row[i]
            rows.append(r)

        # Process JOINs
        for join in ast.get('joins', []):
            join_table_name = join['table']
            if join_table_name not in data['tables']:
                raise RuntimeError(f"Error: no such table: {join_table_name}")
            join_table = data['tables'][join_table_name]
            join_alias = join.get('table_alias') or join_table_name
            join_col_defs = join_table['columns']

            # Add join columns to all_columns
            new_columns = []
            for c in join_col_defs:
                new_columns.append((join_alias, c[0], c[1]))

            new_rows = []
            for left_row in rows:
                matched = False
                for join_row_data in join_table['rows']:
                    # Build combined row
                    combined = dict(left_row)
                    for i, c in enumerate(join_col_defs):
                        combined[(join_alias, c[0])] = join_row_data[i]
                    # Also add unqualified (but only if not ambiguous - last write wins for unqualified)
                    for i, c in enumerate(join_col_defs):
                        combined[(None, c[0])] = join_row_data[i]

                    if self.eval_expr(join['on'], combined, all_columns + new_columns):
                        new_rows.append(combined)
                        matched = True

                if not matched and join['type'] == 'LEFT':
                    combined = dict(left_row)
                    for c in join_col_defs:
                        combined[(join_alias, c[0])] = None
                        combined[(None, c[0])] = None
                    new_rows.append(combined)

            rows = new_rows
            all_columns = all_columns + new_columns

        # WHERE
        if ast.get('where'):
            rows = [r for r in rows if self.eval_expr(ast['where'], r, all_columns)]

        # GROUP BY
        if ast.get('group_by'):
            group_col = ast['group_by']
            groups = {}
            for r in rows:
                key = self._resolve_column(group_col, r, all_columns)
                # Use a hashable key representation
                key_hash = json.dumps(key, default=str)
                if key_hash not in groups:
                    groups[key_hash] = []
                groups[key_hash].append(r)

            # Build result rows
            grouped_rows = []
            for key_hash, group in groups.items():
                grouped_rows.append(group)

            # Apply HAVING
            if ast.get('having'):
                grouped_rows = [g for g in grouped_rows if self.eval_aggregate_expr(ast['having'], g, all_columns)]

            # Build final rows from aggregates
            return self._build_aggregate_result(ast, grouped_rows, all_columns)

        # Check if there are aggregate functions without GROUP BY
        has_aggregates = any(
            c.get('type') == 'aggregate' for c in ast['columns']
        )
        if has_aggregates and ast['columns'] != [{'type': 'star'}]:
            # Treat all rows as one group
            grouped_rows = [rows] if rows else [rows]
            return self._build_aggregate_result(ast, grouped_rows, all_columns)

        # ORDER BY
        if ast.get('order_by'):
            col_ref, direction = ast['order_by']
            def sort_key(row):
                val = self._resolve_column(col_ref, row, all_columns)
                is_null = val is None
                return (is_null, val if not is_null else 0)

            # For mixed types, we need careful comparison
            def sort_key_safe(row):
                val = self._resolve_column(col_ref, row, all_columns)
                if val is None:
                    return (1, 0, "")  # NULLs last
                if isinstance(val, (int, float)):
                    return (0, val, "")
                return (0, 0, str(val))

            rows.sort(key=sort_key_safe, reverse=(direction == 'DESC'))

            # For DESC, NULLs should still be last
            # Re-sort to ensure NULLs are last regardless of direction
            null_rows = [r for r in rows if self._resolve_column(col_ref, r, all_columns) is None]
            non_null_rows = [r for r in rows if self._resolve_column(col_ref, r, all_columns) is not None]

            def val_key(row):
                val = self._resolve_column(col_ref, row, all_columns)
                if isinstance(val, str):
                    return (1, 0, val)
                return (0, val if val is not None else 0, "")

            non_null_rows.sort(key=val_key, reverse=(direction == 'DESC'))
            rows = non_null_rows + null_rows

        # OFFSET
        offset = ast.get('offset')
        if offset:
            rows = rows[int(offset):]

        # LIMIT
        limit = ast.get('limit')
        if limit is not None:
            rows = rows[:int(limit)]

        # Build output
        return self._build_select_result(ast['columns'], rows, all_columns)

    def _build_aggregate_result(self, ast, grouped_rows, all_columns):
        result_columns = []
        result_rows = []

        # Determine output columns
        for col_spec in ast['columns']:
            if col_spec['type'] == 'star':
                for t, c, ct in all_columns:
                    result_columns.append(c)
            elif col_spec['type'] == 'aggregate':
                func = col_spec['func']
                arg = col_spec['arg']
                alias = col_spec.get('alias')
                if alias:
                    result_columns.append(alias)
                elif arg == '*':
                    result_columns.append(f"{func}(*)")
                else:
                    col_name = arg['column'] if isinstance(arg, dict) else arg
                    result_columns.append(f"{func}({col_name})")
            elif col_spec['type'] == 'column':
                alias = col_spec.get('alias')
                if alias:
                    result_columns.append(alias)
                else:
                    result_columns.append(col_spec['ref']['column'])

        for group in grouped_rows:
            row_vals = []
            for col_spec in ast['columns']:
                if col_spec['type'] == 'star':
                    # Use first row of group
                    if group:
                        for t, c, ct in all_columns:
                            row_vals.append(group[0].get((t, c)))
                    else:
                        for _ in all_columns:
                            row_vals.append(None)
                elif col_spec['type'] == 'aggregate':
                    row_vals.append(self._compute_aggregate(col_spec['func'], col_spec['arg'], group, all_columns))
                elif col_spec['type'] == 'column':
                    if group:
                        row_vals.append(self._resolve_column(col_spec['ref'], group[0], all_columns))
                    else:
                        row_vals.append(None)
            result_rows.append(row_vals)

        # ORDER BY
        if ast.get('order_by'):
            col_ref, direction = ast['order_by']
            # Find column index
            col_name = col_ref['column']
            if col_name in result_columns:
                idx = result_columns.index(col_name)

                def sort_key(row):
                    val = row[idx]
                    if val is None:
                        return (1, 0, "")
                    if isinstance(val, (int, float)):
                        return (0, val, "")
                    return (0, 0, str(val))

                null_rows = [r for r in result_rows if r[idx] is None]
                non_null = [r for r in result_rows if r[idx] is not None]
                non_null.sort(key=sort_key, reverse=(direction == 'DESC'))
                result_rows = non_null + null_rows

        # OFFSET/LIMIT
        offset = ast.get('offset')
        if offset:
            result_rows = result_rows[int(offset):]
        limit = ast.get('limit')
        if limit is not None:
            result_rows = result_rows[:int(limit)]

        header = '|'.join(self._escape(c) for c in result_columns)
        lines = [header]
        for row in result_rows:
            lines.append('|'.join(self._format_val(v) for v in row))
        return {'type': 'select', 'output': '\n'.join(lines)}

    def _compute_aggregate(self, func, arg, group, all_columns):
        if func == 'COUNT' and arg == '*':
            return len(group)

        # Get values
        values = []
        for row in group:
            val = self._resolve_column(arg, row, all_columns)
            values.append(val)

        non_null = [v for v in values if v is not None]

        if func == 'COUNT':
            return len(non_null)
        elif func == 'SUM':
            if not non_null:
                return None
            return sum(non_null)
        elif func == 'AVG':
            if not non_null:
                return None
            s = sum(non_null)
            result = s / len(non_null)
            if isinstance(result, float) and result == int(result):
                return result
            return result
        elif func == 'MIN':
            if not non_null:
                return None
            return min(non_null)
        elif func == 'MAX':
            if not non_null:
                return None
            return max(non_null)
        return None

    def eval_aggregate_expr(self, expr, group, all_columns):
        """Evaluate an expression in aggregate context (for HAVING)."""
        if expr is None:
            return True
        etype = expr.get('type')
        if etype == 'comparison':
            left = self._eval_aggregate_value(expr['left'], group, all_columns)
            right = self._eval_aggregate_value(expr['right'], group, all_columns)
            return self._compare(expr['op'], left, right)
        elif etype == 'binop':
            if expr['op'] == 'AND':
                return self.eval_aggregate_expr(expr['left'], group, all_columns) and \
                       self.eval_aggregate_expr(expr['right'], group, all_columns)
            elif expr['op'] == 'OR':
                return self.eval_aggregate_expr(expr['left'], group, all_columns) or \
                       self.eval_aggregate_expr(expr['right'], group, all_columns)
        elif etype == 'unop' and expr['op'] == 'NOT':
            return not self.eval_aggregate_expr(expr['expr'], group, all_columns)
        return False

    def _eval_aggregate_value(self, expr, group, all_columns):
        etype = expr.get('type')
        if etype == 'literal':
            return expr['value']
        elif etype == 'aggregate_expr':
            return self._compute_aggregate(expr['func'], expr['arg'], group, all_columns)
        elif etype == 'column_ref':
            if group:
                return self._resolve_column({'table': expr.get('table'), 'column': expr['column']}, group[0], all_columns)
            return None
        return None

    def _resolve_column(self, col_ref, row, all_columns):
        """Resolve a column reference to a value from a row dict."""
        if isinstance(col_ref, dict):
            table = col_ref.get('table')
            column = col_ref.get('column')
        else:
            table = None
            column = col_ref

        if table:
            key = (table, column)
            if key in row:
                return row[key]
            # Try to find by iterating
            for (t, c, ct) in all_columns:
                if t == table and c == column:
                    return row.get((t, c))
            raise RuntimeError(f"Error: no such column: {column}")

        # Unqualified - try (None, column) first, then search
        key = (None, column)
        if key in row:
            return row[key]

        # Search through all_columns
        matches = [(t, c) for (t, c, ct) in all_columns if c == column]
        if not matches:
            raise RuntimeError(f"Error: no such column: {column}")
        # Use the first match
        return row.get(matches[0], row.get((None, column)))

    def eval_expr(self, expr, row, all_columns):
        """Evaluate a WHERE expression against a row."""
        if expr is None:
            return True
        etype = expr.get('type')
        if etype == 'comparison':
            left = self._eval_value(expr['left'], row, all_columns)
            right = self._eval_value(expr['right'], row, all_columns)
            return self._compare(expr['op'], left, right)
        elif etype == 'binop':
            if expr['op'] == 'AND':
                return self.eval_expr(expr['left'], row, all_columns) and \
                       self.eval_expr(expr['right'], row, all_columns)
            elif expr['op'] == 'OR':
                return self.eval_expr(expr['left'], row, all_columns) or \
                       self.eval_expr(expr['right'], row, all_columns)
        elif etype == 'unop' and expr['op'] == 'NOT':
            return not self.eval_expr(expr['expr'], row, all_columns)
        elif etype == 'is_null':
            val = self._eval_value(expr['expr'], row, all_columns)
            return val is None
        elif etype == 'is_not_null':
            val = self._eval_value(expr['expr'], row, all_columns)
            return val is not None
        elif etype == 'literal':
            return expr['value'] is not None and expr['value'] != 0
        elif etype == 'column_ref':
            val = self._resolve_column({'table': expr.get('table'), 'column': expr['column']}, row, all_columns)
            return val is not None and val != 0
        return False

    def _eval_value(self, expr, row, all_columns):
        etype = expr.get('type')
        if etype == 'literal':
            return expr['value']
        elif etype == 'column_ref':
            return self._resolve_column({'table': expr.get('table'), 'column': expr['column']}, row, all_columns)
        elif etype == 'aggregate_expr':
            # Should not normally appear here unless in HAVING context
            return None
        return None

    def _compare(self, op, left, right):
        # NULL comparisons
        if left is None or right is None:
            if op == '=':
                return False
            elif op == '!=':
                return False
            else:
                return False

        try:
            if op == '=':
                return left == right
            elif op == '!=':
                return left != right
            elif op == '<':
                return left < right
            elif op == '>':
                return left > right
            elif op == '<=':
                return left <= right
            elif op == '>=':
                return left >= right
        except TypeError:
            return False
        return False

    def _build_select_result(self, col_specs, rows, all_columns):
        """Build the output for a SELECT statement."""
        # Determine output column names and how to extract values
        output_cols = []
        extractors = []

        for col_spec in col_specs:
            if col_spec['type'] == 'star':
                for t, c, ct in all_columns:
                    output_cols.append(c)
                    t_copy, c_copy = t, c
                    extractors.append(lambda row, t=t_copy, c=c_copy: row.get((t, c)))
            elif col_spec['type'] == 'column':
                ref = col_spec['ref']
                alias = col_spec.get('alias')
                col_name = alias if alias else ref['column']
                output_cols.append(col_name)
                # Validate column exists
                ref_copy = dict(ref)
                extractors.append(lambda row, r=ref_copy: self._resolve_column(r, row, all_columns))

        header = '|'.join(self._escape(c) for c in output_cols)
        lines = [header]
        for row in rows:
            vals = []
            for ext in extractors:
                vals.append(ext(row))
            lines.append('|'.join(self._format_val(v) for v in vals))

        return {'type': 'select', 'output': '\n'.join(lines)}

    def _escape(self, val):
        """Escape a string for output."""
        if val is None:
            return ''
        s = str(val)
        s = s.replace('\\', '\\\\')
        s = s.replace('|', '\\|')
        s = s.replace('\n', '\\n')
        return s

    def _format_val(self, val):
        """Format a value for output."""
        if val is None:
            return ''
        if isinstance(val, float):
            if val == int(val) and not (val != val):  # not NaN
                # Check if it should be displayed as float
                return self._escape(str(val))
            return self._escape(str(val))
        if isinstance(val, bool):
            return self._escape(str(int(val)))
        return self._escape(str(val))

    def exec_update(self, ast):
        data = self.storage.get_data()
        table_name = ast['table']
        if table_name not in data['tables']:
            raise RuntimeError(f"Error: no such table: {table_name}")

        table = data['tables'][table_name]
        col_defs = table['columns']
        col_names = [c[0] for c in col_defs]
        col_types = {c[0]: c[1] for c in col_defs}

        # Validate assignment columns
        for col, val in ast['assignments']:
            if col not in col_names:
                raise RuntimeError(f"Error: no such column: {col}")

        all_columns = [(table_name, c[0], c[1]) for c in col_defs]
        count = 0

        for i, row in enumerate(table['rows']):
            # Build row dict
            row_dict = {}
            for j, c in enumerate(col_defs):
                row_dict[(table_name, c[0])] = row[j]
                row_dict[(None, c[0])] = row[j]

            if self.eval_expr(ast.get('where'), row_dict, all_columns):
                # Apply assignments
                for col, val_expr in ast['assignments']:
                    if isinstance(val_expr, dict):
                        new_val = self._eval_value(val_expr, row_dict, all_columns)
                    else:
                        new_val = val_expr
                    idx = col_names.index(col)
                    new_val = self._coerce_value(new_val, col_types[col])
                    table['rows'][i][idx] = new_val
                count += 1

        self.storage.save(data)
        return {'type': 'rows_affected', 'count': count}

    def exec_delete(self, ast):
        data = self.storage.get_data()
        table_name = ast['table']
        if table_name not in data['tables']:
            raise RuntimeError(f"Error: no such table: {table_name}")

        table = data['tables'][table_name]
        col_defs = table['columns']
        all_columns = [(table_name, c[0], c[1]) for c in col_defs]

        if ast.get('where') is None:
            count = len(table['rows'])
            table['rows'] = []
        else:
            new_rows = []
            count = 0
            for row in table['rows']:
                row_dict = {}
                for j, c in enumerate(col_defs):
                    row_dict[(table_name, c[0])] = row[j]
                    row_dict[(None, c[0])] = row[j]
                if self.eval_expr(ast['where'], row_dict, all_columns):
                    count += 1
                else:
                    new_rows.append(row)
            table['rows'] = new_rows

        self.storage.save(data)
        return {'type': 'rows_affected', 'count': count}


# ============================================================================
# CLI
# ============================================================================

def main():
    if len(sys.argv) < 3:
        print("Usage: mini_sqlite.py <database> <sql>", file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    sql = sys.argv[2]

    try:
        storage = StorageEngine(db_path)
        storage.load()
    except IOError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    try:
        tokenizer = Tokenizer()
        tokens = tokenizer.tokenize(sql)
        parser = Parser(tokens)
        ast = parser.parse()
    except SyntaxError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    try:
        executor = Executor(storage)
        result = executor.execute(ast)
    except IOError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    # Output result
    if result['type'] == 'ok':
        print("OK")
    elif result['type'] == 'rows_affected':
        count = result['count']
        if count == 1:
            print("1 row affected")
        else:
            print(f"{count} rows affected")
    elif result['type'] == 'select':
        print(result['output'])


if __name__ == '__main__':
    main()
