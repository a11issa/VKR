import streamlit as st

# КОНФИГУРАЦИЯ СТРАНИЦЫ (Всегда должна быть первой строчкой Streamlit!)
st.set_page_config(page_title="Подбор буровых растворов PRO", layout="wide")

# Импорт интерфейса из ui.py
from ui import show_login_page, show_admin_panel, show_engineer_panel


def init_session():
    if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
    if 'user_role' not in st.session_state: st.session_state['user_role'] = None
    if 'user_id' not in st.session_state: st.session_state['user_id'] = None
    if 'current_project_id' not in st.session_state: st.session_state['current_project_id'] = None


def main():
    init_session()

    if not st.session_state['logged_in']:
        show_login_page()
    else:
        if st.session_state['user_role'] == 'admin':
            show_admin_panel()
        else:
            show_engineer_panel()


if __name__ == "__main__":
    main()