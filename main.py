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

# --- БОКОВАЯ ПАНЕЛЬ (ВЕСА КРИТЕРИЕВ) ---
st.sidebar.header("⚙️ Настройки алгоритма (Веса)")
weight_cost = st.sidebar.slider("💰 Важность стоимости", min_value=1, max_value=10, value=5)
weight_density = st.sidebar.slider("🧪 Важность плотности", min_value=1, max_value=10, value=5)
weight_viscosity = st.sidebar.slider("💧 Важность вязкости", min_value=1, max_value=10, value=5)

# Собираем веса в один массив (порядок важен!)
weights = np.array([weight_cost, weight_density, weight_viscosity])

# Указываем, что мы хотим делать с каждым параметром:
# Стоимость - минимизировать (False), Плотность - максимизировать (True), Вязкость - максимизировать (True)
# В реальной ВКР логику можно будет поменять под конкретные геологические условия
criteria_types = np.array([False, True, True])


# --- ФУНКЦИЯ ЗАГРУЗКИ ---
def load_data():
    try:
        conn = psycopg2.connect(
            database=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT
        )
        query = """
        SELECT 
            name AS "Название раствора", 
            base_type AS "Основа", 
            cost AS "Стоимость (руб)",
            density AS "Плотность (г/см3)",
            viscosity AS "Вязкость (с)"
        FROM fluids;
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Связь с базой данных потеряна: {e}")
        return pd.DataFrame()


# --- АЛГОРИТМ TOPSIS ---
def calculate_topsis(df, weights, criteria_types):
    # 1. Берем только числовые колонки
    matrix = df[["Стоимость (руб)", "Плотность (г/см3)", "Вязкость (с)"]].copy().values

    # 2. Нормализация (чтобы рубли и плотность можно было сравнивать)
    norm_matrix = matrix / np.sqrt((matrix ** 2).sum(axis=0))

    # 3. Умножаем на веса, которые задал инженер
    weighted_matrix = norm_matrix * weights

    # 4. Находим идеальные (лучшие и худшие) значения для каждого столбца
    ideal_best = np.where(criteria_types, weighted_matrix.max(axis=0), weighted_matrix.min(axis=0))
    ideal_worst = np.where(criteria_types, weighted_matrix.min(axis=0), weighted_matrix.max(axis=0))

    # 5. Считаем расстояния от каждого раствора до идеала и до анти-идеала
    dist_best = np.sqrt(((weighted_matrix - ideal_best) ** 2).sum(axis=1))
    dist_worst = np.sqrt(((weighted_matrix - ideal_worst) ** 2).sum(axis=1))

    # 6. Считаем финальный рейтинг (от 0 до 1)
    score = dist_worst / (dist_best + dist_worst)
    return score


# --- ОСНОВНОЙ ЭКРАН ---
st.title("🛢️ Интеллектуальная система подбора буровых растворов")

df_fluids = load_data()

if not df_fluids.empty:
    st.subheader("Исходные данные из БД:")
    st.dataframe(df_fluids, use_container_width=True)

    st.markdown("---")
    st.subheader("🏆 Результаты расчета (Метод TOPSIS)")

    # Запускаем нашу математику
    scores = calculate_topsis(df_fluids, weights, criteria_types)

    # Добавляем результаты в таблицу
    df_results = df_fluids.copy()
    df_results["Рейтинг TOPSIS"] = scores

    # Сортируем от лучшего к худшему
    df_results = df_results.sort_values(by="Рейтинг TOPSIS", ascending=False).reset_index(drop=True)

    # Округляем рейтинг для красоты и делаем его в процентах
    df_results["Совпадение (%)"] = (df_results["Рейтинг TOPSIS"] * 100).round(2)

    # Выводим лидера крупно
    best_fluid = df_results.iloc[0]
    st.success(
        f"**Оптимальный выбор:** {best_fluid['Название раствора']} (Совпадение: {best_fluid['Совпадение (%)']}%)")

    # Выводим красивую итоговую таблицу без сырого рейтинга
    st.dataframe(df_results.drop(columns=["Рейтинг TOPSIS"]), use_container_width=True)

else:
    st.warning("База данных пуста или недоступна.")