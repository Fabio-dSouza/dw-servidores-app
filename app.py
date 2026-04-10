

import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

st.set_page_config(page_title="DW Servidores", layout="wide")

st.title("Data Warehouse de Servidores")
st.write("Aplicação Streamlit conectada ao Supabase")

# Montando a URL de conexão
db_url = (
    f"postgresql+psycopg2://{st.secrets['supabase']['user']}:"
    f"{st.secrets['supabase']['password']}@"
    f"{st.secrets['supabase']['host']}:"
    f"{st.secrets['supabase']['port']}/"
    f"{st.secrets['supabase']['database']}?sslmode=require"
)

engine = create_engine(db_url)

df = pd.read_sql(
    "select * from dw.vw_indicadores_pessoal limit 20",
    engine
)

st.dataframe(df)

