import streamlit as st
from supabase import create_client
from groq import Groq
import pandas as pd

# 🔐 CONFIG
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

client = Groq(api_key=st.secrets["GROQ_API_KEY"])

TABELA = "dw.view_completa"

# 🧠 GERAR SQL
def gerar_sql(pergunta):
    prompt = f"""
Você é especialista em PostgreSQL.

Gere uma query SQL para a tabela dw.view_completa.

COLUNAS PERMITIDAS:
tipo_orgao, orgao, cargo, categoria, vinculo, situacao

REGRAS:
- Apenas SELECT
- Nunca use INSERT, UPDATE, DELETE
- Nunca invente colunas
- Para contagem → COUNT(*)

🚨 REGRA CRÍTICA:
- Para texto use SEMPRE:
  UPPER(coluna) ILIKE '%VALOR%'

- NUNCA use "="
- NÃO use ponto e vírgula
- Retorne apenas SQL

Pergunta: {pergunta}
"""

    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    sql = resposta.choices[0].message.content

    sql = (
        sql.replace("```sql", "")
           .replace("```", "")
           .replace(";", "")
           .strip()
    )

    # 🔥 correção automática
    sql = sql.replace(" = ", " ILIKE ")

    return sql

# 🛡️ VALIDAR
def validar_sql(sql):
    sql_upper = sql.upper()

    proibidos = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]

    for p in proibidos:
        if p in sql_upper:
            raise Exception("Comando SQL não permitido")

    if not sql_upper.startswith("SELECT"):
        raise Exception("Apenas SELECT permitido")

    return sql

# 🔎 EXECUTAR
def executar_sql(sql):
    sql = validar_sql(sql)

    res = supabase.rpc("execute_sql", {"query": sql}).execute()

    if res.data is None:
        return "Nenhum resultado encontrado."

    # 🎯 tratar COUNT
    if isinstance(res.data, list) and len(res.data) > 0:
        if "count" in res.data[0]:
            return res.data[0]["count"]

    return res.data

# 🗣️ RESPOSTA
def gerar_resposta(pergunta, resultado):
    prompt = f"""
Pergunta: {pergunta}
Resultado: {resultado}

Responda de forma direta e clara.
"""

    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

# 💬 UI
st.title("📊 Consulta Inteligente RH-RS")

if "chat" not in st.session_state:
    st.session_state.chat = []

pergunta = st.chat_input("Ex: quantos servidores ativos na adm direta?")

if pergunta:
    try:
        with st.spinner("Consultando..."):

            sql = gerar_sql(pergunta)

            st.write("🔍 SQL GERADO:", sql)  # 👈 DEBUG

            resultado = executar_sql(sql)

            resposta = gerar_resposta(pergunta, resultado)

            msg = {"role": "assistant", "content": resposta}

            if isinstance(resultado, list):
                msg["data"] = pd.DataFrame(resultado)

            st.session_state.chat.append(msg)

    except Exception as e:
        st.error(f"Erro: {str(e)}")

# 🧾 CHAT
for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "data" in msg:
            st.dataframe(msg["data"])
