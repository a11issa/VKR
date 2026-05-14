import streamlit as st
import psycopg2
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv

# --- НАСТРОЙКИ ПОДКЛЮЧЕНИЯ ---
load_dotenv()
DB_USER = "postgres"
DB_PASSWORD = os.getenv("DB_PASS")
DB_HOST = "127.0.0.1"
DB_PORT = "5432"
DB_NAME = "drilling_fluids"

st.set_page_config(page_title="Подбор буровых растворов", page_icon="🛢️", layout="wide")

# --- МАТЕМАТИЧЕСКИЕ ПРЕСЕТЫ (СКРЫТЫЙ МАИ) ---
# Здесь мы заранее посчитали веса через МАИ для разных ситуаций
AHP_SCENARIOS = {
    "Стандартные условия": np.array([0.4, 0.3, 0.3]),  # Акцент на баланс
    "АВПД (Высокое давление)": np.array([0.1, 0.7, 0.2]),  # Главное — плотность
    "Поглощения и неустойчивость": np.array([0.2, 0.2, 0.6]),  # Главное — вязкость/корка
    "Экономия бюджета": np.array([0.7, 0.15, 0.15])  # Главное — цена
}


# --- ФУНКЦИИ РАБОТЫ С ДАННЫМИ ---
def get_db_connection():
    return psycopg2.connect(database=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)


def load_data_with_filter(target_density, target_temp, lithology):
    """Загрузка данных с жесткой фильтрацией прямо из таблицы fluids"""
    try:
        conn = get_db_connection()
        # Убрали JOIN, теперь всё берется только из таблицы fluids
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
        st.error(f"Ошибка БД: {e}")
        return pd.DataFrame()


# --- АЛГОРИТМ TOPSIS ---
def calculate_topsis(df, weights):
    # Колонки для расчета: Стоимость (min), Плотность (max), Вязкость (max)
    # Плотность берем как среднюю из диапазона для оценки
    df_calc = df.copy()
    df_calc['avg_density'] = (df['density_min'] + df['density_max']) / 2

    matrix = df_calc[["Стоимость", "avg_density", "Вязкость"]].values

    # Нормализация
    norm_matrix = matrix / np.sqrt((matrix ** 2).sum(axis=0))
    weighted_matrix = norm_matrix * weights

    # Идеалы (Стоимость - min, остальные - max)
    ideal_best = [weighted_matrix[:, 0].min(), weighted_matrix[:, 1].max(), weighted_matrix[:, 2].max()]
    ideal_worst = [weighted_matrix[:, 0].max(), weighted_matrix[:, 1].min(), weighted_matrix[:, 2].min()]

    dist_best = np.sqrt(((weighted_matrix - ideal_best) ** 2).sum(axis=1))
    dist_worst = np.sqrt(((weighted_matrix - ideal_worst) ** 2).sum(axis=1))

    return dist_worst / (dist_best + dist_worst)


# --- ИНТЕРФЕЙС ИНЖЕНЕРА ---
st.title("🛢️ Система проектирования буровых растворов")

# Создаем две колонки для ввода данных
col_input, col_results = st.columns([1, 2])

with col_input:
    st.subheader("📋 Данные интервала")
    well_name = st.text_input("Название скважины", value="Скважина №1")

    c1, c2 = st.columns(2)
    with c1:
        int_from = st.number_input("Интервал от, м", value=0)
    with c2:
        int_to = st.number_input("Интервал до, м", value=500)

    target_density = st.number_input("Требуемая плотность, г/см³", value=1.20, step=0.01)
    target_temp = st.number_input("Забойная температура, °C", value=60)

    lithology = st.multiselect(
        "Литология в интервале",
        ["Глины", "Песчаники", "Известняки", "Соли", "Аргиллиты"],
        default=["Глины"]
    )

    st.markdown("---")
    st.subheader("⚖️ Стратегия подбора")
    scenario = st.selectbox("Выберите сценарий осложнений:", list(AHP_SCENARIOS.keys()))

    run_calc = st.button("📊 Рассчитать оптимальный вариант", type="primary", use_container_width=True)

with col_results:
    if run_calc:
        st.subheader(f"🔍 Результаты для {well_name} ({int_from}-{int_to} м)")

        # 1. Загрузка и жесткая фильтрация
        df = load_data_with_filter(target_density, target_temp, lithology)

        if not df.empty:
            # 2. Получение весов из сценария (МАИ уже внутри)
            weights = AHP_SCENARIOS[scenario]

            # 3. Ранжирование TOPSIS
            df["Рейтинг"] = calculate_topsis(df, weights)
            df = df.sort_values("Рейтинг", ascending=False)

            # Вывод лидера
            winner = df.iloc[0]
            st.success(f"**Рекомендуется:** {winner['Название']} ({winner['Основа']})")

            # Таблица результатов
            display_df = df[["Название", "Основа", "Стоимость", "Вязкость", "Рейтинг"]].copy()
            display_df["Рейтинг"] = (display_df["Рейтинг"] * 100).round(1).astype(str) + " %"
            st.dataframe(display_df, use_container_width=True)

            # Краткое пояснение
            st.info(
                f"Выбран сценарий '{scenario}'. Веса критериев: Цена={weights[0]}, Плотность={weights[1]}, Вязкость={weights[2]}")
        else:
            st.error("❌ В базе нет растворов, подходящих под данные условия (плотность/температура).")