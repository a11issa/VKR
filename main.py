import streamlit as st
import psycopg2
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv
from fpdf import FPDF

# --- НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД ---
load_dotenv()
DB_USER = "postgres"
DB_PASSWORD = os.getenv("DB_PASS", "твой_пароль_если_нет")
DB_HOST = "127.0.0.1"
DB_PORT = "5432"
DB_NAME = "drilling_fluids"

st.set_page_config(page_title="Подбор буровых растворов", page_icon="🛢️", layout="wide")

# ==========================================
# ИНИЦИАЛИЗАЦИЯ ПАМЯТИ (SESSION STATE)
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_role' not in st.session_state:
    st.session_state['user_role'] = None
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'project_intervals' not in st.session_state:
    st.session_state['project_intervals'] = []
if 'well_name' not in st.session_state:
    st.session_state['well_name'] = "Скважина №1"


# ==========================================
# ФУНКЦИИ БАЗЫ ДАННЫХ
# ==========================================
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


def authenticate_user(username, password):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, role FROM users WHERE username = %s AND password_hash = %s", (username, password))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def get_presets():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM presets;", conn)
    conn.close()
    return df


def get_fluids_filtered(rho_min, rho_max, temp_max):
    conn = get_db_connection()
    query = f"""
    SELECT id, name AS "Название", base_type AS "Основа", density_min, density_max, temp_max AS "Термо", inhibition, friction, eco_score, cost AS "Стоимость"
    FROM fluids WHERE temp_max >= {temp_max} AND density_max >= {rho_min} AND density_min <= {rho_max}
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df


def save_interval_to_db(interval_data):
    query = """
    INSERT INTO calculation_history 
    (user_id, well_name, interval_name, depth, p_pl, t_zab, angle, fluid_type, 
     req_density_min, req_density_max, req_viscosity, preset_id, selected_fluid_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, (SELECT id FROM presets WHERE name = %s LIMIT 1), %s)
    """
    params = (
        int(st.session_state['user_id']),
        str(st.session_state['well_name']),
        str(interval_data['Имя_интервала']),
        float(interval_data['H']),
        float(interval_data['P_pl']),
        float(interval_data['T_zab']),
        float(interval_data['Angle']),
        str(interval_data['Fluid_type']),
        float(interval_data['Rho_min']),
        float(interval_data['Rho_max']),
        float(interval_data['Viscosity']),
        str(interval_data['Preset']),
        int(interval_data['Fluid_id'])
    )
    execute_query(query, params)


def get_history():
    conn = get_db_connection()
    query = """
    SELECT ch.calc_date AS "Дата", u.username AS "Инженер", ch.well_name AS "Скважина", 
           ch.interval_name AS "Интервал", ch.depth AS "Глубина", p.name AS "Условия", f.name AS "Победитель (Раствор)"
    FROM calculation_history ch
    JOIN presets p ON ch.preset_id = p.id
    JOIN fluids f ON ch.selected_fluid_id = f.id
    JOIN users u ON ch.user_id = u.id
    ORDER BY ch.calc_date DESC LIMIT 50;
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df


# ==========================================
# МАТЕМАТИКА И ФИЗИКА
# ==========================================
def calculate_physics(H, P_pl, T_zab, angle, fluid_type):
    delta_P = 0
    if fluid_type == "Нефть":
        if H <= 1000:
            delta_P = 1.0
        elif H <= 2500:
            delta_P = 1.5
        elif H <= 4500:
            delta_P = 2.0
        else:
            delta_P = 2.5
    else:
        if H <= 1000:
            delta_P = 1.5
        elif H <= 2500:
            delta_P = 2.0
        elif H <= 4500:
            delta_P = 2.25
        else:
            delta_P = 2.7

    rho_min = (P_pl + delta_P) * 1000 / (9.81 * H)
    P_grp = 0.0083 * H + 0.66 * P_pl
    rho_max = (P_grp) * 1000 / (9.81 * H)
    req_viscosity = 33 * rho_min - 22
    req_dns = 10 + 1.377 * angle
    return round(rho_min, 2), round(rho_max, 2), round(req_viscosity, 1), round(req_dns, 1)


def calculate_topsis(df, weights):
    matrix = df[["inhibition", "friction", "eco_score", "Стоимость"]].values.astype(float)
    col_sums = np.sqrt((matrix ** 2).sum(axis=0))
    col_sums[col_sums == 0] = 1e-10
    norm_matrix = matrix / col_sums
    weighted_matrix = norm_matrix * weights

    ideal_best = [weighted_matrix[:, 0].max(), weighted_matrix[:, 1].min(), weighted_matrix[:, 2].max(),
                  weighted_matrix[:, 3].min()]
    ideal_worst = [weighted_matrix[:, 0].min(), weighted_matrix[:, 1].max(), weighted_matrix[:, 2].min(),
                   weighted_matrix[:, 3].max()]

    dist_best = np.sqrt(((weighted_matrix - ideal_best) ** 2).sum(axis=1))
    dist_worst = np.sqrt(((weighted_matrix - ideal_worst) ** 2).sum(axis=1))

    denominator = dist_best + dist_worst
    rating = np.zeros_like(dist_worst)
    mask = denominator != 0
    rating[mask] = dist_worst[mask] / denominator[mask]
    rating[~mask] = 1.0

    return rating


# ==========================================
# ЭКСПОРТ В PDF
# ==========================================
def create_summary_pdf(well_name, intervals):
    pdf = FPDF(orientation='P')
    pdf.add_page()
    font_path = "Roboto-Regular.ttf"

    if os.path.exists(font_path):
        pdf.add_font("Roboto", "", font_path, uni=True)
        pdf.set_font("Roboto", size=16)
    else:
        pdf.set_font("Arial", size=16)

    pdf.cell(0, 10, txt="ПАСПОРТ ПРОМЫВКИ СКВАЖИНЫ", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font(pdf.font_family, size=12)
    pdf.cell(0, 10, txt=f"Объект: {well_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    for it in intervals:
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font(pdf.font_family, size=12)
        pdf.cell(0, 10, txt=f" Интервал: {it['Имя_интервала']}", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(pdf.font_family, size=10)
        pdf.cell(0, 8, txt=f"  Условия: Глубина {it['H']} м | Давление {it['P_pl']} МПа | Температура {it['T_zab']} °C",
                 new_x="LMARGIN", new_y="NEXT", border='LR')
        pdf.cell(0, 8, txt=f"  Требуемое окно бурения: Плотность от {it['Rho_min']} до {it['Rho_max']} г/см3",
                 new_x="LMARGIN", new_y="NEXT", border='LR')
        pdf.cell(0, 8, txt=f"  Осложнение (МАИ): {it['Preset']}", new_x="LMARGIN", new_y="NEXT", border='LRB')

        pdf.ln(2)
        pdf.set_font(pdf.font_family, size=11)
        pdf.cell(0, 8, txt="  Рекомендуемые растворы:", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(pdf.font_family, size=10)
        for idx, fluid in enumerate(it['Top_3']):
            text = f"    {idx + 1}. {fluid['Название']} ({fluid['Основа']})"
            pdf.cell(140, 8, txt=text)
            pdf.cell(0, 8, txt=f"Рейтинг: {fluid['Рейтинг']}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)

    return pdf.output(dest='S')


# ==========================================
# СТРАНИЦА: АВТОРИЗАЦИЯ
# ==========================================
def show_login_page():
    st.title("🔐 Вход в систему")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Имя пользователя")
            password = st.text_input("Пароль", type="password")
            submitted = st.form_submit_button("Войти", use_container_width=True)

            if submitted:
                user = authenticate_user(username, password)
                if user:
                    st.session_state['logged_in'] = True
                    st.session_state['user_id'] = user[0]
                    st.session_state['user_role'] = user[1]
                    st.rerun()
                else:
                    st.error("Неверный логин или пароль")


# ==========================================
# СТРАНИЦА: ИНЖЕНЕР (ПОДБОР ИНТЕРВАЛОВ)
# ==========================================
def show_engineer_panel():
    st.title(f"🛢️ Проектирование промывки: {st.session_state['well_name']}")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.session_state['well_name'] = st.text_input("Шифр скважины", value=st.session_state['well_name'])
    with c3:
        st.write("")
        st.write("")
        if st.button("🚪 Выйти из аккаунта", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    st.markdown("---")
    col_input, col_results = st.columns([1, 1.5])

    with col_input:
        st.subheader("➕ Добавить интервал")
        with st.form("add_interval_form", clear_on_submit=False):
            int_name = st.text_input("Название (напр. Кондуктор)", value="Интервал 1")
            H = st.number_input("Глубина подошвы (H), м", min_value=10.0, value=1000.0, step=50.0)
            P_pl = st.number_input("Пластовое давление (Pпл), МПа", min_value=1.0, value=12.0, step=0.5)
            T_zab = st.number_input("Макс. температура (Tзаб), °C", min_value=10.0, value=40.0, step=5.0)

            c_a1, c_a2 = st.columns(2)
            angle = c_a1.number_input("Зенитный угол (α)", value=0.0)
            fluid_type = c_a2.selectbox("Флюид", ["Нефть", "Газ"])

            presets_df = get_presets()
            selected_preset_name = st.selectbox("Осложнения (МАИ)",
                                                presets_df['name'].tolist() if not presets_df.empty else [])
            submit_btn = st.form_submit_button("Рассчитать и добавить", type="primary", use_container_width=True)

        if submit_btn and not presets_df.empty:
            rho_min, rho_max, req_viscosity, req_dns = calculate_physics(H, P_pl, T_zab, angle, fluid_type)

            if rho_min > rho_max:
                st.error("⚠️ Давление превышает градиент ГРП! Раствор подобрать невозможно.")
            else:
                df = get_fluids_filtered(rho_min, rho_max, T_zab)
                if df.empty:
                    st.error("❌ Под эти жесткие условия в базе нет растворов.")
                else:
                    preset_row = presets_df[presets_df['name'] == selected_preset_name].iloc[0]
                    weights = np.array(
                        [preset_row['weight_inhibition'], preset_row['weight_friction'], preset_row['weight_eco'],
                         preset_row['weight_cost']])

                    df["Рейтинг"] = calculate_topsis(df, weights)
                    df = df.sort_values("Рейтинг", ascending=False).reset_index(drop=True)

                    top_3_fluids = []
                    for idx, row in df.head(3).iterrows():
                        top_3_fluids.append({
                            "Название": row['Название'],
                            "Основа": row['Основа'],
                            "Рейтинг": f"{(row['Рейтинг'] * 100):.1f}%"
                        })

                    winner = df.iloc[0]
                    interval_data = {
                        "Имя_интервала": int_name, "H": H, "P_pl": P_pl, "T_zab": T_zab,
                        "Angle": angle, "Fluid_type": fluid_type, "Preset": selected_preset_name,
                        "Rho_min": rho_min, "Rho_max": rho_max, "Viscosity": req_viscosity,
                        "Fluid_id": int(winner['id']), "Раствор": winner['Название'],
                        "Рейтинг": f"{(winner['Рейтинг'] * 100):.1f}%",
                        "Top_3": top_3_fluids
                    }
                    st.session_state['project_intervals'].append(interval_data)
                    st.rerun()

    with col_results:
        st.subheader("📑 Сводка по интервалам")

        if len(st.session_state['project_intervals']) > 0:

            # Вывод интервалов в виде карточек
            for i, it in enumerate(st.session_state['project_intervals']):
                with st.container():
                    c_info, c_del = st.columns([12, 1])
                    with c_info:
                        st.markdown(f"**{it['Имя_интервала']} (до {it['H']} м)**")
                        st.caption(
                            f"Плотность: {it['Rho_min']} - {it['Rho_max']} г/см³ | Вязкость: {it['Viscosity']} мПа·с")

                        # Вывод трех растворов в столбец (без лишних слов и иконок)
                        for idx, fluid in enumerate(it['Top_3']):
                            st.write(f"{idx + 1}. {fluid['Название']} — {fluid['Рейтинг']}")

                    with c_del:
                        # Крестик для удаления интервала
                        if st.button("❌", key=f"del_btn_{i}", help="Удалить этот интервал"):
                            st.session_state['project_intervals'].pop(i)
                            st.rerun()
                st.divider()  # Горизонтальная линия между карточками

            # Кнопки финального сохранения
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button("🗑️ Очистить скважину", use_container_width=True):
                    st.session_state['project_intervals'] = []
                    st.rerun()

            with c_btn2:
                pdf_bytes = create_summary_pdf(st.session_state['well_name'], st.session_state['project_intervals'])
                # Кнопка переименована
                if st.download_button(label="💾 Сохранить отчет",
                                      data=bytes(pdf_bytes),
                                      file_name=f"Паспорт_{st.session_state['well_name']}.pdf",
                                      mime="application/pdf", type="primary", use_container_width=True):
                    for it in st.session_state['project_intervals']:
                        save_interval_to_db(it)
                    st.success("Все интервалы сохранены в базу данных!")
        else:
            st.info("Добавьте интервалы слева, чтобы сформировать паспорт скважины.")


# ==========================================
# СТРАНИЦА: АДМИНИСТРАТОР
# ==========================================
def show_admin_panel():
    c1, c2 = st.columns([4, 1])
    c1.title("🛠️ Панель администратора БД")
    if c2.button("🚪 Выйти"):
        st.session_state.clear()
        st.rerun()

    tab_history, tab_add = st.tabs(["🕰️ История", "➕ Добавление растворов"])

    with tab_history:
        if st.button("🔄 Обновить историю"): pass
        history_df = get_history()
        if not history_df.empty:
            st.dataframe(history_df, use_container_width=True)
        else:
            st.info("История пуста.")

    with tab_add:
        with st.form("add_fluid_form", clear_on_submit=True):
            st.subheader("Внесение нового раствора в базу")
            f_name = st.text_input("Название раствора")
            f_base = st.selectbox("Основа", ["Водная", "Углеводородная", "Синтетическая"])

            c_f1, c_f2, c_f3 = st.columns(3)
            d_min = c_f1.number_input("Плотность от (г/см3)", value=1.00, step=0.01)
            d_max = c_f2.number_input("Плотность до (г/см3)", value=1.20, step=0.01)
            t_max = c_f3.number_input("Макс. Температура (°C)", value=100, step=10)

            c_f4, c_f5, c_f6, c_f7 = st.columns(4)
            inh = c_f4.number_input("Ингибирование (1-100)", value=50)
            fric = c_f5.number_input("Коэфф. трения", value=0.20, step=0.01)
            eco = c_f6.number_input("Экологичность (1-10)", value=5)
            cost = c_f7.number_input("Стоимость (руб/м3)", value=5000)

            if st.form_submit_button("Сохранить раствор в БД"):
                query = """INSERT INTO fluids (name, base_type, density_min, density_max, temp_max, filtration, inhibition, friction, eco_score, cost) 
                           VALUES (%s, %s, %s, %s, %s, 10.0, %s, %s, %s, %s)"""
                if execute_query(query, (f_name, f_base, d_min, d_max, t_max, inh, fric, eco, cost)):
                    st.success("✅ Раствор успешно добавлен!")


def main():
    if not st.session_state['logged_in']:
        show_login_page()
    else:
        if st.session_state['user_role'] == 'admin':
            show_admin_panel()
        else:
            show_engineer_panel()


if __name__ == "__main__":
    main()