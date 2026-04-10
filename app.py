 import streamlit as st
from supabase import create_client

st.set_page_config(
    page_title="Assistente de Dados de Servidores",
    layout="centered"
)

st.title("🤖 Assistente de Servidores Públicos")
st.write("Pergunte em linguagem natural sobre os dados de servidores.")

# Conexão com Supabase
supabase = create_client(
    st.secrets["supabase"]["url"],
    st.secrets["supabase"]["service_role_key"]
)

# Histórico do chat
if "messages" not in st.session_state:
    st.session_state.messages = []

# Exibir histórico
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Entrada do usuário
user_prompt = st.chat_input("Digite sua pergunta…")

if user_prompt:
    # Mostra pergunta do usuário
    st.session_state.messages.append(
        {"role": "user", "content": user_prompt}
    )
    with st.chat_message("user"):
        st.markdown(user_prompt)

    # Processar pergunta (regra simples por enquanto)
    resposta = ""

    texto = user_prompt.lower()

    if "total" in texto and "servidor" in texto:
        res = supabase.rpc("get_vw_indicadores_pessoal").execute()
        total = sum(row["total_servidores"] for row in res.data)
        resposta = f"✅ Existem **{total} servidores** no total."

    elif "ativo" in texto:
        res = supabase.rpc("get_vw_indicadores_pessoal").execute()
        ativos = sum(
            row["total_servidores"]
            for row in res.data
            if row["situacao"] == "ATIVO"
        )
        resposta = f"🟢 Existem **{ativos} servidores ativos**."

    elif "secretaria" in texto:
        res = supabase.rpc("get_vw_indicadores_pessoal").execute()
        agrupado = {}
        for r in res.data:
            org = r["orgao_executivo"]
            agrupado[org] = agrupado.get(org, 0) + r["total_servidores"]

        resposta = "📊 **Servidores por secretaria:**\n"
        for org, total in agrupado.items():
            resposta += f"- {org}: {total}\n"

    else:
        resposta = (
            "🤔 Ainda não entendi completamente.\n\n"
            "Você pode perguntar, por exemplo:\n"
            "- Quantos servidores ativos existem?\n"
            "- Total de servidores\n"
            "- Servidores por secretaria"
        )

    # Mostra resposta
    st.session_state.messages.append(
        {"role": "assistant", "content": resposta}
    )
    with st.chat_message("assistant"):
        st.markdown(resposta)
``
