
import streamlit as st
import pandas as pd
import psycopg2

st.set_page_config(page_title="DW Servidores", layout="wide")

st.title("Data Warehouse de Servidores")
st.write("Aplicação Streamlit conectada ao Supabase")

conn = psycopg2.connect(
    host=st.secrets["supabase"]["host"],
    database=st.secrets["supabase"]["database"],
    user=st.secrets["supabase"]["user"],
    password=st.secrets["supabase"]["password"],
    port=st.secrets["supabase"]["port"]
)

query = "select * from dw.vw_indicadores_pessoal limit 20"
df = pd.read_sql(query, conn)

st.dataframe(df)
