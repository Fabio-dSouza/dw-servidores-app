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
Colunas disponíveis na tabela 'dw.vw_indicadores_pessoal':
- 'orgao_executivo': Nome da secretaria/órgão (Ex: 'FAZENDA', 'SAUDE', 'EDUCACAO').
- 'situacao': Status do servidor (Ex: 'ATIVO', 'INATIVO').
- 'tipo_vinculo': Tipo de contrato (Ex: 'EFETIVO', 'COMISSIONADO', 'CONTRATO').
- 'categoria': Grupo de carreira (Ex: 'POLICIA CIVIL', 'QUADRO GERAL').
- 'cargo_nome': Nome do cargo específico.
- 'total_servidores': Coluna numérica com a QUANTIDADE de pessoas.
- nas perguntas referentes a quantidades, considerar sempre a última coluna que diz sempre respeito a número de servidores ou vínculos, pois é a mesma coisa.
- na situação diferenciar ativos, inativos, outros e todas as outras situações, se não mencionado nada na pergunra sobre isso, trazer todos os tipos de situação.
- a categoria funciona como um cargo pai da coluna cargo_nome, ou seja, o cargo_nome está contido em uma categoria, mas uma categoria pode ter mais de um cargo_nome.
- considerar o orgão executivo como local de exercício ou lotação do servidor.

"""

# 🎯 GERAR INTENÇÃO (FILTROS)
def gerar_intencao(pergunta):
    prompt = f"""
    Responda APENAS com JSON puro.
    {DICIONARIO}

    Regras:
    1. Para quantidades/totais, use operacao='soma' e campo='total_servidores'.
    2. Para listar tipos, categorias ou nomes, use operacao='lista' e 'agrupar_por' com o nome da coluna.
    3. Use valores em MAIÚSCULAS para os filtros.

    Pergunta: {pergunta}
    """
    
    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    
    conteudo = resposta.choices[0].message.content
    
    # Esta é a parte que estava com erro de indentação:
    conteudo = conteudo.replace("```json", "").replace("```", "").strip()
    
    try:
        obj = json.loads(conteudo)
        # Garante que seja um dicionário, mesmo que a IA mande lista
        if isinstance(obj, list):
            return obj[0]
        return obj
    except:
        return {"filtro": {}, "operacao": "lista", "campo": None}

# 🔎 EXECUTAR CONSULTA
def executar_consulta(intencao):
    query = supabase.schema("dw").table(TABELA).select("*")

    filtros = intencao.get("filtro", {})
    if filtros:
        for campo, valor in filtros.items():
            if valor:
                query = query.ilike(campo, f"%{valor}%")

    dados = query.execute().data
    if not dados:
        return "Nenhum dado encontrado."

    df = pd.DataFrame(dados)

    # 💡 LÓGICA PARA "QUAIS TIPOS..." (Valores Únicos)
    # Se a pergunta pedir tipos/categorias e não for soma:
    if intencao.get("operacao") == "lista":
        # Se a IA sugerir agrupar por uma coluna específica (ex: tipo_vinculo)
        agrupar = intencao.get("agrupar_por") or intencao.get("campo")
        
        if agrupar in df.columns:
            # Retorna apenas os nomes únicos (EFETIVO, COMISSIONADO, etc)
            return df[agrupar].unique().tolist()
    
    # Lógica de Soma (mantida)
    if intencao.get("operacao") == "soma":
        df["total_servidores"] = pd.to_numeric(df["total_servidores"], errors='coerce').fillna(0)
        return int(df["total_servidores"].sum())

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
