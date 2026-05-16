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
            return ast.literal_eval(tree.body[0].value)

        # Otherwise, scan for the first assignment of a list/dict.
        for node in tree.body:
            if isinstance(node, ast.Assign):
                value = node.value
                if isinstance(value, (ast.List, ast.Dict)):
                    return ast.literal_eval(value)

        raise ValueError(f"No top-level list or dict literal found in {file_path}")

    def load_and_insert_from_file(self, file_path: str, table_name: str, primary_key: Optional[str] = "template_name"):
        rows = self.load_python_data_file(file_path)
        if not rows:
            return
        self.create_table_from_sample(table_name, rows[0], primary_key=primary_key)
        self.insert_many(table_name, rows, replace=True)
    
if __name__ == "__main__":
    db = Database("zero_hour.db")
    db.connect()
    template_file = "E:\\PythonProjects\\General_Zero_Hour\\GeneralsGameCode\\AI_Agent\\template_database.txt"
    try:
        db.load_and_insert_from_file(template_file, "armies_units", primary_key="template_name")
        data = db.fetch_data("armies_units", conditions={"army_name": "america"})
        print(data[:3])

        matches = db.fetch_by_json_list_contains(
            "armies_units",
            "strong_against",
            "infantry",
            conditions={"army_name": "america"}
        )
        print("Example rows where strong_against contains 'infantry':", matches[:3])
    except Exception as exc:
        print(f"Unable to load templates: {exc}")
    finally:
        db.close()