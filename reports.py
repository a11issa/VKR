import os
import matplotlib.pyplot as plt
import pandas as pd
from fpdf import FPDF

# Вспомогательные графики (радар и круговая) удалены по запросу для очистки интерфейса.
# Горизонтальный бар-чарт для PDF оставлен без изменений.

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

        # Построение графика для PDF
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