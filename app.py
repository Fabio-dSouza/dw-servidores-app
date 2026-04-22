import streamlit as st
from supabase import create_client
from groq import Groq
import pandas as pd
import re
import time
from typing import List

# --- 1. Configuração Inicial --- #

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except KeyError as e:
    st.error(f"Erro: Chave secreta não encontrada no st.secrets: {e}")
    st.stop()

TABELA_CONSULTA = "dw.view_completa_limpa"
COLUNAS_PERMITIDAS = "tipo_orgao, orgao, cargo, categoria, vinculo, situacao_padronizada"
COLUNAS_SET = {c.strip().lower() for c in COLUNAS_PERMITIDAS.split(",")}
DEFAULT_LIMIT = 1000
AI_MODEL = "llama-3.1-8b-instant"
IA_RETRIES = 3
IA_RETRY_DELAY = 1.0  # segundos

# --- 1.b Clients com cache --- #

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_resource
def get_groq_client():
    return Groq(api_key=GROQ_API_KEY)

supabase_client = get_supabase_client()
groq_client = get_groq_client()

# --- 2. Funções de Geração e Validação de SQL --- #

def gerar_prompt_sql(pergunta: str) -> str:
    prompt = f"""
Você é um especialista em PostgreSQL para o sistema RHE-RS.
Sua tarefa é gerar SQL para a tabela `{TABELA_CONSULTA}`.

COLUNAS:
- tipo_orgao, orgao, cargo, categoria, vinculo, situacao_padronizada

REGRAS DE FILTRO (MUITO IMPORTANTE):
1. Para ATIVOS: use `situacao_padronizada = 'ATIVO'` (Exato, sem %).
2. Para INATIVOS: use `situacao_padronizada = 'INATIVO'` (Exato, sem %).
3. Para buscas de nomes (orgao, cargo): use `ILIKE '%TERMO%'`.
4. Se a pergunta pedir "quantos" ou "total", use `COUNT(*)`.
5. Se houver colunas de texto e COUNT(*), use `GROUP BY`.

EXEMPLOS:
Pergunta: "quantos ativos"
SQL: SELECT COUNT(*) as total FROM {TABELA_CONSULTA} WHERE situacao_padronizada = 'ATIVO'

Pergunta: "quantas pessoas ativas por tipo de orgao"
SQL: SELECT tipo_orgao, COUNT(*) as total FROM {TABELA_CONSULTA} WHERE situacao_padronizada = 'ATIVO' GROUP BY tipo_orgao

Retorne APENAS o SQL.
Pergunta do Usuário: {pergunta}
"""
    return prompt

def chamar_ia_com_retry(prompt: str) -> str:
    last_exc = None
    for attempt in range(IA_RETRIES):
        try:
            resposta_ia = groq_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            content = resposta_ia.choices[0].message.content.strip()
            if content:
                return content
        except Exception as e:
            last_exc = e
            time.sleep(IA_RETRY_DELAY * (2 ** attempt))
    raise RuntimeError(f"Falha na chamada à IA após {IA_RETRIES} tentativas: {last_exc}")

def gerar_sql_ia(pergunta: str) -> str:
    prompt_completo = gerar_prompt_sql(pergunta)
    return chamar_ia_com_retry(prompt_completo)

def extrair_sql(conteudo_ia: str) -> str:
    # Extrai o primeiro bloco SELECT ... até ; ou fim do texto
    # Remove possíveis blocos de markdown
    # Busca a primeira ocorrência de SELECT
    txt = re.sub(r"```(?:sql)?", "", conteudo_ia, flags=re.IGNORECASE).strip()
    match = re.search(r"(SELECT[\s\S]*?)(?:;|$)", txt, re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
        sql = re.sub(r"\s+", " ", sql)
        return sql
    # fallback: retorna texto original limpo
    return " ".join(txt.split())

def corrigir_agregacao(sql):
    sql_upper = sql.upper()

    # Caso usuário peça separar por situação mas IA esqueça COUNT/GROUP BY
    if (
        "SITUACAO_PADRONIZADA" in sql_upper
        and "COUNT(" not in sql_upper
        and "GROUP BY" not in sql_upper
    ):
        return """
        SELECT situacao_padronizada, COUNT(*) as total
        FROM dw.view_completa_limpa
        GROUP BY situacao_padronizada
        """

    # Caso peça órgão + situação sem agregação
    if (
        "ORGAO" in sql_upper
        and "SITUACAO_PADRONIZADA" in sql_upper
        and "COUNT(" not in sql_upper
    ):
        return """
        SELECT orgao, situacao_padronizada, COUNT(*) as total
        FROM dw.view_completa_limpa
        GROUP BY orgao, situacao_padronizada
        ORDER BY total DESC
        """

    return sql

def validar_select_seguro(sql: str) -> str:
    sql_norm = sql.strip().rstrip(";")
    # Normalizar espaços
    sql_norm = re.sub(r"\s+", " ", sql_norm)
    # Somente SELECT...FROM
    if not re.match(r"^\s*SELECT\b[\s\S]*\bFROM\b", sql_norm, flags=re.IGNORECASE):
        raise ValueError("Apenas consultas SELECT com FROM são permitidas.")
    # Bloquear comandos proibidos
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b", sql_norm, flags=re.IGNORECASE):
        raise ValueError("Comando não permitido.")
    # Forçar uso da tabela autorizada
    if TABELA_CONSULTA.lower() not in sql_norm.lower():
        raise ValueError(f"A consulta deve usar apenas a tabela autorizada: {TABELA_CONSULTA}")
    # Substituições de correção para situacao_padronizada
    sql_norm = re.sub(r"situacao_padronizada\s+ILIKE\s+'%?ATIVO%?'", "situacao_padronizada = 'ATIVO'", sql_norm, flags=re.IGNORECASE)
    sql_norm = re.sub(r"situacao_padronizada\s+ILIKE\s+'%?INATIVO%?'", "situacao_padronizada = 'INATIVO'", sql_norm, flags=re.IGNORECASE)
    # Validar colunas usadas: extrair tokens que parecem colunas e comparar com whitelist
    tokens = re.findall(r"\b([a-z_][a-z0-9_]*)\b", sql_norm, flags=re.IGNORECASE)
    # Remover palavras-chave SQL comuns
    sql_keywords = {
        "select","from","where","group","by","order","limit","offset","as","count","distinct",
        "and","or","on","join","left","right","inner","outer","having","ilike","like","in","not",
        "sum","avg","min","max"
    }
    used_cols = set(t.lower() for t in tokens if t.lower() not in sql_keywords and not t.isdigit())
    # Allow table name tokens; remove if equals table or aliases
    table_name_tokens = {tok.lower() for tok in re.findall(r"[a-z0-9_]+", TABELA_CONSULTA.lower())}
    used_cols = used_cols - table_name_tokens
    # Now ensure any referenced column that is not obviously a SQL keyword is in whitelist OR is an alias/number
    for col in used_cols:
        # if looks like a column (contains underscore) or is in whitelist check
        if col in COLUNAS_SET:
            continue
        # allow typical aggregate aliases like total
        if col in {"total", "count"}:
            continue
        # if it's purely numeric or short alias, skip strict fail (best-effort)
        if re.match(r"^[a-z]{1,2}$", col):
            continue
        # If not allowed, raise
        raise ValueError(f"Coluna/palavra não autorizada detectada ou fora da whitelist: {col}")
    # Garantir LIMIT por padrão
    if not re.search(r"\bLIMIT\b", sql_norm, flags=re.IGNORECASE):
        sql_norm = sql_norm + f" LIMIT {DEFAULT_LIMIT}"
    return sql_norm

# --- 3. Interface --- #

st.set_page_config(page_title="RH-RS Analytics", layout="wide")
st.title("📊 Consulta Inteligente RH-RS")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "data" in msg:
            st.dataframe(msg["data"])

pergunta = st.chat_input("Sua pergunta...")

if pergunta:
    st.session_state.chat_history.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.write(pergunta)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Gerando SQL com IA..."):
                sql_bruto = gerar_sql_ia(pergunta)

            sql_limpo = extrair_sql(sql_bruto)
            sql_final = validar_select_seguro(sql_limpo)

            st.code(sql_final, language="sql")

            # Executa RPC supabase de forma segura (já validamos SQL)
            with st.spinner("Executando consulta no banco..."):
                # Nota: continue usando sua função RPC; assumimos que ela executa SQL em modo leitura
                res = supabase_client.rpc("execute_sql", {"query": sql_final}).execute()

            if res.data:
                df = pd.DataFrame(res.data)
                st.write("### Resultados")
                st.dataframe(df)
                st.session_state.chat_history.append({"role": "assistant", "content": "Dados encontrados:", "data": df})
            else:
                st.warning("Nenhum resultado encontrado (Soma 0). Verifique se os termos 'ATIVO'/'INATIVO' estão corretos no banco.")
                st.session_state.chat_history.append({"role": "assistant", "content": "Nenhum resultado encontrado."})
        except Exception as e:
            st.error(f"Erro: {e}")
            # registrar no histórico para debug (sem dados sensíveis)
            st.session_state.chat_history.append({"role": "assistant", "content": f"Erro ao processar: {e}"})
