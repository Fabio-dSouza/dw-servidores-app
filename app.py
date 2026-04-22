import streamlit as st
from supabase import create_client
from groq import Groq
import pandas as pd
import re

# --- 1. Configuração Inicial --- #

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except KeyError as e:
    st.error(f"Erro: Chave secreta não encontrada no st.secrets: {e}")
    st.stop()

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

TABELA_CONSULTA = "dw.view_completa_limpa"
COLUNAS_PERMITIDAS = "tipo_orgao, orgao, cargo, categoria, vinculo, situacao_padronizada"

# --- 2. Funções de Geração e Validação de SQL --- #

def gerar_prompt_sql(pergunta: str) -> str:
    prompt = f"""
Você é um especialista em PostgreSQL para o sistema RHE-RS.
Sua tarefa é gerar SQL para a tabela `{TABELA_CONSULTA}`.

COLUNAS:
- tipo_orgao, orgao, cargo, categoria, vinculo, situacao_padronizada

REGRAS DE FILTRO (MUITO IMPORTANTE):
1. Para ATIVOS: use `situacao_padronizada = 'ATIVO'` (Exato, sem %).
2. Para INATIVOS: use `situacao_padronizada = 'INATIVO'` (Exato, sem %).
3. Para buscas de nomes (orgao, cargo): use `ILIKE '%TERMO%'`.
4. Se a pergunta pedir "quantos" ou "total", use `COUNT(*)`.
5. Se houver colunas de texto e COUNT(*), use `GROUP BY`.

EXEMPLOS:
Pergunta: "quantos ativos"
SQL: SELECT COUNT(*) as total FROM {TABELA_CONSULTA} WHERE situacao_padronizada = 'ATIVO'

Pergunta: "quantas pessoas ativas por tipo de orgao"
SQL: SELECT tipo_orgao, COUNT(*) as total FROM {TABELA_CONSULTA} WHERE situacao_padronizada = 'ATIVO' GROUP BY tipo_orgao

Retorne APENAS o SQL.
Pergunta do Usuário: {pergunta}
"""
    return prompt

def gerar_sql_ia(pergunta: str) -> str:
    prompt_completo = gerar_prompt_sql(pergunta)
    try:
        resposta_ia = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt_completo}]
        )
        return resposta_ia.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Erro na IA: {e}")
        raise

def extrair_sql(conteudo_ia: str) -> str:
    match = re.search(r"(SELECT[\s\S]*?)(?:;|$)", conteudo_ia, re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
        return " ".join(sql.split()).replace(";", "")
    return conteudo_ia

def validar_e_corrigir_sql(sql: str) -> str:
    sql_upper = sql.upper()
    if any(p in sql_upper for p in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
        raise ValueError("Comando não permitido.")
    
    # Garante que situacao_padronizada use os termos corretos se a IA errar
    sql = re.sub(r"situacao_padronizada\s+ILIKE\s+'%?ATIVO%?'", "situacao_padronizada = 'ATIVO'", sql, flags=re.IGNORECASE)
    sql = re.sub(r"situacao_padronizada\s+ILIKE\s+'%?INATIVO%?'", "situacao_padronizada = 'INATIVO'", sql, flags=re.IGNORECASE)
    
    return sql

# --- 3. Interface --- #

st.set_page_config(page_title="RH-RS Analytics", layout="wide")
st.title("📊 Consulta Inteligente RH-RS")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "data" in msg: st.dataframe(msg["data"])

pergunta = st.chat_input("Sua pergunta...")

if pergunta:
    st.session_state.chat_history.append({"role": "user", "content": pergunta})
    with st.chat_message("user"): st.write(pergunta)
    
    with st.chat_message("assistant"):
        try:
            sql_bruto = gerar_sql_ia(pergunta)
            sql_limpo = extrair_sql(sql_bruto)
            sql_final = validar_e_corrigir_sql(sql_limpo)
            
            st.code(sql_final, language="sql")
            
            res = supabase_client.rpc("execute_sql", {"query": sql_final}).execute()
            
            if res.data:
                df = pd.DataFrame(res.data)
                st.write("### Resultados")
                st.dataframe(df)
                st.session_state.chat_history.append({"role": "assistant", "content": "Dados encontrados:", "data": df})
            else:
                st.warning("Nenhum resultado encontrado (Soma 0). Verifique se os termos 'ATIVO'/'INATIVO' estão corretos no banco.")
                st.session_state.chat_history.append({"role": "assistant", "content": "Nenhum resultado encontrado."})
        except Exception as e:
            st.error(f"Erro: {e}")
