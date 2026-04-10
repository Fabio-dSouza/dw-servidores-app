import streamlit as st
import pandas as pd
from supabase import create_client

# Configuração da página
st.set_page_config(
    page_title="Data Warehouse de Servidores",
    layout="wide"
)

st.title("Data Warehouse de Servidores")
st.write("Aplicação Streamlit conectada ao Supabase")

# Criação do cliente Supabase (BACKEND)
supabase = create_client(
    st.secrets["supabase"]["url"],
    st.secrets["supabase"]["service_role_key"]
)

# Chamada da função RPC que retorna a view do DW
response = supabase.rpc("get_vw_indicadores_pessoal").execute()

# Converter os dados para DataFrame
df = pd.DataFrame(response.data)

# Exibir no app
st.dataframe(df, use_container_width=True)

