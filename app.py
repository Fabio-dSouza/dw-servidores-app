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

# 📖 CONTEXTO PARA GERAR SQL
PROMPT_SQL = """
Você é um especialista em SQL PostgreSQL.

Gere uma query SQL baseada na pergunta do usuário.

TABELA: dw.view_completa

COLUNAS DISPONÍVEIS:
- tipo_orgao
- orgao
- cargo
- categoria
- vinculo
- situacao

REGRAS:
- Para contagem → use COUNT(*)
- Use UPPER() para comparações
- Use ILIKE para textos
- Nunca invente colunas
- Não explique nada
- Retorne apenas SQL puro

EXEMPLOS:

Pergunta: quantos servidores ativos?
SQL:
SELECT COUNT(*) FROM dw.view_completa
WHERE UPPER(situacao) = 'ATIVO';

Pergunta: quantos servidores na fazenda?
SQL:
SELECT COUNT(*) FROM dw.view_completa
WHERE UPPER(orgao) ILIKE '%FAZENDA%';
"""

# 🧠 GERAR SQL
def gerar_sql(pergunta):
    prompt = f"{PROMPT_SQL}\n\nPergunta: {pergunta}"

    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    sql = resposta.choices[0].message.content
    sql = sql.replace("```sql", "").replace("```", "").strip()

    return sql

# 🔎 EXECUTAR SQL
def executar_sql(sql):
    try:
        # ⚠️ necessário criar função no Supabase (explico abaixo)
        res = supabase.rpc("execute_sql", {"query": sql}).execute()
        return res.data
    except Exception as e:
        return f"Erro ao executar SQL: {str(e)}"

# 🗣️ GERAR RESPOSTA NATURAL
def gerar_resposta(pergunta, resultado):
    prompt = f"""
Pergunta: {pergunta}
Resultado: {resultado}

Responda de forma clara e objetiva.
"""

    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

# 💬 INTERFACE
st.title("📊 Consulta Inteligente RH-RS (SQL)")

if "chat" not in st.session_state:
    st.session_state.chat = []

pergunta = st.chat_input("Ex: quantos servidores ativos na adm direta?")

if pergunta:
    st.session_state.chat.append({"role": "user", "content": pergunta})

    try:
        with st.spinner("Gerando SQL..."):

            sql = gerar_sql(pergunta)

            # DEBUG
            st.code(sql, language="sql")

            resultado = executar_sql(sql)

            resposta = gerar_resposta(pergunta, resultado)

            msg = {"role": "assistant", "content": resposta}

            # Se vier tabela
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
