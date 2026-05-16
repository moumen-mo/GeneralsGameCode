import ast
import json
import sqlite3
from typing import Any, Dict, List, Optional

class Database:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.connection = None
        self.table_names = []

    def connect(self):
        try:
            self.connection = sqlite3.connect(self.db_name)
            self.connection.row_factory = sqlite3.Row
            print("Database connection established.")
        except sqlite3.Error as e:
            print(f"Error connecting to database: {e}")
    def get_column_names(self, table_name: str) -> List[str]:
        query = f"PRAGMA table_info({table_name})"
        columns_info = self.execute_query(query)
        if columns_info is None:
            return []
        return [col["name"] for col in columns_info]
    
    def execute_query(self, query: str, params: Optional[tuple] = None):
        if self.connection is None:
            print("No database connection.")
            return None

        try:
            cursor = self.connection.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            self.connection.commit()
            return cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Error executing query: {e}")
            return None

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
            print("Database connection closed.")

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return value

    @staticmethod
    def _deserialize_value(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (list, dict)):
                return parsed
        except (ValueError, TypeError):
            pass
        return value

    def _deserialize_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {key: self._deserialize_value(row[key]) for key in row.keys()}

    def create_table(self, table_name: str, columns: Dict[str, str]):
        columns_str = ", ".join([f"{col} {dtype}" for col, dtype in columns.items()])
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_str})"
        self.execute_query(query)
        if table_name not in self.table_names:
            self.table_names.append(table_name)

    def create_table_from_sample(self, table_name: str, sample_row: Dict[str, Any], primary_key: Optional[str] = None):
        columns: Dict[str, str] = {}
        for key in sample_row:
            if key == primary_key:
                columns[key] = "TEXT PRIMARY KEY"
            else:
                columns[key] = "TEXT"
        self.create_table(table_name, columns)

    def insert_data(self, table_name: str, data: Dict[str, Any], replace: bool = False):
        columns_str = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        op = "INSERT OR REPLACE" if replace else "INSERT"
        query = f"{op} INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        params = tuple(self._serialize_value(value) for value in data.values())
        self.execute_query(query, params)

    def insert_many(self, table_name: str, rows: List[Dict[str, Any]], replace: bool = False):
        if not rows:
            return
        columns = list(rows[0].keys())
        columns_str = ", ".join(columns)
        placeholders = ", ".join(["?" for _ in columns])
        op = "INSERT OR REPLACE" if replace else "INSERT"
        query = f"{op} INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        serialized_rows = [tuple(self._serialize_value(row[col]) for col in columns) for row in rows]
        if self.connection is None:
            print("No database connection.")
            return
        try:
            cursor = self.connection.cursor()
            cursor.executemany(query, serialized_rows)
            self.connection.commit()
        except sqlite3.Error as e:
            print(f"Error executing bulk insert: {e}")

    def fetch_data(self, table_name: str, conditions: Optional[Dict[str, Any]] = None, as_dict: bool = True):
        query = f"SELECT * FROM {table_name}"
        params = None
        if conditions:
            conditions_str = " AND ".join([f"{col} = ?" for col in conditions])
            query += f" WHERE {conditions_str}"
            params = tuple(self._serialize_value(value) for value in conditions.values())

        rows = self.execute_query(query, params)
        if rows is None:
            return None
        return [self._deserialize_row(row) for row in rows] if as_dict else rows
    def save_query_results_to_table(self, results: List[tuple], new_table_name: str):
        if self.connection is None:
            print("No database connection.")
            return
        try:
            if not results:
                print("Query returned no results.")
                return
            cursor = self.connection.cursor()

            # Accept list of dicts or list of tuples
            if isinstance(results[0], dict):
                columns = list(results[0].keys())
                rows = [tuple(self._serialize_value(r[col]) for col in columns) for r in results]
            else:
                # Assume sequence of tuples; generate generic column names
                cols_count = len(results[0])
                columns = [f"col{i}" for i in range(1, cols_count + 1)]
                rows = results

            columns_str = ", ".join([f"{col} TEXT" for col in columns])
            create_query = f"CREATE TABLE IF NOT EXISTS {new_table_name} ({columns_str})"
            cursor.execute(create_query)
            placeholders = ", ".join(["?" for _ in columns])
            insert_query = f"INSERT INTO {new_table_name} ({', '.join(columns)}) VALUES ({placeholders})"
            cursor.executemany(insert_query, rows)
            self.connection.commit()
        except sqlite3.Error as e:
            print(f"Error saving query results to table: {e}")
            self.connection.rollback()
            cursor.close()
    def delete_specific_columns_in_table(self, table_name: str, columns_to_delete: List[str]):
        existing_columns = self.get_column_names(table_name)
        remaining_columns = [col for col in existing_columns if col not in columns_to_delete]
        if not remaining_columns:
            print("Cannot delete all columns from the table.")
            return

        temp_table_name = f"{table_name}_temp"
        columns_str = ", ".join([f"{col} TEXT" for col in remaining_columns])
        create_query = f"CREATE TABLE {temp_table_name} ({columns_str})"
        insert_query = f"INSERT INTO {temp_table_name} ({', '.join(remaining_columns)}) SELECT {', '.join(remaining_columns)} FROM {table_name}"
        drop_query = f"DROP TABLE {table_name}"
        rename_query = f"ALTER TABLE {temp_table_name} RENAME TO {table_name}"

        try:
            cursor = self.connection.cursor()
            cursor.execute(create_query)
            cursor.execute(insert_query)
            cursor.execute(drop_query)
            cursor.execute(rename_query)
            self.connection.commit()
        except sqlite3.Error as e:
            print(f"Error deleting specific columns: {e}")
            self.connection.rollback()

    def fetch_by_json_list_contains(self, table_name: str, column: str, item: Any, conditions: Optional[Dict[str, Any]] = None):
        rows = self.fetch_data(table_name, conditions=conditions, as_dict=True)
        if rows is None:
            return None
        return [row for row in rows if isinstance(row.get(column), list) and item in row[column]]

    def delete_data(self, table_name: str, conditions: Dict[str, Any]):
        conditions_str = " AND ".join([f"{col} = ?" for col in conditions])
        query = f"DELETE FROM {table_name} WHERE {conditions_str}"
        self.execute_query(query, tuple(self._serialize_value(value) for value in conditions.values()))

    def update_data(self, table_name: str, data: Dict[str, Any], conditions: Dict[str, Any]):
        set_str = ", ".join([f"{col} = ?" for col in data])
        conditions_str = " AND ".join([f"{col} = ?" for col in conditions])
        query = f"UPDATE {table_name} SET {set_str} WHERE {conditions_str}"
        params = tuple(self._serialize_value(value) for value in data.values()) + tuple(self._serialize_value(value) for value in conditions.values())
        self.execute_query(query, params)

    def list_tables(self) -> List[str]:
        query = "SELECT name FROM sqlite_master WHERE type='table'"
        tables = self.execute_query(query)
        return [table[0] for table in tables] if tables else []

    @staticmethod
    def load_python_data_file(file_path: str) -> List[Dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8") as file:
            source = file.read()
        tree = ast.parse(source, file_path)
        # If the file contains only a top-level literal list/dict, return it.
        if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
            parsed = ast.literal_eval(tree.body[0].value)
            if isinstance(parsed, (list, dict)):
                return parsed
            raise ValueError(f"Top-level literal in {file_path} is not a list or dict")

        # Otherwise, scan for the first assignment of a list/dict.
        for node in tree.body:
            if isinstance(node, ast.Assign):
                value = node.value
                if isinstance(value, (ast.List, ast.Dict)):
                    parsed = ast.literal_eval(value)
                    if isinstance(parsed, (list, dict)):
                        return parsed
                    raise ValueError(f"Assigned value in {file_path} is not a list or dict")

        raise ValueError(f"No top-level list or dict literal found in {file_path}")

    def load_and_insert_from_file(self, file_path: str, table_name: str, primary_key: Optional[str] = "template_name"):
        rows = self.load_python_data_file(file_path)
        if rows is None:
            raise ValueError(f"Loaded data from {file_path} is None")

        # If a single dict was returned, wrap it in a list
        if isinstance(rows, dict):
            rows = [rows]

        if not isinstance(rows, list) or len(rows) == 0:
            raise ValueError(f"No rows to insert from {file_path}")

        if not isinstance(rows[0], dict):
            raise ValueError(f"Expected rows to be a list of dicts, got {type(rows[0])}")

        self.create_table_from_sample(table_name, rows[0], primary_key=primary_key)
        self.insert_many(table_name, rows, replace=True)
