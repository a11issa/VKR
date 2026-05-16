import numpy as np
import pandas as pd
from db import get_db_connection


def calculate_physics(H, P_pl, P_gr, T_zab, angle):  # Добавили P_gr
    rho_w = 1000
    g = 9.81

    # Считаем требуемую плотность (нижняя граница) с коэффициентом запаса
    k_a = (P_pl * 1e6) / (rho_w * g * H)
    k_p = 1.12 if H <= 1200 else (1.07 if H <= 2500 else 1.05)
    rho_0 = k_a * k_p

    # Считаем плотность гидроразрыва (верхняя граница окна бурения)
    # Формула: Градиент давления разрыва переводим в плотность
    rho_max = (P_gr * 1e6) / (g * H * 1000)

    if rho_0 > rho_max:
        return None, None, None, None, f"Ошибка: Окно давлений закрыто! Требуемая плотность {rho_0:.2f} г/см³ превышает плотность разрыва {rho_max:.2f} г/см³."

    return round(rho_0, 2), round(rho_max, 2), max(5.0, 33 * rho_0 - 22), 10 + 1.377 * angle, None


def calculate_topsis(df, weights):
    if len(df) == 1: return np.array([1.0])
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
    return dist_worst / (dist_best + dist_worst)


def get_smart_recipe_from_db(D_mm, H, rho_req, fluid_id, preset_name, T_zab, base_density, base_type):
    V_total = round((np.pi * ((D_mm / 1000.0) ** 2) / 4) * H * 1.2, 1)
    fluid_base_name = "Нефтяная основа (РУО)" if base_type == "Углеводородная" else "Вода техническая"

    if H < 500: return V_total, [{"Реагент": "Бентонит (ПБМА)", "На 1 м³": "40 кг", "Цена": 400},
                                 {"Реагент": "NaOH (Сода)", "На 1 м³": "1 кг", "Цена": 100},
                                 {"Реагент": fluid_base_name, "На 1 м³": "1000 л", "Цена": 0}]

    litho_tag = 'Глины' if 'глин' in str(preset_name).lower() else (
        'Трещины' if 'трещин' in str(preset_name).lower() else 'Общий')
    total_recipe_data = []

    conn = get_db_connection()
    try:
        df_reagents = pd.read_sql(
            "SELECT r.name, fr.concentration, r.function_type FROM fluid_reagents fr JOIN reagents r ON fr.reagent_id = r.id WHERE fr.fluid_id = %s AND r.max_temp >= %s AND (r.target_lithology = 'Общий' OR r.target_lithology = %s)",
            conn, params=(int(fluid_id), float(T_zab), litho_tag))
    except:
        df_reagents = pd.DataFrame()
    finally:
        conn.close()

    barite_kg = 0
    v_base_fraction = 1.0

    if rho_req > base_density and rho_req < 4.2:
        barite_kg = int(1000 * 4.2 * (rho_req - base_density) / (4.2 - base_density))
        v_barite = barite_kg / 4200.0
        v_base_fraction = 1.0 - v_barite

    if not df_reagents.empty:
        for _, row in df_reagents.iterrows():
            corrected_conc = row['concentration'] * v_base_fraction
            mass = int(round(corrected_conc, 0)) if corrected_conc >= 1 else round(corrected_conc, 2)
            total_recipe_data.append(
                {"Реагент": f"{row['name']} ({row['function_type']})", "На 1 м³": f"{mass} кг", "Цена": mass * 150})

    if barite_kg > 0:
        total_recipe_data.append(
            {"Реагент": "Барит (Утяжелитель)", "На 1 м³": f"{barite_kg} кг", "Цена": barite_kg * 12})

    base_liters = int(v_base_fraction * 1000)
    total_recipe_data.append(
        {"Реагент": fluid_base_name, "На 1 м³": f"{base_liters} л", "Цена": int(v_base_fraction * 500)})

    return V_total, total_recipe_data