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
8. Não explique a consulta
9. Não escreva texto antes ou depois do SQL
10. Não use markdown

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

# ADICIONE AQUI
def corrigir_equals_orgao(sql):
    pattern = r"orgao_executivo\s*=\s*'([^']+)'"

    match = re.search(pattern, sql, re.IGNORECASE)

    if match:
        valor = match.group(1)

        sql = re.sub(
            pattern,
            f"orgao_executivo ILIKE '%{valor}%'",
            sql,
            flags=re.IGNORECASE
        )

    return sql

def corrigir_group_by(sql):
    sql_upper = sql.upper()

    # se já possui GROUP BY, não mexe
    if "GROUP BY" in sql_upper:
        return sql

    # só corrige se houver agregação
    if "SUM(" not in sql_upper:
        return sql

    colunas_group = []

    if "TIPO_ORGAO" in sql_upper:
        colunas_group.append("tipo_orgao")

    if "SITUACAO" in sql_upper:
        colunas_group.append("situacao")

    if "ORGAO_EXECUTIVO" in sql_upper:
        colunas_group.append("orgao_executivo")

    if "CATEGORIA" in sql_upper:
        colunas_group.append("categoria")

    if "CARGO_NOME" in sql_upper:
        colunas_group.append("cargo_nome")

    if "TIPO_VINCULO" in sql_upper:
        colunas_group.append("tipo_vinculo")

    if colunas_group:
        sql += " GROUP BY " + ", ".join(colunas_group)

    return sql


def corrigir_select_all(sql, pergunta):
    pergunta_lower = pergunta.lower()

    if "todas as colunas" in pergunta_lower or "tabela completa" in pergunta_lower:
        if "SELECT *" in sql.upper():

            colunas = """
            tipo_orgao,
            situacao,
            orgao_executivo,
            categoria,
            cargo_nome,
            tipo_vinculo,
            total_servidores
            """

            sql = re.sub(
                r"SELECT\s+\*",
                f"SELECT {colunas}",
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

# ---------- CSS ---------- #
st.markdown("""
<style>
.main {
    background-color: #f8fafc;
}

[data-testid="stSidebar"] {
    background-color: #0f172a;
}

[data-testid="stSidebar"] * {
    color: white;
}

div[data-testid="metric-container"] {
    background-color: white;
    border-radius: 12px;
    padding: 15px;
    box-shadow: 0px 2px 8px rgba(0,0,0,0.08);
}

.block-container {
    padding-top: 2rem;
}
</style>
""", unsafe_allow_html=True)

# ---------- SIDEBAR ---------- #
with st.sidebar:
    st.title("RH Analytics RS")

    if st.button("➕ Nova consulta"):
        st.session_state.chat_history = []

    st.subheader("Consultas rápidas")

    if st.button("Servidores ativos"):
        st.session_state.pergunta_rapida = (
            "quantos servidores ativos existem?"
        )

    if st.button("Servidores por órgão"):
        st.session_state.pergunta_rapida = (
            "quantos servidores ativos por orgao"
        )

    if st.button("Servidores da educação"):
        st.session_state.pergunta_rapida = (
            "quantos servidores ativos na educação"
        )

    if st.button("Servidores da fazenda"):
        st.session_state.pergunta_rapida = (
            "quantos servidores ativos na fazenda"
        )

# ---------- HEADER ---------- #
st.title("📊 Consulta Inteligente RH-RS")
st.caption(
    "Consulte dados de servidores públicos do RS usando linguagem natural."
)

# ---------- HISTÓRICO ---------- #
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "pergunta_rapida" not in st.session_state:
    st.session_state.pergunta_rapida = None

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

        if "data" in msg:
            st.dataframe(msg["data"])

# ---------- INPUT ---------- #
pergunta_manual = st.chat_input(
    "Ex: quantos servidores ativos na educação?"
)

pergunta = (
    st.session_state.pergunta_rapida
    if st.session_state.pergunta_rapida
    else pergunta_manual
)

# limpa pergunta rápida após uso
st.session_state.pergunta_rapida = None

# ---------- EXECUÇÃO ---------- #
if pergunta:

    st.session_state.chat_history.append({
        "role": "user",
        "content": pergunta
    })

    with st.chat_message("user"):
        st.write(pergunta)

    with st.chat_message("assistant"):

        try:
            # gerar sql
            with st.spinner("Gerando SQL..."):
                sql_bruto = gerar_sql_ia(pergunta)

            # debug opcional
            with st.expander("Ver SQL bruto IA"):
                st.code(sql_bruto)

            # pipeline de correções
            sql = extrair_sql(sql_bruto)
            sql = corrigir_filtro_orgao(sql, pergunta)
            sql = corrigir_equals_orgao(sql)
            sql = corrigir_ilike_quotes(sql)
            sql = corrigir_group_by(sql)
            sql = validar_sql(sql, pergunta)

            with st.expander("Ver SQL final"):
                st.code(sql, language="sql")

            # consulta banco
            with st.spinner("Consultando banco..."):
                resultado = executar_sql(sql)

            if resultado:

                df = pd.DataFrame(resultado)

                # ---------------- KPI ---------------- #
                if len(df.columns) == 1:
                    valor = df.iloc[0, 0]

                    if valor is None:
                        st.warning(
                            "Nenhum registro encontrado."
                        )
                    else:
                        st.metric(
                            label="Total encontrado",
                            value=f"{int(valor):,}".replace(",", ".")
                        )

                # ---------------- TABELA ---------------- #
                else:
                    st.subheader("Resultados")
                    st.dataframe(
                        df,
                        use_container_width=True
                    )

                    # ---------------- GRÁFICO ---------------- #
                    if "total" in df.columns:
                        coluna_categoria = [
                            c for c in df.columns
                            if c != "total"
                        ][0]

                        grafico_df = df[
                            [coluna_categoria, "total"]
                        ].set_index(coluna_categoria)

                        st.subheader(
                            "Visualização"
                        )

                        st.bar_chart(grafico_df)

                # salva histórico
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
