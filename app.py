
import streamlit as st
from supabase import create_client

st.set_page_config(
    page_title="Assistente de Servidores",
    layout="centered"
)

st.title("🤖 Assistente de Servidores Públicos")
st.write("Faça perguntas em linguagem natural sobre os dados.")

# Cliente Supabase
supabase = create_client(
    st.secrets["supabase"]["url"],
    st.secrets["supabase"]["service_role_key"]
)

# Histórico do chat
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostrar histórico
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Entrada do usuário
prompt = st.chat_input("Digite sua pergunta...")

if prompt:
    # Exibe pergunta
    st.session_state.messages.append(
        {"role": "user", "content": prompt}
    )
    with st.chat_message("user"):
        st.markdown(prompt)

    texto = prompt.lower()
    resposta = ""

    # Chamada aos dados (sem mostrar tabela)
    data = supabase.rpc("get_vw_indicadores_pessoal").execute().data

    if "total" in texto and "servidor" in texto:
        total = sum(d["total_servidores"] for d in data)
        resposta = f"✅ Existem **{total} servidores** no total."

    elif "ativo" in texto:
        ativos = sum(
            d["total_servidores"]
            for d in data
            if d["situacao"] == "ATIVO"
        )
        resposta = f"🟢 Existem **{ativos} servidores ativos**."

    elif "secretaria" in texto or "órgão" in texto:
        resumo = {}
        for d in data:
            org = d["orgao_executivo"]
            resumo[org] = resumo.get(org, 0) + d["total_servidores"]

        resposta = "📊 **Servidores por órgão:**\n"
        for org, qtd in resumo.items():
            resposta += f"- {org}: {qtd}\n"

    else:
        resposta = (
            "🤔 Não entendi completamente.\n\n"
            "Exemplos de perguntas:\n"
            "- Quantos servidores ativos existem?\n"
            "- Total de servidores\n"
            "- Servidores por secretaria"
        )

    # Exibe resposta
    st.session_state.messages.append(
        {"role": "assistant", "content": resposta}
    )
    with st.chat_message("assistant"):
        st.markdown(resposta)

