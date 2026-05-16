import os
import plotly.graph_objects as go
import plotly.express as px
import matplotlib.pyplot as plt
import pandas as pd
from fpdf import FPDF


# --- СТИЛЬНЫЙ ГРАФИК РЕЙТИНГА (ВМЕСТО РАДАРА) ---
def plot_radar_chart(top_3_data):
    # Преобразуем данные
    names = [fluid['Название'] for fluid in top_3_data]
    # Очищаем проценты от знака % и переводим в число
    scores = [float(fluid['Рейтинг'].replace('%', '')) for fluid in top_3_data]

    # Делаем красивый горизонтальный бар-чарт
    fig = go.Figure(go.Bar(
        x=scores,
        y=names,
        orientation='h',
        marker=dict(
            color=scores,
            colorscale='Viridis',  # Красивый градиент
            line=dict(color='rgba(0,0,0,0)', width=1)
        ),
        text=[f"{s}%" for s in scores],
        textposition='auto'
    ))

    fig.update_layout(
        title="Рейтинг растворов (AHP-TOPSIS)",
        xaxis_title="Оценка соответствия (%)",
        yaxis=dict(autorange="reversed"),  # Чтобы победитель был сверху
        margin=dict(l=20, r=20, t=40, b=20),
        height=250,
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig


# --- СТИЛЬНАЯ КАРТА ЗАТРАТ (ВМЕСТО КРУГОВОГО) ---
def plot_cost_pie(recipe_data):
    labels = [r['Реагент'].split(' (')[0] for r in recipe_data]
    values = [r.get('Цена', 10) for r in recipe_data]

    # Используем Treemap (современные "плитки" затрат)
    df = pd.DataFrame({'Реагент': labels, 'Стоимость (руб)': values})
    df = df[df['Стоимость (руб)'] > 0]  # Убираем нули

    fig = px.treemap(
        df,
        path=['Реагент'],
        values='Стоимость (руб)',
        color='Стоимость (руб)',
        color_continuous_scale='Blues',
        title="Структура бюджета (руб/м³)"
    )

    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=300)
    fig.update_traces(textinfo="label+value+percent entry")
    return fig


# --- PDF ГЕНЕРАТОР (Остается без изменений, он хорош) ---
def create_summary_pdf(well_name, intervals):
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()

    font_path = "Roboto-Regular.ttf"
    if os.path.exists(font_path):
        pdf.add_font("Roboto", "", font_path, uni=True)
        pdf.set_font("Roboto", size=16)
    else:
        pdf.set_font("Arial", size=16)

    pdf.cell(0, 10, txt="ИНЖЕНЕРНЫЙ ПАСПОРТ СКВАЖИНЫ", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font(pdf.font_family, size=12)
    pdf.cell(0, 10, txt=f"Проект: {well_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    for idx, it in enumerate(intervals):
        if pdf.get_y() > 220:
            pdf.add_page()

        pdf.set_fill_color(230, 230, 230)
        pdf.set_font(pdf.font_family, size=12)
        pdf.cell(0, 10, txt=f" {it.get('Имя_интервала', '')} (до {it.get('H', 0)} м)", border=1, fill=True,
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.font_family, size=10)
        pdf.cell(0, 8,
                 txt=f"  Окно бурения: {it.get('Rho_min')} - {it.get('Rho_max')} г/см3 | Стоимость: {it.get('Cost_Total', 0):,.0f} руб.",
                 new_x="LMARGIN", new_y="NEXT", border='LRB')
        pdf.ln(4)

        pdf.set_font(pdf.font_family, size=10)
        pdf.cell(0, 8, txt="Рецептура на 1 м³:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.font_family, size=9)

        for r in it.get('RecipeTotal', []):
            pdf.cell(10, 6, txt="")
            pdf.cell(110, 6, txt=r.get('Реагент', ''), border=1)
            pdf.cell(40, 6, txt=r.get('На 1 м³', ''), border=1, align='C')
            pdf.ln()

        # Для PDF оставляем простой горизонтальный бар-чарт по стоимости
        labels = [r['Реагент'].split(' (')[0] for r in it.get('RecipeTotal', [])]
        values = [r.get('Цена', 100) for r in it.get('RecipeTotal', [])]

        fig, ax = plt.subplots(figsize=(6, 2.5))
        ax.barh(labels, values, color='#1f77b4')
        ax.set_title('Стоимость реагентов (руб/м³)', fontsize=10)
        plt.tight_layout()

        img_path = f"tmp_bar_{idx}.png"
        fig.savefig(img_path, bbox_inches='tight', dpi=150, facecolor='white')
        plt.close(fig)

        if pdf.get_y() > 200:
            pdf.add_page()

        pdf.ln(2)
        pdf.image(img_path, w=120)
        os.remove(img_path)
        pdf.ln(10)

    return pdf.output(dest='S')