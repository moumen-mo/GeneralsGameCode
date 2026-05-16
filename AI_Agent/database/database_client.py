from AI_Agent.database.datebase import Database
import ast
import json
import sqlite3
from typing import Any, Dict, List, Optional

def build_main_database():
    db = Database("zero_hour.db")
    db.connect()
    table_name = "armies_units"
    table_columns = {
        "template_name": "TEXT PRIMARY KEY",
        "army_name": "TEXT",
        "army_type": "TEXT",
        "role": "TEXT",
        "strong_against": "TEXT",
        "weak_against": "TEXT",
        "description": "TEXT",
        "economy_unit": "INTEGER",
        "fight_unit": "INTEGER"
    } 
    db.create_table_from_sample(table_name, table_columns)
    template_file = "E:\\PythonProjects\\General_Zero_Hour\\GeneralsGameCode\\AI_Agent\\template_database.txt"
    try:
        db.load_and_insert_from_file(template_file, "armies_units", primary_key="template_name")
    except Exception as exc:
        print(f"Unable to load templates: {exc}")
    finally:
        db.close()

if __name__ == "__main__":
    db = Database("zero_hour.db")
    db.connect()
    try:
        data_usa = db.fetch_data("armies_units", conditions={"army_name": "america","economy_unit": 1}, as_dict=True)
        db.save_query_results_to_table(data_usa, "usa_economy_units")
        data_chaina = db.fetch_data("armies_units", conditions={"army_name": "china","economy_unit": 1}, as_dict=True)
        db.save_query_results_to_table(data_chaina, "china_economy_units")
        data_gla = db.fetch_data("armies_units", conditions={"army_name": "gla","economy_unit": 1}, as_dict=True)
        db.save_query_results_to_table(data_gla, "gla_economy_units")

    except Exception as exc:
        print(f"Unable to load templates: {exc}")
    finally:
        db.close()