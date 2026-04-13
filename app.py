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

# 📖 PROMPT PARA GERAR SQL (INTERNO)
PROMPT_SQL = """
Você é um especialista em SQL PostgreSQL.

Gere uma query SQL baseada na pergunta do usuário.

TABELA: dw.view_completa

COLUNAS:
- tipo_orgao
- orgao
- cargo
- categoria
- vinculo
- situacao

REGRAS:
- Para contagem → COUNT(*)
- Use UPPER() para igualdade
- Use ILIKE para texto parcial
- Nunca invente colunas
- Retorne apenas SQL puro (sem explicação)
"""

# 🧠 GERAR SQL (OCULTO)
def gerar_sql(pergunta):
    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": f"{PROMPT_SQL}\nPergunta: {pergunta}"}]
    )

    sql = resposta.choices[0].message.content
    return sql.replace("```sql", "").replace("```", "").strip()

# 🔎 EXECUTAR SQL
def executar_sql(sql):
    res = supabase.rpc("execute_sql", {"query": sql}).execute()
    return res.data

# 🗣️ GERAR RESPOSTA FINAL (SEM MOSTRAR SQL)
def gerar_resposta(pergunta, resultado):
    prompt = f"""
Pergunta: {pergunta}
Resultado: {resultado}

Responda de forma direta, como um assistente.
Não mencione SQL.
"""

    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

# 💬 INTERFACE
st.title("📊 Consulta Inteligente RH-RS")

if "chat" not in st.session_state:
    st.session_state.chat = []

pergunta = st.chat_input("Ex: quantos servidores ativos na adm direta?")

if pergunta:
    st.session_state.chat.append({"role": "user", "content": pergunta})

    try:
        with st.spinner("Consultando base de dados..."):

            sql = gerar_sql(pergunta)  # 🔥 oculto

            resultado = executar_sql(sql)  # 🔥 executa direto no banco

            resposta = gerar_resposta(pergunta, resultado)

            msg = {"role": "assistant", "content": resposta}

            # se vier tabela
            if isinstance(resultado, list) and len(resultado) > 0:
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
