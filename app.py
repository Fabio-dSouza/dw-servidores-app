import streamlit as st
from supabase import create_client
from groq import Groq
import json
import pandas as pd

# 🔐 CONFIG
supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# 👉 VIEW baseada na STG (1 linha = 1 servidor)
TABELA = "view_completa"

# 📖 CONTEXTO PARA IA
DICIONARIO = """
Você interpreta perguntas e retorna JSON válido.

ATENÇÃO:
- Use SOMENTE estas colunas:
  tipo_orgao, orgao, cargo, categoria, vinculo, situacao

- Nunca invente nomes de colunas
- Nunca use valores genéricos como "orgao"

SINÔNIMOS:
- "adm direta", "adm. direta" → tipo_orgao = "ADMINISTRACAO DIRETA"
- "ativo", "ativos" → situacao = "ATIVO"
- "inativo", "inativos" → situacao = "INATIVO"

REGRAS:
1. "quantos", "total" → operacao = "count"
2. "quais", "listar" → operacao = "lista"
3. Retorne apenas JSON válido

Formato:
{
  "filtro": {},
  "operacao": "count | lista",
  "agrupar_por": null
}
"""

# 🎯 GERAR INTENÇÃO
def gerar_intencao(pergunta):
    prompt = f"{DICIONARIO}\n\nPergunta: {pergunta}"

    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    conteudo = resposta.choices[0].message.content
    conteudo = conteudo.replace("```json", "").replace("```", "").strip()

    try:
        obj = json.loads(conteudo)
        return obj if isinstance(obj, dict) else obj[0]
    except:
        return {"filtro": {}, "operacao": "lista", "agrupar_por": None}

# 🔎 CONSULTA
def executar_consulta(intencao):
    query = supabase.schema("dw").table(TABELA).select("*").limit(50000)

    filtros = intencao.get("filtro", {})

    if filtros:
        for campo, valor in filtros.items():
            if valor:
                valor = str(valor).upper()
                query = query.ilike(campo, f"%{valor}%")

    dados = query.execute().data

    if not dados:
        return "Nenhum registro encontrado."

    df = pd.DataFrame(dados)

    # 🔥 padronização
    for col in ["orgao", "cargo", "categoria", "vinculo", "situacao"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.upper()

    # 🧠 COUNT (principal mudança)
    if intencao.get("operacao") == "count":
        return int(len(df))

    # 🧠 LISTA COM AGRUPAMENTO
if intencao.get("operacao") == "count":
    query = supabase.schema("dw").table(TABELA).select("*", count="exact")

    filtros = intencao.get("filtro", {})

    for campo, valor in filtros.items():
        if valor:
            valor = str(valor).upper()
            query = query.ilike(campo, f"%{valor}%")

    res = query.execute()
    return res.count

# 🗣️ RESPOSTA NATURAL
def gerar_resposta_final(pergunta, resultado):
    prompt = f"""
Pergunta: {pergunta}
Resultado: {resultado}

Responda de forma clara, objetiva e amigável.
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

pergunta = st.chat_input("Ex: quantos servidores ativos na fazenda?")

if pergunta:
    st.session_state.chat.append({"role": "user", "content": pergunta})

    try:
        with st.spinner("Analisando..."):
            intencao = gerar_intencao(pergunta)

            # DEBUG (opcional)
            st.write("🔍 Intenção:", intencao)

            resultado = executar_consulta(intencao)
            resposta = gerar_resposta_final(pergunta, resultado)

            msg = {"role": "assistant", "content": resposta}

            if isinstance(resultado, list) and isinstance(resultado[0], dict):
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
