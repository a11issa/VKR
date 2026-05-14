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
DB_PASSWORD = os.getenv("DB_PASS")
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
        st.session_state['user_id'], st.session_state['well_name'], interval_data['Имя_интервала'],
        interval_data['H'], interval_data['P_pl'], interval_data['T_zab'], interval_data['Angle'],
        interval_data['Fluid_type'], interval_data['Rho_min'], interval_data['Rho_max'],
        interval_data['Viscosity'], interval_data['Preset'],
        int(interval_data['Fluid_id'])  # ИСПРАВЛЕНИЕ 2: Принудительный перевод в Python int
    )
    execute_query(query, params)


def get_history():
    conn = get_db_connection()
    query = """
    SELECT ch.calc_date AS "Дата", u.username AS "Инженер", ch.well_name AS "Скважина", 
           ch.interval_name AS "Интервал", ch.depth AS "Глубина", p.name AS "Условия", f.name AS "Раствор"
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

    rating = dist_worst / (dist_best + dist_worst)
    # ИСПРАВЛЕНИЕ 4: Убираем вероятность появления NaN
    return np.nan_to_num(rating, nan=0.0)


# ==========================================
# ЭКСПОРТ В PDF
# ==========================================
def create_summary_pdf(well_name, intervals):
    pdf = FPDF(orientation='L')
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

    pdf.set_font(pdf.font_family, size=9)
    # ИСПРАВЛЕНИЕ 3: Перераспределили ширину. Раствору отдано 130мм (почти половина листа)
    col_widths = [25, 15, 15, 15, 30, 150, 25]
    headers = ["Интервал", "Глубина", "Pпл", "Tзаб", "Плотность", "Рекомендуемый раствор", "Рейтинг МАИ"]

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, txt=header, border=1, align='C')
    pdf.ln()

    for it in intervals:
        pdf.cell(col_widths[0], 10, txt=str(it['Имя_интервала']), border=1, align='C')
        pdf.cell(col_widths[1], 10, txt=str(it['H']), border=1, align='C')
        pdf.cell(col_widths[2], 10, txt=str(it['P_pl']), border=1, align='C')
        pdf.cell(col_widths[3], 10, txt=str(it['T_zab']), border=1, align='C')
        pdf.cell(col_widths[4], 10, txt=f"{it['Rho_min']} - {it['Rho_max']}", border=1, align='C')
        # Для очень длинных названий можно использовать обрезку строки, если они все еще не влезают
        pdf.cell(col_widths[5], 10, txt=str(it['Раствор'])[:85], border=1, align='L')
        pdf.cell(col_widths[6], 10, txt=str(it['Рейтинг']), border=1, align='C')
        pdf.ln()

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
    col_input, col_results = st.columns([1, 2])

    with col_input:
        st.subheader("➕ Добавить интервал")
        with st.form("add_interval_form", clear_on_submit=False):
            int_name = st.text_input("Название", value="Интервал 1")
            H = st.number_input("Глубина подошвы (H), м", min_value=10.0, value=1000.0, step=50.0)
            P_pl = st.number_input("Пластовое давление (Pпл), МПа", min_value=1.0, value=12.0, step=0.5)
            T_zab = st.number_input("Макс. температура (Tзаб), °C", min_value=10.0, value=40.0, step=5.0)

            c_a1, c_a2 = st.columns(2)
            angle = c_a1.number_input("Зенитный угол (α)", value=0.0)
            fluid_type = c_a2.selectbox("Флюид", ["Нефть", "Газ"])

            presets_df = get_presets()
            selected_preset_name = st.selectbox("Осложнения (МАИ)",
                                                presets_df['name'].tolist() if not presets_df.empty else [])
            submit_btn = st.form_submit_button("Рассчитать", type="primary", use_container_width=True)

        # Выполняем расчет ВНЕ формы, чтобы можно было интерактивно вывести Топ-3
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

                    # ИСПРАВЛЕНИЕ 5: Показываем инженеру ТОП-3 вариантов
                    st.success(f"Расчет успешен! Требуемая плотность: {rho_min} - {rho_max} г/см3")
                    st.write("🏆 **Топ-3 подходящих раствора:**")

                    # Форматируем рейтинг для вывода
                    df_display_top = df.head(3).copy()
                    df_display_top["Рейтинг"] = (df_display_top["Рейтинг"] * 100).round(1).astype(str) + "%"
                    st.dataframe(df_display_top[["Название", "Основа", "Рейтинг"]], use_container_width=True)

                    winner = df.iloc[0]
                    interval_data = {
                        "Имя_интервала": int_name, "H": H, "P_pl": P_pl, "T_zab": T_zab,
                        "Angle": angle, "Fluid_type": fluid_type, "Preset": selected_preset_name,
                        "Rho_min": rho_min, "Rho_max": rho_max, "Viscosity": req_viscosity,
                        "Fluid_id": int(winner['id']), "Раствор": winner['Название'],
                        "Рейтинг": f"{(winner['Рейтинг'] * 100):.1f}%", "Цена": winner['Стоимость']
                    }
                    st.session_state['project_intervals'].append(interval_data)
                    st.rerun()  # Обновляем страницу, чтобы таблица справа перерисовалась

    with col_results:
        st.subheader("📑 Сводная таблица по скважине")

        if len(st.session_state['project_intervals']) > 0:
            df_display = pd.DataFrame(st.session_state['project_intervals'])
            # Использование конфигурации колонок Streamlit, чтобы длинные названия не обрезались
            st.dataframe(df_display[["Имя_интервала", "H", "Rho_min", "Rho_max", "Раствор", "Рейтинг"]],
                         use_container_width=True)

            # ИСПРАВЛЕНИЕ 1: Блок удаления конкретного интервала
            st.markdown("---")
            col_del1, col_del2 = st.columns([2, 1])
            with col_del1:
                interval_options = {i: f"{it['Имя_интервала']} ({it['H']}м)" for i, it in
                                    enumerate(st.session_state['project_intervals'])}
                interval_to_delete = st.selectbox("Выберите интервал для удаления:",
                                                  options=list(interval_options.keys()),
                                                  format_func=lambda x: interval_options[x])
            with col_del2:
                st.write("")
                st.write("")
                if st.button("❌ Удалить выбранный", use_container_width=True):
                    st.session_state['project_intervals'].pop(interval_to_delete)
                    st.rerun()
            st.markdown("---")

            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button("🗑️ Очистить всю скважину", use_container_width=True):
                    st.session_state['project_intervals'] = []
                    st.rerun()

            with c_btn2:
                pdf_bytes = create_summary_pdf(st.session_state['well_name'], st.session_state['project_intervals'])
                if st.download_button(label="💾 Сохранить в БД и Скачать PDF",
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
        st.warning("Раздел добавления растворов временно скрыт. Сосредоточьтесь на функционале инженера.")


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