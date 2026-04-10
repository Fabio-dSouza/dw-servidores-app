
import streamlit as st
from supabase import create_client
from openai import OpenAI
import json
import pandas as pd

# 🔐 CONFIG
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# 🧠 CONTEXTO DA TABELA (AJUSTE AQUI)
TABELA = "servidores"

COLUNAS = {
    "nome": "texto",
    "orgao": "texto",
    "ativo": "booleano",
    "salario": "numero"
}

# 🎯 PROMPT PARA GERAR INTENÇÃO (SEM SQL)
def gerar_intencao(pergunta):
    prompt = f"""
    Você é um sistema que interpreta perguntas e retorna JSON.

    Tabela: {TABELA}
    Colunas:
    {COLUNAS}

    Retorne apenas JSON no formato:
    {{
        "filtro": {{}},
        "operacao": "count | media | lista",
        "campo": "coluna ou null",
        "agrupar_por": "coluna ou null"
    }}

    Pergunta: {pergunta}
    """

    resposta = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return json.loads(resposta.choices[0].message.content)

# 🔎 EXECUTAR CONSULTA SEM SQL
def executar_consulta(intencao):
    query = supabase.table(TABELA).select("*")

    # aplicar filtros
    for campo, valor in intencao["filtro"].items():
        query = query.eq(campo, valor)

    dados = query.execute().data
    df = pd.DataFrame(dados)

    if df.empty:
        return "Nenhum dado encontrado."

    # operações
    if intencao["operacao"] == "count":
        return len(df)

    if intencao["operacao"] == "media":
        return df[intencao["campo"]].mean()

    if intencao["operacao"] == "lista":
        return df.head(10).to_dict(orient="records")

    return df

# 🗣️ GERAR RESPOSTA NATURAL
def gerar_resposta(pergunta, resultado):
    prompt = f"""
    Responda de forma clara e objetiva.

    Pergunta: {pergunta}
    Resultado: {resultado}
    """

    resposta = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return resposta.choices[0].message.content

# 💬 INTERFACE CHAT
st.title("Consulta Inteligente")

if "chat" not in st.session_state:
    st.session_state.chat = []

pergunta = st.chat_input("Digite sua pergunta...")

if pergunta:
    st.session_state.chat.append({"role": "user", "content": pergunta})

    try:
        intencao = gerar_intencao(pergunta)
        resultado = executar_consulta(intencao)
        resposta = gerar_resposta(pergunta, resultado)

    except Exception as e:
        resposta = f"Erro: {str(e)}"

    st.session_state.chat.append({"role": "assistant", "content": resposta})

# exibir chat
for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
