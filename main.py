import streamlit as st
import psycopg2
import pandas as pd
import numpy as np
import os
import urllib.request
from dotenv import load_dotenv
from fpdf import FPDF

# --- НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД ---
load_dotenv()
DB_USER = "postgres"
DB_PASSWORD = os.getenv("DB_PASS")
DB_HOST = "127.0.0.1"
DB_PORT = "5432"
DB_NAME = "drilling_fluids"

# Настройка страницы приложения
st.set_page_config(page_title="Подбор буровых растворов", page_icon="🛢️", layout="wide")

# --- СЦЕНАРИИ И ВЕСА (МАИ) ---
# Веса критериев (Стоимость, Плотность, Вязкость), заранее рассчитанные методом МАИ
AHP_SCENARIOS = {
    "Стандартные условия (Баланс)": np.array([0.4, 0.3, 0.3]),
    "АВПД (Высокое давление)": np.array([0.1, 0.7, 0.2]),
    "Поглощения и неустойчивость": np.array([0.2, 0.2, 0.6]),
    "Экономия бюджета": np.array([0.7, 0.15, 0.15])
}


# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
def get_db_connection():
    """Создает и возвращает подключение к PostgreSQL"""
    return psycopg2.connect(
        database=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT
    )


def execute_query(query, params=None):
    """Выполняет запросы на изменение данных (INSERT/UPDATE)"""
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


def load_data_with_filter(target_density, target_temp):
    """Выгружает растворы, которые физически подходят под условия скважины"""
    try:
        conn = get_db_connection()
        query = f"""
        SELECT 
            name AS "Название", 
            base_type AS "Основа", 
            cost AS "Стоимость",
            density_min, 
            density_max,
            temp_max AS "Термо",
            viscosity AS "Вязкость"
        FROM fluids
        WHERE {target_density} BETWEEN density_min AND density_max
          AND temp_max >= {target_temp}
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Ошибка при загрузке данных: {e}")
        return pd.DataFrame()


# --- МАТЕМАТИЧЕСКИЙ АЛГОРИТМ (TOPSIS) ---
def calculate_topsis(df, weights):
    """Считает рейтинг растворов методом TOPSIS"""
    df_calc = df.copy()
    # Для математики берем среднюю плотность из диапазона
    df_calc['avg_density'] = (df['density_min'] + df['density_max']) / 2
    matrix = df_calc[["Стоимость", "avg_density", "Вязкость"]].values

    # 1. Нормализация данных
    col_sums = np.sqrt((matrix ** 2).sum(axis=0))
    col_sums[col_sums == 0] = 1e-10  # Защита от деления на ноль
    norm_matrix = matrix / col_sums

    # 2. Применение весов из МАИ
    weighted_matrix = norm_matrix * weights

    # 3. Поиск Идеального и Анти-идеального решений
    # Стоимость минимизируем (индекс 0), Плотность и Вязкость максимизируем (индексы 1, 2)
    ideal_best = [weighted_matrix[:, 0].min(), weighted_matrix[:, 1].max(), weighted_matrix[:, 2].max()]
    ideal_worst = [weighted_matrix[:, 0].max(), weighted_matrix[:, 1].min(), weighted_matrix[:, 2].min()]

    # 4. Расчет Евклидовых расстояний
    dist_best = np.sqrt(((weighted_matrix - ideal_best) ** 2).sum(axis=1))
    dist_worst = np.sqrt(((weighted_matrix - ideal_worst) ** 2).sum(axis=1))

    # 5. Итоговый рейтинг (от 0 до 1)
    score = dist_worst / (dist_best + dist_worst)
    return score


# --- ФУНКЦИЯ ЭКСПОРТА В PDF ---
def create_pdf(well_name, interval, scenario, df_results):
    """Генерирует PDF-отчет с результатами подбора"""
    pdf = FPDF()
    pdf.add_page()

    font_path = "Roboto-Regular.ttf"

    # Проверяем, положила ли ты файл в папку
    if not os.path.exists(font_path):
        st.error(f"❌ Файл шрифта '{font_path}' не найден! Пожалуйста, закинь его в папку с проектом.")
        return bytes()

        # Подключаем наш надежный локальный шрифт
    pdf.add_font("Roboto", "", font_path)

    pdf.set_font("Roboto", size=16)
    pdf.cell(0, 10, txt="Отчет: Подбор бурового раствора", new_x="LMARGIN", new_y="NEXT", align='C')

    pdf.set_font("Roboto", size=12)
    pdf.cell(0, 10, txt=f"Скважина: {well_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, txt=f"Интервал бурения: {interval}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, txt=f"Сценарий осложнений: {scenario}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.cell(0, 10, txt="Топ-3 оптимальных рецептуры:", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Roboto", size=10)
    for i, row in df_results.head(3).iterrows():
        text = f"{i + 1}. {row['Название']} | Основа: {row['Основа']} | Цена: {row['Стоимость']} руб. | Рейтинг: {row['Рейтинг'] * 100:.1f}%"
        pdf.cell(0, 10, txt=text, new_x="LMARGIN", new_y="NEXT")

    return pdf.output(dest='S')


# --- ПАНЕЛЬ АДМИНИСТРАТОРА ---
def show_admin_panel():
    st.title("🛠️ Панель администратора")
    st.write("Наполнение базы данных и управление справочниками.")

    tab1, tab2, tab3 = st.tabs(["🧪 Добавить реагент", "🛢️ Добавить раствор", "🔗 Состав растворов (В разработке)"])

    with tab1:
        st.subheader("Внесение реагента в справочник")
        with st.form("add_reagent_form", clear_on_submit=True):
            r_name = st.text_input("Название (например: Барит, ПАЦ-В)")
            r_type = st.selectbox("Назначение",
                                  ["Утяжелитель", "Понизитель фильтрации", "Смазочная добавка", "Ингибитор",
                                   "Структурообразователь"])
            if st.form_submit_button("Сохранить реагент"):
                if r_name:
                    query = "INSERT INTO reagents (name, type) VALUES (%s, %s);"
                    if execute_query(query, (r_name, r_type)):
                        st.success(f"✅ Реагент '{r_name}' добавлен в таблицу reagents.")
                else:
                    st.warning("Введите название реагента.")

    with tab2:
        st.subheader("Внесение базового раствора в справочник")
        with st.form("add_fluid_form", clear_on_submit=True):
            f_name = st.text_input("Название состава")
            f_base = st.selectbox("Тип основы", ["Водная (ВБР)", "Углеводородная (РУО)", "Синтетическая"])
            c1, c2 = st.columns(2)
            with c1:
                d_min = st.number_input("Плотность от (г/см3)", value=1.00, step=0.01)
                t_max = st.number_input("Термостабильность (°C)", value=100)
            with c2:
                d_max = st.number_input("Плотность до (г/см3)", value=1.20, step=0.01)
                visc = st.number_input("Вязкость условная (с)", value=40)
            cost = st.number_input("Стоимость (руб/м3)", value=5000)

            if st.form_submit_button("Сохранить раствор"):
                if f_name:
                    query = """
                    INSERT INTO fluids (name, base_type, density_min, density_max, temp_max, viscosity, cost) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """
                    if execute_query(query, (f_name, f_base, d_min, d_max, t_max, visc, cost)):
                        st.success(f"✅ Раствор '{f_name}' добавлен в таблицу fluids.")
                else:
                    st.warning("Введите название раствора.")

    with tab3:
        st.info(
            "Здесь будет функционал связывания таблицы fluids и reagents через таблицу fluid_reagents с автоматическим подтягиванием названий.")


# --- РАБОЧЕЕ МЕСТО ИНЖЕНЕРА ---
def show_engineer_panel():
    st.title("🛢️ Интеллектуальный подбор бурового раствора")
    col_input, col_results = st.columns([1, 2])

    with col_input:
        st.subheader("📋 Исходные данные")
        well_name = st.text_input("Шифр скважины", value="Скважина №1")

        c1, c2 = st.columns(2)
        with c1:
            int_from = st.number_input("Интервал от (м)", value=0)
        with c2:
            int_to = st.number_input("Интервал до (м)", value=1200)

        target_density = st.number_input("Требуемая плотность (г/см³)", value=1.15, step=0.01)
        target_temp = st.number_input("Ожидаемая забойная температура (°C)", value=80)
        lithology = st.multiselect("Преобладающая литология", ["Глины", "Песчаники", "Соли", "Известняки", "Аргиллиты"],
                                   default=["Глины"])

        st.markdown("---")
        st.subheader("⚖️ Настройки алгоритма")
        scenario = st.selectbox("Ожидаемые осложнения (Пресет МАИ):", list(AHP_SCENARIOS.keys()))

        run_calc = st.button("📊 Найти оптимальный раствор", type="primary", use_container_width=True)

    with col_results:
        if run_calc:
            st.subheader(f"🔍 Результат анализа для {well_name} ({int_from}-{int_to} м)")

            # 1. Фильтрация
            df = load_data_with_filter(target_density, target_temp)

            if not df.empty:
                # 2. Ранжирование
                weights = AHP_SCENARIOS[scenario]
                df["Рейтинг"] = calculate_topsis(df, weights)
                df = df.sort_values("Рейтинг", ascending=False)

                # 3. Вывод победителя
                winner = df.iloc[0]
                st.success(f"**Наилучший выбор:** {winner['Название']} (Совпадение: {(winner['Рейтинг'] * 100):.1f}%)")

                # 4. Форматирование таблицы для экрана
                display_df = df[["Название", "Основа", "Стоимость", "Вязкость", "Рейтинг"]].copy()
                display_df["Рейтинг"] = (display_df["Рейтинг"] * 100).round(1).astype(str) + " %"
                st.dataframe(display_df, use_container_width=True)

                st.info(
                    f"Весовые коэффициенты МАИ: Стоимость={weights[0]}, Плотность={weights[1]}, Вязкость={weights[2]}")

                # 5. Экспорт в PDF
                st.markdown("---")
                pdf_bytes = create_pdf(well_name, f"{int_from}-{int_to} м", scenario, df)

                st.download_button(
                    label="📄 Скачать отчет (PDF)",
                    data=bytes(pdf_bytes),
                    file_name=f"Отчет_{well_name}.pdf",
                    mime="application/pdf",
                    type="primary"
                )
            else:
                st.error("❌ Ни один раствор из базы не выдерживает заданные параметры плотности и температуры.")


# --- ГЛАВНАЯ ТОЧКА ВХОДА ---
def main():
    # Временная панель авторизации (заменим на полноценную позже)
    st.sidebar.title("🔐 Авторизация")
    role = st.sidebar.radio("Валидация пользователя:", ["Инженер-технолог", "Администратор БД"])
    st.sidebar.markdown("---")

    if role == "Администратор БД":
        show_admin_panel()
    else:
        show_engineer_panel()


if __name__ == "__main__":
    main()