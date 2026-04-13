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
FONTE: Todos os dados dizem respespeito aos servidores ativos e inativos do poder executivo do estado do Rio Grande do sul

COLUNAS DISPONÍVEIS:
   SITUAÇÃO: "ativos": "ATIVO".
    "ativo": "ATIVO".
    "inativos": "INATIVO".
    "inativo": "INATIVO".
    
    COLUNAS
   - "orgao_executivo": "texto".
    -"cargo_nome": "texto".
    -"categoria": "texto".
    -"tipo_vinculo": "texto".
    -"situacao": "texto".
-"total_servidores": "numero".
- 'orgao_executivo': Nome do órgão (Ex: 'FAZENDA', 'PLANEJAMENTO', 'SAUDE'), significa o local onde o servidor está trabalhando ou lotado (sinônimos).
- 'situacao': Status (Ex: 'ATIVO', 'INATIVO'), significa se o servidor está efetivamente trabalhando (ativo) ou aposentado (inativo).
- 'tipo_vinculo': Vínculo (Ex: 'EFETIVO', 'COMISSIONADO', 'CONTRATADO'), significa o tipo de contrato que o indivíduo tem com o Estado.
- 'nome_cargo': é o nome do cargo que o indivíduo possui e pode ser utilizado como critério para filtragem de dados, é filho da Categoria, pois está contifo nela.
- 'categoria': é onde o cargo está contido e faz uma divisão entre grupos de cargos dentro da administração pública do Rio Grande do Sul
- 'total_servidores': Coluna numérica com a QUANTIDADE de pessoas.

REGRAS OBRIGATÓRIAS:
1. Se perguntar "quantos", "total" ou "quantidade", use SEMPRE operacao='soma', sempre a última coluna deve ser somanda, 
quando a pergunta questionar em relação a vínculos ou servidores, está falando a respeito do número que se encontra na última coluna
2. Se a pergunta tiver dois critérios ou mais (ex: Ativos E Fazenda), o JSON DEVE ter todos os filtros solicitados pela pergunta.
3. Se perguntar "quais tipos" ou "quais cargos", use operacao='lista' e agrupar_por='coluna'.
4. NUNCA explique nada. Responda apenas o JSON.
5. quando houver algum erro na resposta, me mostre a dificuldade que você encontrou.
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
    query = supabase.schema("dw").table(TABELA).select("*").limit(10000)

    # Aplicar Filtros Cruzados
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

    # garantir numérico
    df["total_servidores"] = pd.to_numeric(df["total_servidores"], errors="coerce").fillna(0)

    # operação soma
    if intencao.get("operacao") == "soma":
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
