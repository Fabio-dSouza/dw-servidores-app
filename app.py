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

# 🧠 GERAR SQL
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

🚨 REGRAS CRÍTICAS:

- Todos os dados são extraídos da base do sistema RHE (Sistema de Recursos Humanos do estado do Rio Grande do Sul (RS) TODOS OS DADOS SÃO DO PODER EXECUTIVO DO RS
- "adm direta", "administração direta" → tipo_orgao ILIKE '%DIRETA%'
- orgao diz respeito ao local de exercício dos servidor, geralmente sobre a secretaria, mas pode trazer o nome de um órgão específico
-  quando você não entender uma pergunta, buscar entendimento com o usuario, tentando especificar o que você não entendeu da pergunta
- utilize os filtros solicitados pelo prompt do usuário
- cada linha da tabela significa um registro, ou seja, um servidor na base e eles podem possuir variados campos, todos passíveis de filtro;
- quando o usuário solicitar quantidades ou número, em primeiro lugar, execute uma contagem das linhas com os filtros solicitados

EXEMPLO:    
PERGUNTA: Quantos servidores ativos existem na Administração Direta?
RESPOSTA (QUERY):SELECT COUNT(*)  FROM dw.view_completa
                 WHERE situacao ilike 'ATIVO'
                 and tipo_orgao ilike '%DIRETA';
resposta para o usuário: "Existem 122.569 servidores ativos na administração direta no estado do Rio Grande do Sul."


- Para texto:
  UPPER(coluna) ILIKE '%VALOR%'

- NÃO use "="
- NÃO use ponto e vírgula
- Retorne apenas SQL

REGRAS DA TABELA

COLUNAS (TODOS OS CAMPOS SÃO PASSÍVEIS DE SEREM FILTRADOS)
-  Tipo_órgão: diz respeito a classificação do órgão e somente pode assumir estes 3 valores ADMINISTRACAO DIRETA, AUTARQUIA, FUNDAÇÃO
    ADMINSTRAÇÃO DIRETA = "ADM. DIRETA", admi. direta, "direta"
    Quando o questionamento falar sobre 'ADMINISTRAÇÃO INDIRETA" OU "INDIRETA" é agrupado os campos de "AUTARQUIA" E "FUNDAÇÃO"
- vinculo diz respeito ao tipo de contrato do servidor, é como se fosse o tipo de contrato dos servidores
- O CAMPO 'CATEGORIA' DIZ RESPEITO AO VALOR AGREGADO DO CARGO, OU SEJA, PE UM CAMPO "PAI" DO CARGO E UMA CATEGORIA PODE POSSUIR VÁRIOS CARGOS, E UM CARGO PERTENCE A SOMENTE UMA CATEGORIA

Pergunta: {pergunta}
"""

    resposta = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    sql = resposta.choices[0].message.content

    sql = (
        sql.replace("```sql", "")
           .replace("```", "")
           .replace(";", "")
           .strip()
    )

    # 🔥 correção automática
    sql = sql.replace(" = ", " ILIKE ")

    return sql

# 🛡️ VALIDAR
def validar_sql(sql):
    sql_upper = sql.upper()

    proibidos = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]

    for p in proibidos:
        if p in sql_upper:
            raise Exception("Comando SQL não permitido")

    if not sql_upper.startswith("SELECT"):
        raise Exception("Apenas SELECT permitido")

    return sql

# 🔎 EXECUTAR
def executar_sql(sql):
    sql = validar_sql(sql)

    # 🔍 detectar COUNT
    is_count = "COUNT" in sql.upper()

    query = supabase.schema("dw").table("view_completa").select("*", count="exact")

    # 🔥 aplicar filtros simples (ILIKE)
    if "WHERE" in sql.upper():
        where = sql.upper().split("WHERE")[1]

        condicoes = where.split("AND")

        for cond in condicoes:
            if "ILIKE" in cond:
                partes = cond.split("ILIKE")
                coluna = partes[0].strip().lower()
                valor = partes[1].replace("'", "").replace("%", "").strip()

                query = query.ilike(coluna, f"%{valor}%")

    res = query.execute()

    # 🎯 COUNT correto
    if is_count:
        return res.count

    return res.data

# 🗣️ RESPOSTA
def gerar_resposta(pergunta, resultado):

    # 🚨 se for número, responde direto
    if isinstance(resultado, int):
        return f"O total é de {resultado} servidores."

    prompt = f"""
Pergunta: {pergunta}
Resultado: {resultado}

Responda:
- usando APENAS o resultado
- NÃO invente desculpas
- NÃO diga que não tem acesso a dados
"""

    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return res.choices[0].message.content

# 💬 UI
st.title("📊 Consulta Inteligente RH-RS")

if "chat" not in st.session_state:
    st.session_state.chat = []

pergunta = st.chat_input("Ex: quantos servidores ativos na adm direta?")

if pergunta:
    try:
        with st.spinner("Consultando..."):

            # ✅ TUDO AQUI DENTRO PRECISA ESTAR INDENTADO

            if "sql" not in st.session_state:
                st.session_state.sql = ""

            st.session_state.sql = gerar_sql(pergunta)

            st.write("🔍 SQL GERADO (IA):", st.session_state.sql)

            sql_editado = st.text_area(
                "✏️ Ajuste o SQL se necessário:",
                value=st.session_state.sql,
                height=150,
                key="sql_editado"
            )

            if st.button("Executar consulta"):

                resultado = executar_sql(sql_editado)

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
