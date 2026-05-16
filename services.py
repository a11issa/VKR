import pandas as pd
import numpy as np
from db import get_db_connection, get_presets, get_fluids_filtered
from calculations import get_smart_recipe_from_db, calculate_topsis

def load_intervals_from_db(project_id):
    conn = get_db_connection()
    query = """
        SELECT ch.id, ch.interval_name, ch.depth, ch.diameter, ch.p_pl, ch.t_zab, ch.angle, ch.fluid_type,
               ch.req_density_min, ch.req_density_max, ch.req_viscosity, pr.name AS preset_name,
               f.id AS fluid_id, f.name AS fluid_name, f.density_min AS base_density, f.base_type, f.cost
        FROM calculation_history ch
        JOIN presets pr ON ch.preset_id = pr.id
        JOIN fluids f ON ch.selected_fluid_id = f.id
        WHERE ch.project_id = %s ORDER BY ch.id ASC
    """
    df = pd.read_sql(query, conn, params=(int(project_id),))
    conn.close()

    presets_df = get_presets()
    intervals = []

    for _, row in df.iterrows():
        V, recipe_total = get_smart_recipe_from_db(row['diameter'], row['depth'], row['req_density_min'],
                                                   row['fluid_id'], row['preset_name'], row['t_zab'],
                                                   row['base_density'], row['base_type'])

        radar_data = []
        df_fluids = get_fluids_filtered(row['req_density_min'], row['req_density_max'], row['t_zab'])
        if not df_fluids.empty and not presets_df.empty:
            preset_row = presets_df[presets_df['name'] == row['preset_name']].iloc[0]
            weights = np.array(
                [preset_row['weight_inhibition'], preset_row['weight_friction'], preset_row['weight_eco'],
                 preset_row['weight_cost']])
            df_fluids["Рейтинг"] = calculate_topsis(df_fluids, weights)
            df_fluids = df_fluids.sort_values("Рейтинг", ascending=False).reset_index(drop=True)

            for _, alt_row in df_fluids.head(3).iterrows():
                norm_cost = 1.0 / (alt_row['Стоимость'] / 1000) if alt_row['Стоимость'] > 0 else 1.0
                radar_data.append({
                    "Название": alt_row['Название'], "Основа": alt_row['Основа'],
                    "Рейтинг": f"{(alt_row['Рейтинг'] * 100):.1f}%",
                    "Ингибирование": alt_row['inhibition'] / 100, "Трение": 1.0 - alt_row['friction'],
                    "Экология": alt_row['eco_score'] / 10, "Экономичность": min(1.0, norm_cost),
                    "Стоимость": alt_row['Стоимость']
                })

        intervals.append({
            "id": row['id'], "Имя_интервала": row['interval_name'], "H": row['depth'], "D_mm": row['diameter'],
            "P_pl": row['p_pl'], "T_zab": row['t_zab'], "Angle": row['angle'], "Fluid_type": row['fluid_type'],
            "Preset": row['preset_name'], "Rho_min": row['req_density_min'], "Rho_max": row['req_density_max'],
            "Viscosity": row['req_viscosity'], "Fluid_id": row['fluid_id'], "Раствор": row['fluid_name'],
            "Volume": V, "RecipeTotal": recipe_total, "Cost_Total": V * row['cost'], "Top_3": radar_data
        })
    return intervals