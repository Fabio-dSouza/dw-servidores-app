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
prompt = f"""
Você é especialista em PostgreSQL.

Gere uma query SQL para a tabela dw.view_completa.

COLUNAS PERMITIDAS:
tipo_orgao, orgao, cargo, categoria, vinculo, situacao

REGRAS OBRIGATÓRIAS:
- Apenas SELECT
- Nunca use INSERT, UPDATE, DELETE
- Nunca invente colunas
- Para contagem → COUNT(*)

🚨 REGRA CRÍTICA:
- Para QUALQUER filtro de texto use SEMPRE:
  UPPER(coluna) ILIKE '%VALOR%'

- NUNCA use "=" para texto

- NÃO use ponto e vírgula (;)
- Retorne apenas SQL

Pergunta: {pergunta}
"""

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
- Use UPPER() para igualdade
- Use ILIKE para texto
- NÃO use ponto e vírgula (;)
- Retorne apenas SQL

Pergunta: {pergunta}
"""

    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    sql = resposta.choices[0].message.content

    return (
        sql.replace("```sql", "")
           .replace("```", "")
           .replace(";", "")
           .strip()
    )
def validar_sql(sql):
    sql_upper = sql.upper()

    # 🚨 bloquear comandos perigosos
    proibidos = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]

    for p in proibidos:
        if p in sql_upper:
            raise Exception("Comando SQL não permitido")

    # 🚨 garantir SELECT
    if not sql_upper.startswith("SELECT"):
        raise Exception("Apenas SELECT é permitido")

    # 🚨 colunas válidas
    colunas_validas = ["TIPO_ORGAO", "ORGAO", "CARGO", "CATEGORIA", "VINCULO", "SITUACAO"]

    for palavra in sql_upper.split():
        if "." not in palavra and palavra.isalpha():
            if palavra not in colunas_validas and palavra not in ["SELECT","FROM","WHERE","AND","OR","COUNT","ILIKE","UPPER","AS"]:
                # não trava tudo, mas reduz erro
                pass

    return sql

def executar_sql(sql):
    sql = validar_sql(sql)

    res = supabase.rpc("execute_sql", {"query": sql}).execute()

    if res.data is None:
        return "Nenhum resultado encontrado."

    return res.data

# 🗣️ GERAR RESPOSTA FINAL (SEM MOSTRAR SQL)
def gerar_resposta(pergunta, resultado):
    prompt = f"""
Usuário perguntou: {pergunta}

Resultado do banco:
{resultado}

Responda:
- direto
- sem mencionar SQL
- com número correto
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
    try:
        with st.spinner("Consultando base..."):

            sql = gerar_sql(pergunta)

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
