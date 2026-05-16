import os
import hashlib
import psycopg2
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# --- НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД ---
load_dotenv()
DB_USER = "postgres"
DB_PASSWORD = os.getenv("DB_PASS", "твой_пароль_если_нет")
DB_HOST = "127.0.0.1"
DB_PORT = "5432"
DB_NAME = "drilling_fluids"

def get_db_connection():
    return psycopg2.connect(database=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)

def execute_query(query, params=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Ошибка БД: {e}")
        return False

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    conn = get_db_connection()
    cur = conn.cursor()
    hashed = hash_password(password)
    cur.execute("SELECT id, role FROM users WHERE username = %s AND password_hash = %s", (username, hashed))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def get_all_users():
    conn = get_db_connection()
    df = pd.read_sql("SELECT id, username, role FROM users ORDER BY id;", conn)
    conn.close()
    return df

def add_user_to_db(username, password, role):
    hashed_pw = hash_password(password)
    try:
        return execute_query("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                             (username, hashed_pw, role))
    except Exception:
        return False

def add_fluid_to_db(name, base_type, d_min, d_max, t_max, inh, fric, eco, cost):
    query = "INSERT INTO fluids (name, base_type, density_min, density_max, temp_max, inhibition, friction, eco_score, cost) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
    return execute_query(query, (name, base_type, d_min, d_max, t_max, inh, fric, eco, cost))

def get_all_reagents():
    conn = get_db_connection()
    df = pd.read_sql("SELECT id, name, function_type, target_lithology, max_temp FROM reagents ORDER BY id;", conn)
    conn.close()
    return df

def add_reagent_to_db(name, func_type, litho, max_t):
    query = "INSERT INTO reagents (name, function_type, target_lithology, max_temp) VALUES (%s, %s, %s, %s)"
    return execute_query(query, (name, func_type, litho, max_t))

def add_recipe_item(fluid_id, reagent_id, conc):
    query = "INSERT INTO fluid_reagents (fluid_id, reagent_id, concentration) VALUES (%s, %s, %s)"
    return execute_query(query, (int(fluid_id), int(reagent_id), float(conc)))

def get_fluid_recipe(fluid_id):
    conn = get_db_connection()
    query = """
    SELECT r.name AS "Реагент", fr.concentration AS "Кг на 1 м³", r.function_type AS "Назначение", r.target_lithology AS "Условие"
    FROM fluid_reagents fr
    JOIN reagents r ON fr.reagent_id = r.id
    WHERE fr.fluid_id = %s
    """
    df = pd.read_sql(query, conn, params=(int(fluid_id),))
    conn.close()
    return df

def get_user_projects(user_id):
    conn = get_db_connection()
    df = pd.read_sql("SELECT id, name FROM projects WHERE user_id = %s ORDER BY created_at DESC;", conn,
                     params=(int(user_id),))
    conn.close()
    return df

def create_project(user_id, name):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (user_id, name) VALUES (%s, %s) RETURNING id;", (int(user_id), str(name)))
    project_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return project_id

def delete_project_from_db(project_id):
    execute_query("DELETE FROM projects WHERE id = %s;", (int(project_id),))

def save_interval_to_db(interval_data, project_id):
    query = """
    INSERT INTO calculation_history 
    (project_id, user_id, well_name, interval_name, depth, diameter, p_pl, t_zab, angle, fluid_type, 
     req_density_min, req_density_max, req_viscosity, preset_id, selected_fluid_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, (SELECT id FROM presets WHERE name = %s LIMIT 1), %s)
    """
    params = (
        int(project_id), int(st.session_state['user_id']), str(st.session_state['well_name']),
        str(interval_data['Имя_интервала']),
        float(interval_data['H']), float(interval_data['D_mm']), float(interval_data['P_pl']),
        float(interval_data['T_zab']),
        float(interval_data['Angle']), str(interval_data['Fluid_type']), float(interval_data['Rho_min']),
        float(interval_data['Rho_max']),
        float(interval_data['Viscosity']), str(interval_data['Preset']), int(interval_data['Fluid_id'])
    )
    execute_query(query, params)

def delete_interval_from_db(interval_id):
    execute_query("DELETE FROM calculation_history WHERE id = %s;", (int(interval_id),))

def get_presets():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM presets;", conn)
    conn.close()
    return df

def get_fluids_filtered(rho_min, rho_max, temp_max):
    conn = get_db_connection()
    query = f"""
    SELECT id, name AS "Название", base_type AS "Основа", density_min, density_max, temp_max, inhibition, friction, eco_score, cost AS "Стоимость", density_min AS base_density
    FROM fluids WHERE temp_max >= {temp_max} AND density_max >= {rho_min} AND density_min <= {rho_max}
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def get_history():
    conn = get_db_connection()
    query = """
    SELECT ch.calc_date AS "Дата", u.username AS "Инженер", p.name AS "Условия", f.name AS "Победитель (Раствор)"
    FROM calculation_history ch
    JOIN presets p ON ch.preset_id = p.id
    JOIN fluids f ON ch.selected_fluid_id = f.id
    JOIN users u ON ch.user_id = u.id
    ORDER BY ch.calc_date DESC LIMIT 50;
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df