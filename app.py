
import streamlit as st
from supabase import create_client
from groq import Groq
import json
import pandas as pd

# 🔐 CONFIG (Certifique-se de que estão no .streamlit/secrets.toml)
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# 🧠 CONTEXTO DA TABELA
TABELA = "vw_indicadores_pessoal"
COLUNAS = {
    "poder_executivo": "texto",
    "orgao_executivo": "texto",
    "cargo_nome": "texto",
    "categoria": "texto",
    "tipo_vinculo": "texto",
    "situacao": "texto",
    "total_servidores": "número" # Corrigido para número se for somar/fazer média
}

# 🎯 PROMPT PARA GERAR INTENÇÃO
def gerar_intencao(pergunta):
    prompt = f"""
    Responda APENAS com JSON válido.
    Tabela: {TABELA}
    Colunas: {COLUNAS}

    Formato obrigatório:
    {{
        "filtro": {{"nome_da_coluna": "valor"}},
        "operacao": "count | soma | lista",
        "campo": "coluna_para_operacao",
        "agrupar_por": null
    }}
    Pergunta: {pergunta}
    """
    
    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    
    conteudo = resposta.choices[0].message.content
    # Limpeza básica de Markdown
    conteudo = conteudo.replace("```json", "").replace("```", "").strip()
    return json.loads(conteudo)

# 🔎 EXECUTAR CONSULTA VIA SUPABASE
def executar_consulta(intencao):
    query = supabase.table(TABELA).select("*")

    # Aplicar filtros dinâmicos
    if intencao.get("filtro"):
        for campo, valor in intencao["filtro"].items():
            query = query.eq(campo, valor)

    dados = query.execute().data
    if not dados:
        return None

    df = pd.DataFrame(dados)

    # Lógica de processamento de resultados
    operacao = intencao.get("operacao")
    if operacao == "count":
        return len(df)
    elif operacao == "soma" and "total_servidores" in df.columns:
        return int(df["total_servidores"].astype(float).sum())
    elif operacao == "lista":
        return df.head(15).to_dict(orient="records")
    
    return df.to_dict(orient="records")

# 🗣️ GERAR RESPOSTA NATURAL
def gerar_resposta_natural(pergunta, resultado):
    prompt = f"""
    Você é um assistente de dados do RS. 
    Converta o resultado técnico em uma resposta amigável e direta em português.
    Pergunta: {pergunta}
    Resultado: {resultado}
    """
    
    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    return resposta.choices[0].message.content

# 💬 INTERFACE STREAMLIT
st.set_page_config(page_title="RH Inteligente RS", page_icon="📊")
st.title("📊 Consulta Inteligente - Pessoal RS")

if "chat" not in st.session_state:
    st.session_state.chat = []

# Exibir histórico
for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

pergunta = st.chat_input("Ex: Quantos servidores ativos existem na Secretaria da Fazenda?")

if pergunta:
    st.session_state.chat.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.write(pergunta)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Analisando dados..."):
                intencao = gerar_intencao(pergunta)
                resultado = executar_consulta(intencao)
                
                if resultado is None:
                    resposta = "Não encontrei dados para essa consulta."
                else:
                    resposta = gerar_resposta_natural(pergunta, resultado)
                
                st.write(resposta)
                
                # Se for lista, mostra uma tabela para facilitar
                if isinstance(resultado, list):
                    st.dataframe(pd.DataFrame(resultado))
                
                st.session_state.chat.append({"role": "assistant", "content": resposta})
        
        except Exception as e:
            st.error(f"Ocorreu um erro: {e}")
