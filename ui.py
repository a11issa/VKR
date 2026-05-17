import streamlit as st
import pandas as pd
import numpy as np

# Импортируем из наших модулей
from db import (authenticate_user, get_history, get_all_users, add_user_to_db,
                add_fluid_to_db, get_all_reagents, add_reagent_to_db,
                add_recipe_item, get_fluid_recipe, get_user_projects,
                create_project, delete_project_from_db, get_presets,
                get_fluids_filtered, save_interval_to_db, delete_interval_from_db, get_db_connection)
from calculations import calculate_physics, calculate_topsis
from services import load_intervals_from_db
from reports import create_summary_pdf


def show_login_page():
    st.title("Авторизация")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Имя пользователя")
            password = st.text_input("Пароль", type="password")
            if st.form_submit_button("Войти", use_container_width=True):
                user = authenticate_user(username, password)
                if user:
                    st.session_state.update({'logged_in': True, 'user_id': user[0], 'user_role': user[1]});
                    st.rerun()
                else:
                    st.error("Неверный логин или пароль")


def show_admin_panel():
    c1, c2 = st.columns([4, 1])
    c1.title("Панель главного технолога")
    if c2.button("Выйти из системы", use_container_width=True): st.session_state.clear(); st.rerun()

    tab_history, tab_users, tab_fluids, tab_reagents, tab_recipes = st.tabs(
        ["Журнал", "Пользователи", "Растворы", "Склад реагентов", "Рецептуры"])

    with tab_history:
        st.subheader("Журнал расчетов инженеров")
        if st.button("Обновить журнал"): pass
        history_df = get_history()
        if not history_df.empty:
            st.dataframe(history_df, use_container_width=True, hide_index=True)
        else:
            st.info("История пуста.")

    with tab_users:
        col_list, col_add = st.columns([1.5, 1])
        with col_list:
            st.subheader("Текущие пользователи")
            st.dataframe(get_all_users(), use_container_width=True, hide_index=True)
        with col_add:
            st.subheader("Добавить пользователя")
            with st.form("add_user_form", clear_on_submit=True):
                new_user = st.text_input("Логин")
                new_pass = st.text_input("Пароль", type="password")
                new_role = st.selectbox("Роль", ["engineer", "admin"])
                if st.form_submit_button("Создать", type="primary", use_container_width=True):
                    if add_user_to_db(new_user, new_pass, new_role):
                        st.success("Пользователь добавлен!");
                        st.rerun()
                    else:
                        st.error("Ошибка!")

    with tab_fluids:
        col_fl_add, col_fl_list = st.columns([1, 1.5])
        with col_fl_add:
            st.subheader("Новый раствор")
            with st.form("add_fluid_form", clear_on_submit=True):
                f_name = st.text_input("Название (напр: Биополимерный)")
                f_base = st.selectbox("Основа", ["Водная", "Углеводородная"])
                c1, c2 = st.columns(2)
                f_d_min = c1.number_input("Мин. плотность", min_value=1.0, value=1.05)
                f_d_max = c2.number_input("Макс. плотность", min_value=1.1, value=1.40)
                f_t_max = c1.number_input("T_max, °C", min_value=50, value=120)
                f_cost = c2.number_input("Цена за 1 м³", min_value=1000, value=5000)
                f_inh = st.slider("Ингибирование (0-100)", 0, 100, 70)
                f_fric = st.slider("Скольжение (0-100)", 0, 100, 50)
                f_eco = st.slider("Экологичность (0-10)", 0, 10, 8)
                if st.form_submit_button("Сохранить раствор", type="primary"):
                    if add_fluid_to_db(f_name, f_base, f_d_min, f_d_max, f_t_max, f_inh, f_fric, f_eco,
                                       f_cost): st.success("Раствор добавлен!"); st.rerun()
        with col_fl_list:
            st.subheader("Справочник растворов")
            conn = get_db_connection()
            st.dataframe(
                pd.read_sql("SELECT id, name, base_type, density_min, density_max FROM fluids ORDER BY id;", conn),
                use_container_width=True, hide_index=True)
            conn.close()

    with tab_reagents:
        col_rg_add, col_rg_list = st.columns([1, 1.5])
        with col_rg_add:
            st.subheader("Добавить реагент")
            with st.form("add_reagent_form", clear_on_submit=True):
                r_name = st.text_input("Название (напр: Ксантановая камедь)")
                r_func = st.selectbox("Назначение",
                                      ["Структурообразователь", "Понизитель фильтрации", "Ингибитор", "Смазка",
                                       "Регулятор pH", "Кольматант", "Бактерицид"])
                r_litho = st.selectbox("Литология:", ["Общий", "Глины", "Трещины"])
                r_temp = st.number_input("T_max, °C", min_value=50, value=130, step=10)
                if st.form_submit_button("Добавить", type="primary"):
                    if r_name and add_reagent_to_db(r_name, r_func, r_litho, r_temp): st.success(
                        "Реагент добавлен!"); st.rerun()
        with col_rg_list:
            st.subheader("Склад хим. реагентов")
            st.dataframe(get_all_reagents(), use_container_width=True, hide_index=True)

    with tab_recipes:
        st.subheader("Матрица рецептур")
        conn = get_db_connection()
        fluids_df = pd.read_sql("SELECT id, name FROM fluids ORDER BY id;", conn)
        conn.close()
        reagents_df = get_all_reagents()
        if not fluids_df.empty and not reagents_df.empty:
            col_b1, col_b2 = st.columns([1, 1.5])
            with col_b1:
                with st.form("add_recipe_form"):
                    sel_fluid = st.selectbox("1. Раствор", fluids_df['name'].tolist())
                    sel_reagent = st.selectbox("2. Реагент", reagents_df['name'].tolist())
                    conc = st.number_input("3. Концентрация (кг/м³)", min_value=0.1, value=2.0, step=0.5)
                    if st.form_submit_button("Добавить в рецепт", type="primary", use_container_width=True):
                        if add_recipe_item(fluids_df[fluids_df['name'] == sel_fluid].iloc[0]['id'],
                                           reagents_df[reagents_df['name'] == sel_reagent].iloc[0]['id'],
                                           conc): st.success(f"Добавлено!"); st.rerun()
            with col_b2:
                view_fluid = st.selectbox("Просмотр рецептуры для:", fluids_df['name'].tolist())
                recipe_df = get_fluid_recipe(fluids_df[fluids_df['name'] == view_fluid].iloc[0]['id'])
                if not recipe_df.empty:
                    st.dataframe(recipe_df, use_container_width=True, hide_index=True)
                else:
                    st.warning("Рецептура не задана.")


def show_engineer_panel():
    projects_df = get_user_projects(st.session_state['user_id'])
    project_list = projects_df['name'].tolist() if not projects_df.empty else []

    with st.sidebar:
        st.header("Ваши проекты")
        with st.form("create_project_form", clear_on_submit=True):
            new_proj_name = st.text_input("Новый проект")
            if st.form_submit_button("Создать", use_container_width=True) and new_proj_name.strip():
                st.session_state['current_project_id'] = create_project(st.session_state['user_id'],
                                                                        new_proj_name.strip())
                st.rerun()
        st.divider()
        if project_list:
            # Исправление ошибки с int64 при выборе проекта
            if st.session_state['current_project_id'] is None or st.session_state['current_project_id'] not in \
                    projects_df['id'].values:
                default_index = 0
            else:
                raw_index = projects_df[projects_df['id'] == st.session_state['current_project_id']].index[0]
                default_index = int(raw_index)

            selected_proj_name = st.selectbox("Активный проект:", options=project_list, index=default_index)
            active_proj_id = int(projects_df[projects_df['name'] == selected_proj_name].iloc[0]['id'])
            st.session_state['current_project_id'] = active_proj_id

            if st.button("Удалить проект", type="secondary", use_container_width=True):
                delete_project_from_db(active_proj_id)
                st.session_state['current_project_id'] = None
                st.rerun()
        st.divider()
        if st.button("Выйти", use_container_width=True): st.session_state.clear(); st.rerun()

    if st.session_state['current_project_id'] is None:
        st.title("Выберите проект слева")
        return

    current_intervals = load_intervals_from_db(st.session_state['current_project_id'])
    st.session_state['well_name'] = projects_df[projects_df['id'] == st.session_state['current_project_id']].iloc[0][
        'name']

    st.title(f"{st.session_state['well_name']}")

    with st.expander("ДОБАВИТЬ НОВЫЙ ИНТЕРВАЛ", expanded=True):
        with st.form("add_interval_form", clear_on_submit=False):
            int_name = st.text_input("Название (напр. Кондуктор)", value="Интервал 1")

            # Более свободный интерфейс в 2 колонки
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Параметры ствола**")
                H = st.number_input("Глубина (H), м", min_value=10.0, value=1000.0, step=50.0)
                D_mm = st.number_input("Долото, мм", min_value=50.0, value=215.9, step=1.0)
                angle = st.number_input("Зенитный угол, °", value=0.0)

            with col2:
                st.markdown("**Пластовые условия**")
                P_pl = st.number_input("Пластовое давление (P пл), МПа", min_value=1.0, value=12.0, step=0.5)
                P_gr = st.number_input("Давление разрыва (P гр), МПа", min_value=P_pl + 1.0, value=P_pl + 6.0, step=0.5)
                T_zab = st.number_input("Температура забоя, °C", min_value=10.0, value=40.0, step=5.0)

            presets_df = get_presets()
            if not presets_df.empty:
                selected_lithology = st.selectbox("Литология / Условия бурения", presets_df['lithology'].tolist())
                selected_preset_name = presets_df[presets_df['lithology'] == selected_lithology].iloc[0]['name']
            else:
                selected_preset_name = None

            if st.form_submit_button("Рассчитать и добавить", type="primary",
                                     use_container_width=True) and not presets_df.empty:
                calc_result = calculate_physics(H, P_pl, P_gr, T_zab, angle)
                if calc_result[4] is not None:
                    st.error(calc_result[4])
                else:
                    rho_min, rho_max, req_viscosity, req_dns, _ = calc_result
                    df = get_fluids_filtered(rho_min, rho_max, T_zab)
                    if df.empty:
                        st.error("База пуста для этих условий.")
                    else:
                        preset_row = presets_df[presets_df['name'] == selected_preset_name].iloc[0]
                        df["Рейтинг"] = calculate_topsis(df, np.array(
                            [preset_row['weight_inhibition'], preset_row['weight_friction'], preset_row['weight_eco'],
                             preset_row['weight_cost']]))
                        df = df.sort_values("Рейтинг", ascending=False).reset_index(drop=True)
                        save_interval_to_db(
                            {"Имя_интервала": int_name, "H": H, "D_mm": D_mm, "P_pl": P_pl, "T_zab": T_zab,
                             "Angle": angle, "Fluid_type": "Нефть/Газ", "Preset": selected_preset_name,
                             "Rho_min": rho_min, "Rho_max": rho_max, "Viscosity": req_viscosity,
                             "Fluid_id": int(df.iloc[0]['id'])}, st.session_state['current_project_id'])
                        st.rerun()

    st.markdown("### Паспорт скважины (Интервалы)")

    if len(current_intervals) > 0:
        for it in current_intervals:
            with st.container():
                st.markdown(f"#### {it.get('Имя_интервала', '')}")
                c_main, c_cost, c_del = st.columns([5, 3, 1])
                with c_main:
                    st.success(f"Оптимальный раствор: **{it.get('Раствор')}**")
                with c_cost:
                    st.info(f"Итого смета: **{it.get('Cost_Total', 0):,.0f} руб.**".replace(',', ' '))
                with c_del:
                    if st.button("Удалить", key=f"del_btn_{it['id']}"):
                        delete_interval_from_db(it['id'])
                        st.rerun()

                st.markdown("**Рецептура (на 1 м³):**")
                st.dataframe(pd.DataFrame(it.get('RecipeTotal', [])), use_container_width=True, hide_index=True)

                if st.button("Показать альтернативы", key=f"alt_btn_{it['id']}"):
                    if it.get('Top_3'):
                        st.markdown("**Топ-3 подходящих раствора (TOPSIS):**")
                        alt_df = pd.DataFrame(it.get('Top_3'))
                        st.dataframe(alt_df[['Название', 'Основа', 'Рейтинг', 'Стоимость']], use_container_width=True,
                                     hide_index=True)
                    else:
                        st.info("Альтернативных вариантов не найдено.")
                st.divider()

        pdf_bytes = create_summary_pdf(st.session_state['well_name'], current_intervals)
        st.download_button(label="Скачать Паспорт скважины (PDF)", data=bytes(pdf_bytes),
                           file_name=f"Паспорт_{st.session_state['well_name']}.pdf", mime="application/pdf",
                           type="primary")