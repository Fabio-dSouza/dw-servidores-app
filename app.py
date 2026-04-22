import streamlit as st
from supabase import create_client
from groq import Groq
import pandas as pd
import re
import time

# ---------------- CONFIG ---------------- #

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

TABELA_CONSULTA = "dw.view_consulta_rhe"
DEFAULT_LIMIT = 1000
AI_MODEL = "llama-3.1-8b-instant"

COLUNAS_PERMITIDAS = {
    "tipo_orgao",
    "situacao",
    "orgao_executivo",
    "categoria",
    "cargo_nome",
    "tipo_vinculo",
    "total_servidores"
}

AREAS_GOVERNO = {
    "educacao": "EDUCACAO",
    "educação": "EDUCACAO",
    "saude": "SAUDE",
    "saúde": "SAUDE",
    "seguranca": "SEGURANCA",
    "segurança": "SEGURANCA",
    "fazenda": "FAZENDA"
}

# ---------------- CLIENTS ---------------- #

@st.cache_resource
def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def get_groq():
    return Groq(api_key=GROQ_API_KEY)

supabase = get_supabase()
groq = get_groq()

# ---------------- PROMPT ---------------- #

def gerar_prompt(pergunta):
    return f"""
Você é especialista em PostgreSQL do sistema RH-RS.

Tabela disponível:
{TABELA_CONSULTA}

COLUNAS PERMITIDAS:
- tipo_orgao
- situacao
- orgao_executivo
- categoria
- cargo_nome
- tipo_vinculo
- total_servidores

REGRAS:

1. A tabela já está agregada
→ para quantidade use:
SUM(total_servidores)

2. Para ativos:
situacao = 'ATIVO'

3. Para aposentados/inativos:
situacao = 'INATIVO'

4. Se o usuário mencionar:
educação, saúde, segurança, fazenda
→ use orgao_executivo

5. Para filtros textuais:
ILIKE '%valor%'

6. Se houver agrupamento:
GROUP BY

7. Retorne SOMENTE SQL

Exemplo:
SELECT SUM(total_servidores) as total
FROM {TABELA_CONSULTA}
WHERE situacao = 'ATIVO'

Pergunta:
{pergunta}
"""

# ---------------- IA ---------------- #

def gerar_sql_ia(pergunta):
    prompt = gerar_prompt(pergunta)

    for tentativa in range(3):
        try:
            resposta = groq.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            return resposta.choices[0].message.content.strip()

        except Exception as e:
            if tentativa == 2:
                raise e
            time.sleep(2)

# ---------------- EXTRAÇÃO ---------------- #

def extrair_sql(texto):
    # remove markdown
    texto = re.sub(
        r"```sql|```",
        "",
        texto,
        flags=re.IGNORECASE
    ).strip()

    # pega apenas o primeiro SELECT até GROUP BY/ORDER BY/LIMIT/fim
    match = re.search(
        r"(SELECT[\s\S]*?(?:GROUP BY[\s\S]*?|ORDER BY[\s\S]*?|LIMIT\s+\d+|FROM[\s\S]*?))(?:$|\n\n|Essa query|Explicação|Observação)",
        texto,
        re.IGNORECASE
    )

    if match:
        sql = match.group(1)

        sql = re.sub(r"\s+", " ", sql).strip()

        # remove ponto e vírgula
        sql = sql.replace(";", "")

        return sql

    raise Exception("Nenhum SQL válido encontrado")

# ---------------- CORREÇÃO ORGÃO ---------------- #

def corrigir_filtro_orgao(sql, pergunta):
    pergunta_lower = pergunta.lower()

    for termo_usuario, termo_sql in AREAS_GOVERNO.items():

        if termo_usuario in pergunta_lower:

            # Corrige categoria -> orgao
            sql = re.sub(
                r"categoria\s+ILIKE\s+'%.*?%'",
                f"orgao_executivo ILIKE '%{termo_sql}%'",
                sql,
                flags=re.IGNORECASE
            )

            # adiciona filtro se IA esquecer
            if "orgao_executivo" not in sql.lower():

                if "where" in sql.lower():
                    sql += f" AND orgao_executivo ILIKE '%{termo_sql}%'"
                else:
                    sql += f" WHERE orgao_executivo ILIKE '%{termo_sql}%'"

    return sql

# ---------------- CORREÇÃO ILIKE ---------------- #

def corrigir_ilike_quotes(sql):

    pattern = r"(ILIKE\s+'%[^']+)(\s+LIMIT)"

    match = re.search(pattern, sql, re.IGNORECASE)

    if match:
        sql = re.sub(
            pattern,
            lambda m: m.group(1) + "%'" + m.group(2),
            sql,
            flags=re.IGNORECASE
        )

    return sql

# ---------------- VALIDAÇÃO ---------------- #

def validar_sql(sql, pergunta):
    sql = re.sub(r"\s+", " ", sql).strip()
    sql_upper = sql.upper()

    # comandos proibidos
    comandos_proibidos = [
        "INSERT", "UPDATE", "DELETE",
        "DROP", "ALTER", "CREATE", "TRUNCATE"
    ]

    for cmd in comandos_proibidos:
        if cmd in sql_upper:
            raise Exception(f"Comando proibido: {cmd}")

    # impedir SELECT *
    if "SELECT *" in sql_upper:
        raise Exception("SELECT * não permitido")

    # força uso apenas da tabela correta
    if TABELA_CONSULTA.lower() not in sql.lower():
        raise Exception("Consulta fora da tabela permitida")

    # colunas permitidas
    colunas_permitidas = [
        "tipo_orgao",
        "situacao",
        "orgao_executivo",
        "categoria",
        "cargo_nome",
        "tipo_vinculo",
        "total_servidores"
    ]

    # extrai colunas do SELECT
    select_match = re.search(
        r"SELECT (.*?) FROM",
        sql,
        re.IGNORECASE
    )

    if select_match:
        campos = select_match.group(1)

        campos_limpos = re.split(r",", campos)

        for campo in campos_limpos:
            campo = campo.strip()

            if "SUM(" in campo.upper():
                continue

            if "COUNT(" in campo.upper():
                continue

            if " AS " in campo.upper():
                campo = campo.split()[0]

            if campo not in colunas_permitidas:
                raise Exception(
                    f"Coluna não permitida: {campo}"
                )

    # perguntas genéricas precisam de filtro
    if "quantos servidores" in pergunta.lower():
        if "WHERE" not in sql_upper:
            raise Exception(
                "Consulta muito ampla. Especifique ativo/inativo/orgão."
            )

    # força LIMIT quando não houver agregação
    if "SUM(" not in sql_upper and "COUNT(" not in sql_upper:
        if "LIMIT" not in sql_upper:
            sql += f" LIMIT {DEFAULT_LIMIT}"

    return sql

# ---------------- EXECUÇÃO ---------------- #

def executar_sql(sql):
    resposta = supabase.rpc(
        "execute_sql",
        {
            "query": sql
        }
    ).execute()

    return resposta.data

# ---------------- UI ---------------- #

st.set_page_config(
    page_title="Consulta RH-RS",
    layout="wide"
)

st.title("📊 Consulta Inteligente RH-RS")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

        if "data" in msg:
            st.dataframe(msg["data"])

pergunta = st.chat_input(
    "Ex: quantos servidores ativos na educação?"
)

if pergunta:
    st.session_state.chat_history.append({
        "role": "user",
        "content": pergunta
    })

    with st.chat_message("user"):
        st.write(pergunta)

    with st.chat_message("assistant"):

        try:
            with st.spinner("Gerando SQL..."):
                sql_bruto = gerar_sql_ia(pergunta)

            st.write("SQL bruto IA:")
            st.code(sql_bruto)

            sql = extrair_sql(sql_bruto)
            sql = corrigir_filtro_orgao(sql, pergunta)
            sql = corrigir_ilike_quotes(sql)
            sql = validar_sql(sql, pergunta)

            st.write("SQL final:")
            st.code(sql, language="sql")

            with st.spinner("Consultando banco..."):
                resultado = executar_sql(sql)

            if resultado:
                df = pd.DataFrame(resultado)

                # resultado agregado
                if len(df.columns) == 1:
                    valor = df.iloc[0, 0]

                    if valor is None:
                        st.warning("Nenhum registro encontrado.")
                    else:
                        st.success(f"Total encontrado: {valor}")

                else:
                    st.dataframe(df)

                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": "Consulta realizada com sucesso",
                    "data": df
                })

            else:
                st.warning("Nenhum resultado encontrado.")

        except Exception as e:
            st.error(f"Erro: {e}")
