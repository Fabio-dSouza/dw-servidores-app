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

TABELA = "dw.view_completa_limpa"

# 🧠 GERAR SQL
def gerar_sql(pergunta):
    prompt = f"""
Você é especialista em PostgreSQL.

Gere uma query SQL para a tabela dw.view_completa.

COLUNAS PERMITIDAS:
tipo_orgao, orgao, cargo, categoria, vinculo, situacao

REGRAS:
FORMATO DE RESPOSTA (OBRIGATÓRIO):

- Retorne SOMENTE UMA LINHA com SQL
- NÃO explique
- NÃO escreva texto antes ou depois
- NÃO use quebras de linha
- NÃO escreva "resposta", "query", ou qualquer explicação

- Apenas SELECT
- Nunca use INSERT, UPDATE, DELETE
- Nunca invente colunas
- Para contagem → COUNT(*)

Se a pergunta for incompleta ou ambígua:
- NÃO gere SQL
- Responda: "PERGUNTA_INSUFICIENTE"

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

Exemplo: quantos servidores ativos que possuem o cargo APPGG?
resposta (query):   SELECT COUNT(*)
                    FROM dw.view_completa
                    WHERE situacao ILIKE 'ATIVO'
                    AND tipo_orgao ILIKE '%DIRETA%'
                    AND cargo ILIKE 'APPGG%'
Essa query conta a quantidade de servidores ativos na Administração Direta que possuem o cargo com o nome a partir de "APPGG".
resposta para o usuário: "Existem 1.897 servidores ativos no cargo de APPGG no estado do Rio Grande do Sul."




- Para filtros textuais SEMPRE use:

- Para situacao:
use match exato:
situacao ILIKE 'ATIVO'
situacao ILIKE 'INATIVO'

- Para orgao, cargo, categoria:
use contains:
orgao ILIKE '%EDUCACAO%'
cargo ILIKE '%APPGG%'
categoria ILIKE '%MAGISTERIO%'
coluna ILIKE '%VALOR%'


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
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    conteudo = resposta.choices[0].message.content

    st.write("🧠 RESPOSTA BRUTA IA:", conteudo)

    if "PERGUNTA_INSUFICIENTE" in conteudo:
        raise Exception("Pergunta incompleta. Seja mais específico.")

    sql = extrair_sql(conteudo)

    return sql

def extrair_sql(conteudo):
    import re

    matches = re.findall(r"SELECT[\s\S]*", conteudo, re.IGNORECASE)

    if not matches:
        print("⚠️ RESPOSTA DA IA:", conteudo)  # DEBUG
        raise Exception("Nenhum SELECT encontrado na resposta da IA")

    sql = matches[0]

    sql = sql.split("\n")[0] if "\n" in sql else sql

    sql = (
        sql.replace("```sql", "")
           .replace("```", "")
           .replace(";", "")
           .strip()
    )

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

import re

def corrigir_group_by(sql):
    sql_upper = sql.upper()

    # só atua se houver COUNT e não existir GROUP BY
    if "COUNT(" in sql_upper and "GROUP BY" not in sql_upper:

        # captura o conteúdo entre SELECT e FROM
        match_select = re.search(
            r"SELECT\s+(.*?)\s+FROM",
            sql,
            re.IGNORECASE
        )

        if not match_select:
            return sql

        select_part = match_select.group(1)

        # separa colunas do SELECT
        colunas = [c.strip() for c in select_part.split(",")]

        # remove agregações
        colunas_sem_count = [
            c for c in colunas
            if "COUNT" not in c.upper()
        ]

        # se só tiver COUNT(*), não precisa GROUP BY
        if not colunas_sem_count:
            return sql

        group_by = ", ".join(colunas_sem_count)

        sql_corrigido = sql + f" GROUP BY {group_by}"

        return sql_corrigido

    return sql

import re

def corrigir_ilike(sql):
    """
    Corrige padrões inválidos como:
    ILIKE 'ATIVO'%
    ILIKE 'INATIVO'%
    """

    pattern = r"ILIKE\s+'([^']+)'%"

    sql_corrigido = re.sub(
        pattern,
        r"ILIKE '%\1%'",
        sql,
        flags=re.IGNORECASE
    )

    return sql_corrigido

# 🔎 EXECUTAR
def executar_sql(sql):
    if not sql:
        raise Exception("SQL não foi gerado")

    sql = validar_sql(sql)
    sql = corrigir_group_by(sql)
    sql = corrigir_ilike(sql)

    st.write("🛠️ SQL FINAL EXECUTADO:", sql)

    res = supabase.rpc("execute_sql", {"query": sql}).execute()

    if not res.data:
        return "Nenhum resultado encontrado."

    if isinstance(res.data, list) and len(res.data) > 0:
        if "count" in res.data[0]:
            return res.data[0]["count"]

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

            # 👇 SALVA PERGUNTA
            st.session_state.chat.append({
                "role": "user",
                "content": pergunta
            })

            sql_gerado = gerar_sql(pergunta)

            st.write("🔍 SQL GERADO (IA):", sql_gerado)

            sql_editado = st.text_area(
                "✏️ Ajuste o SQL se necessário:",
                value=sql_gerado,
                height=150
            )

            resultado = executar_sql(sql_editado)

            st.write("📊 Resultado bruto:", resultado)

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
