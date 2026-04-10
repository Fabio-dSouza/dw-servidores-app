
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
    Responda APENAS JSON válido.
    Tabela: {TABELA}
    Colunas: {COLUNAS}

    REGRAS CRÍTICAS:
    1. Se a pergunta pedir "total", "quantos" ou quantidade de pessoas, use "operacao": "soma" e "campo": "total_servidores".
    2. NUNCA use "count" para colunas que guardam quantidades numéricas.
    3. Para filtros, use apenas palavras-chave (ex: 'FAZENDA' em vez de '1400-SECRETARIA DA FAZENDA').

    Exemplo de saída:
    {{
        "filtro": {{"orgao_executivo": "FAZENDA", "situacao": "ATIVO"}},
        "operacao": "soma",
        "campo": "total_servidores"
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
    query = supabase.schema("dw").table(TABELA).select("*")

    # Aplica todos os filtros que a IA identificar
    if intencao.get("filtro"):
        for campo, valor in intencao["filtro"].items():
            if campo in COLUNAS and valor: # Valida se a coluna existe
                query = query.ilike(campo, f"%{valor}%")

    dados = query.execute().data
    if not dados: return 0

    df = pd.DataFrame(dados)
    
    # Converte para número para evitar erro de soma de strings
    df["total_servidores"] = pd.to_numeric(df["total_servidores"], errors='coerce').fillna(0)

    # Lógica de agregação
    if intencao.get("operacao") in ["soma", "count"]:
        return int(df["total_servidores"].sum())
    
    # Se a pergunta for "Quais categorias...", a IA deve usar agrupar_por
    if intencao.get("agrupar_por"):
        col = intencao["agrupar_por"]
        return df[col].unique().tolist()

    return df.to_dict(orient="records")

# 🗣️ GERAR RESPOSTA NATURAL
def gerar_intencao(pergunta):
    prompt = f"""
    Atue como um tradutor de perguntas naturais para filtros de banco de dados.
    Tabela: {TABELA}
    
    MAPEAMENTO DE COLUNAS (Use isso para decidir o filtro):
    - 'orgao_executivo': Nomes de secretarias e órgãos (ex: Fazenda, Educação, Saúde).
    - 'tipo_vinculo': Tipo de contrato (ex: EFETIVO, COMISSIONADO, TEMPORÁRIO).
    - 'categoria': Grupos de cargos (ex: Professor, Policial, Técnico).
    - 'situacao': Status do servidor (ex: ATIVO, INATIVO).
    - 'cargo_nome': Nome específico da função.

    REGRAS DE OURO:
    1. Se a pergunta citar 'EFETIVO' ou 'COMISSIONADO', o filtro é na coluna 'tipo_vinculo'.
    2. Se a pergunta citar 'ATIVO' ou 'INATIVO', o filtro é na coluna 'situacao'.
    3. Para "quantos", "total" ou "soma", use sempre operacao: "soma" e campo: "total_servidores".
    4. Responda APENAS o JSON.

    Pergunta: {pergunta}
    """
    # ... código Groq ...
    
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
