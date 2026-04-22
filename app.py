import streamlit as st
from supabase import create_client
from groq import Groq
import pandas as pd
import re

# --- 1. Configuração Inicial --- #

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except KeyError as e:
    st.error(f"Erro: Chave secreta não encontrada no st.secrets: {e}")
    st.stop()

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

TABELA_CONSULTA = "dw.view_completa_limpa"
COLUNAS_PERMITIDAS = "tipo_orgao, orgao, cargo, categoria, vinculo, situacao_padronizada"

# --- 2. Funções de Geração e Validação de SQL --- #

def gerar_prompt_sql(pergunta: str) -> str:
    prompt = f"""
Você é um especialista em PostgreSQL. Sua tarefa é traduzir perguntas de usuários em queries SQL precisas para a tabela `{TABELA_CONSULTA}`.

COLUNAS PERMITIDAS:
- tipo_orgao, orgao, cargo, categoria, vinculo, situacao_padronizada

REGRAS OBRIGATÓRIAS:
1. Retorne APENAS o código SQL. NUNCA explique nada.
2. NUNCA use ponto e vírgula (;).
3. Se o usuário pedir "total", "quantidade" ou "número de servidores", use COUNT(*).
4. Use ILIKE '%TERMO%' para buscas textuais flexíveis.
5. Se selecionar colunas de texto junto com COUNT(*), você DEVE usar GROUP BY.

EXEMPLO DE RESPOSTA (SÓ ISSO):
SELECT orgao, COUNT(*) as total FROM {TABELA_CONSULTA} WHERE orgao ILIKE '%SAUDE%' GROUP BY orgao

Pergunta do Usuário: {pergunta}
"""
    return prompt

def gerar_sql_ia(pergunta: str) -> str:
    prompt_completo = gerar_prompt_sql(pergunta)
    try:
        resposta_ia = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt_completo}]
        )
        return resposta_ia.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Erro na IA: {e}")
        raise

def extrair_sql(conteudo_ia: str) -> str:
    # 1. Tenta pegar o que está entre blocos de código markdown ```sql ... ```
    match_md = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", conteudo_ia, re.IGNORECASE)
    if match_md:
        conteudo_ia = match_md.group(1)
    
    # 2. Se não houver blocos de código, tenta pegar a partir do primeiro SELECT até o fim da linha ou ponto e vírgula
    # Esta regex ignora qualquer texto antes do SELECT
    match_select = re.search(r"(SELECT[\s\S]*?)(?:;|$)", conteudo_ia, re.IGNORECASE)
    if match_select:
        sql = match_select.group(1).strip()
    else:
        # Se falhar, tenta pegar a primeira linha que começa com SELECT
        linhas = conteudo_ia.split('\n')
        sql = next((l.strip() for l in linhas if l.strip().upper().startswith("SELECT")), conteudo_ia)
    
    # Limpeza final: remove ponto e vírgula e espaços extras
    sql = sql.replace(";", "").strip()
    # Remove qualquer comentário SQL ou quebra de linha que a IA possa ter inserido
    sql = " ".join(sql.split())
    
    return sql

def validar_e_corrigir_sql(sql: str) -> str:
    sql_upper = sql.upper()
    
    # Proteção básica
    if any(p in sql_upper for p in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
        raise ValueError("Comando SQL não permitido.")
    
    # Garante que é um SELECT
    if not sql_upper.startswith("SELECT"):
        raise ValueError("A query gerada não é um comando SELECT válido.")
    
    # Auto-correção de colunas (vincolo -> vinculo, situacao -> situacao_padronizada)
    sql = re.sub(r'\bvincolo\b', 'vinculo', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bsituacao\b(?!_padronizada)', 'situacao_padronizada', sql, flags=re.IGNORECASE)
    
    # Garante GROUP BY se houver COUNT e outras colunas
    if "COUNT(" in sql_upper and "GROUP BY" not in sql_upper:
        match_select = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE)
        if match_select:
            colunas = [c.strip() for c in match_select.group(1).split(",")]
            sem_agregacao = [c for c in colunas if "COUNT" not in c.upper()]
            if sem_agregacao:
                sql += f" GROUP BY {', '.join(sem_agregacao)}"
                
    return sql

# --- 3. Interface e Execução --- #

st.set_page_config(page_title="RH-RS Analytics", layout="wide")
st.title("📊 Consulta Inteligente RH-RS")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Exibe histórico
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "data" in msg: st.dataframe(msg["data"])

pergunta = st.chat_input("Ex: Qual o total de servidores na secretaria da SAUDE?")

if pergunta:
    st.session_state.chat_history.append({"role": "user", "content": pergunta})
    with st.chat_message("user"): st.write(pergunta)
    
    with st.chat_message("assistant"):
        try:
            with st.spinner("Consultando banco de dados..."):
                sql_bruto = gerar_sql_ia(pergunta)
                sql_limpo = extrair_sql(sql_bruto)
                sql_final = validar_e_corrigir_sql(sql_limpo)
                
                st.code(sql_final, language="sql")
                
                res = supabase_client.rpc("execute_sql", {"query": sql_final}).execute()
                
                if res.data:
                    df = pd.DataFrame(res.data)
                    
                    # Lógica de Pivot Table Automática
                    if 'orgao' in df.columns and 'situacao_padronizada' in df.columns:
                        val_cols = [c for c in df.columns if c not in ['orgao', 'situacao_padronizada']]
                        if val_cols:
                            df_pivot = df.pivot_table(index='orgao', columns='situacao_padronizada', values=val_cols[0], aggfunc='sum', fill_value=0)
                            df_pivot['TOTAL GERAL'] = df_pivot.sum(axis=1)
                            st.write("### Resumo Consolidado")
                            st.dataframe(df_pivot)
                            st.session_state.chat_history.append({"role": "assistant", "content": "Resumo gerado:", "data": df_pivot})
                        else:
                            st.dataframe(df)
                            st.session_state.chat_history.append({"role": "assistant", "content": "Dados encontrados:", "data": df})
                    else:
                        st.write("### Resultados")
                        st.dataframe(df)
                        st.session_state.chat_history.append({"role": "assistant", "content": "Dados encontrados:", "data": df})
                else:
                    st.warning("Nenhum resultado encontrado.")
                    st.session_state.chat_history.append({"role": "assistant", "content": "Nenhum resultado encontrado."})
                    
        except Exception as e:
            st.error(f"Erro: {e}")
            st.session_state.chat_history.append({"role": "assistant", "content": f"Erro: {e}"})
