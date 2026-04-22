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

COLUNAS_PERMITIDAS = {
    "tipo_orgao",
    "situacao",
    "orgao_executivo",
    "categoria",
    "cargo_nome",
    "tipo_vinculo",
    "total_servidores"
}

DEFAULT_LIMIT = 1000
AI_MODEL = "llama-3.1-8b-instant"

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

Base disponível:
{TABELA_CONSULTA}

Colunas:
- tipo_orgao
- situacao
- orgao_executivo
- categoria
- cargo_nome
- tipo_vinculo
- total_servidores

REGRAS IMPORTANTES:

1. A tabela já está agregada em situação
REGRAS SEMÂNTICAS IMPORTANTES:

- Quando o usuário mencionar secretarias ou áreas governamentais
(ex: educação, saúde, segurança, fazenda),
priorize o campo `orgao_executivo`

Exemplo:
"quantos servidores ativos na educação"

SQL correto:
SELECT SUM(total_servidores) as total
FROM dw.view_consulta_rhe
WHERE situacao = 'ATIVO'
AND orgao_executivo ILIKE '%EDUCACAO%'

2. Para quantidade utilize, observando sempre os filtros que o usuário indicar:

SUM(total_servidores)

3. Para filtros textuais:
use ILIKE '%valor%'

4. Para ativos:
situacao = 'ATIVO'

5. Para aposentados:
situacao = 'INATIVO'

6. Se houver agrupamento:
use GROUP BY

7. Retorne apenas SQL

Exemplo:

Pergunta:
quantos servidores ativos existem?

SQL:
SELECT SUM(total_servidores) as total
FROM {TABELA_CONSULTA}
WHERE situacao = 'ATIVO'

Pergunta:
quantos ativos por órgão?

SQL:
SELECT orgao_executivo,
SUM(total_servidores) as total
FROM {TABELA_CONSULTA}
WHERE situacao = 'ATIVO'
GROUP BY orgao_executivo
ORDER BY total DESC

Pergunta usuário:
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

# ---------------- EXTRAIR SQL ---------------- #

def extrair_sql(texto):
    texto = re.sub(
        r"```sql|```",
        "",
        texto,
        flags=re.IGNORECASE
    ).strip()

    match = re.search(
        r"(SELECT[\s\S]*?)(?:;|$)",
        texto,
        re.IGNORECASE
    )

    if not match:
        raise Exception("Nenhum SQL encontrado")

    return match.group(1).strip()

# ---------------- VALIDAÇÃO ---------------- #

def validar_sql(sql):
    sql_upper = sql.upper()

    comandos_proibidos = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE"
    ]

    for cmd in comandos_proibidos:
        if cmd in sql_upper:
            raise Exception("Comando não permitido")

    if TABELA_CONSULTA.lower() not in sql.lower():
        raise Exception("Consulta fora da tabela permitida")

    if "LIMIT" not in sql_upper:
        sql += f" LIMIT {DEFAULT_LIMIT}"

    return sql

# ---------------- EXECUÇÃO ---------------- #

def executar_sql(sql):
    res = supabase.rpc(
        "execute_sql",
        {
            "query": sql
        }
    ).execute()

    return res.data

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

            sql_limpo = extrair_sql(sql_bruto)
            sql_final = validar_sql(sql_limpo)

            st.code(sql_final, language="sql")

            with st.spinner("Consultando banco..."):
                resultado = executar_sql(sql_final)

            if resultado:
                df = pd.DataFrame(resultado)

                if (
                    len(df.columns) == 1
                    and "total" in df.columns[0].lower()
                ):
                    total = df.iloc[0, 0]
                    st.success(
                        f"Total encontrado: {total}"
                    )
                else:
                    st.dataframe(df)

                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": "Consulta realizada com sucesso",
                    "data": df
                })

            else:
                st.warning(
                    "Nenhum resultado encontrado."
                )

        except Exception as e:
            st.error(f"Erro: {e}")
