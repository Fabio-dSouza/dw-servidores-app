import streamlit as st
from supabase import create_client
from groq import Groq
import json
import pandas as pd

# 🔐 CONFIG
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

TABELA = "vw_indicadores_pessoal"

# 📖 DICIONÁRIO DE DADOS (CONTEXTO PARA A IA)
DICIONARIO = """
OBJETIVO: Você é um tradutor de perguntas para JSON de filtros.
TABELA: 'dw.vw_indicadores_pessoal'

COLUNAS DISPONÍVEIS:
- 'orgao_executivo': Nome do órgão (Ex: 'FAZENDA', 'PLANEJAMENTO', 'SAUDE').
- 'situacao': Status (Ex: 'ATIVO', 'INATIVO').
- 'tipo_vinculo': Vínculo (Ex: 'EFETIVO', 'COMISSIONADO', 'CONTRATADO').
- 'total_servidores': Coluna numérica com a QUANTIDADE de pessoas.

REGRAS OBRIGATÓRIAS:
1. Se perguntar "quantos", "total" ou "quantidade", use SEMPRE operacao='soma'.
2. Se a pergunta tiver dois critérios (ex: Ativos E Fazenda), o JSON DEVE ter ambos no filtro.
3. Se perguntar "quais tipos" ou "quais cargos", use operacao='lista' e agrupar_por='coluna'.
4. NUNCA explique nada. Responda apenas o JSON.
"""

# 🎯 GERAR INTENÇÃO (FILTROS)
def gerar_intencao(pergunta):
    prompt = f"{DICIONARIO}\n\nPergunta do usuário: {pergunta}"
    
    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    
    conteudo = resposta.choices[0].message.content
    conteudo = conteudo.replace("```json", "").replace("```", "").strip()
    
    try:
        obj = json.loads(conteudo)
        return obj[0] if isinstance(obj, list) else obj
    except:
        return {"filtro": {}, "operacao": "lista"}

# 🔎 EXECUTAR CONSULTA
def executar_consulta(intencao):
    query = supabase.schema("dw").table(TABELA).select("*")

    # Aplicar Filtros Cruzados (Importante para não misturar dados)
    filtros = intencao.get("filtro", {})
    if filtros:
        for campo, valor in filtros.items():
            if valor:
                # Usamos ilike para pegar 'SECRETARIA DA FAZENDA' apenas com 'FAZENDA'
                query = query.ilike(campo, f"%{valor}%")

    dados = query.execute().data
    if not dados:
        return "Nenhum registro encontrado para esses critérios."

    df = pd.DataFrame(dados)
    
    # Garante que a coluna de soma seja numérica
    df["total_servidores"] = pd.to_numeric(df["total_servidores"], errors='coerce').fillna(0)

    # Lógica de Soma (Onde estava o erro da Fazenda)
    if intencao.get("operacao") == "soma":
        total_real = int(df["total_servidores"].sum())
        return f"O total encontrado é de {total_real} servidores."

    # Lógica de Listagem (Onde estava o erro do Planejamento)
    if intencao.get("operacao") == "lista" and intencao.get("agrupar_por"):
        coluna = intencao.get("agrupar_por")
        if coluna in df.columns:
            itens = df[coluna].unique().tolist()
            return f"Os tipos de {coluna} encontrados são: {', '.join(map(str, itens))}"

    # Se nada acima bater, retorna uma prévia dos dados
    return df.head(10).to_dict(orient="records")

# 🗣️ RESPOSTA NATURAL
def gerar_resposta_final(pergunta, resultado):
    prompt = f"O usuário perguntou: '{pergunta}'. O resultado do banco de dados foi: {resultado}. Responda de forma direta e amigável."
    
    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content

# 💬 INTERFACE
st.title("📊 Consulta Inteligente RH-RS")

if "chat" not in st.session_state:
    st.session_state.chat = []

pergunta = st.chat_input("Digite sua dúvida (ex: quantos ativos na fazenda?)")

if pergunta:
    st.session_state.chat.append({"role": "user", "content": pergunta})
    
    try:
        with st.spinner("Analisando..."):
            intencao = gerar_intencao(pergunta)
            resultado = executar_consulta(intencao)
            resposta = gerar_resposta_final(pergunta, resultado)
            
            st.session_state.chat.append({"role": "assistant", "content": resposta})
            if isinstance(resultado, list): # Se for lista, mostra a tabela também
                 st.session_state.chat[-1]["data"] = pd.DataFrame(resultado)
    except Exception as e:
        st.error(f"Erro: {str(e)}")

# Exibir chat
for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "data" in msg:
            st.dataframe(msg["data"])
