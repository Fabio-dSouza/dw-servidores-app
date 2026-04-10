

import streamlit as st
import pandas as pd
from supabase import create_client

st.set_page_config(page_title="DW Servidores", layout="wide")

st.title("Data Warehouse de Servidores")
st.write("Aplicação Streamlit conectada ao Supabase")

# Conexão via API do Supabase
supabase = create_client(
    st.secrets["supabase"]["url"],
    st.secrets["supabase"]["service_role_key"]
)

# Consulta segura via view
response = supabase.rpc(
    "get_vw_indicadores_pessoal"
).execute()

df = pd.DataFrame(response.data)

st.dataframe(df)

