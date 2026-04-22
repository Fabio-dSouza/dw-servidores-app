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
# ATENÇÃO: Removi 'situacao' e adicionei 'situacao_padronizada'
COLUNAS_PERMITIDAS = "tipo_orgao, orgao, cargo, categoria, vinculo, situacao_padronizada"

# --- 2. Funções de Geração e Validação de SQL --- #

def gerar_prompt_sql(pergunta: str) -> str:
    prompt = f"""
Você é um especialista em PostgreSQL. Sua tarefa é traduzir perguntas de usuários em queries SQL precisas para a tabela `{TABELA_CONSULTA}`.

COLUNAS PERMITIDAS (USE APENAS ESTAS):
- tipo_orgao: Classificação (ADMINISTRACAO DIRETA, AUTARQUIA, FUNDAÇÃO).
- orgao: Nome da secretaria ou órgão.
- cargo: Nome do cargo do servidor.
- categoria: Grupo do cargo.
- vinculo: Tipo de contrato.
- situacao_padronizada: Situação do servidor (ATIVO, INATIVO, etc). NUNCA use apenas 'situacao'.

REGRAS DE OURO:
1. Se o usuário pedir "por situação", "pelo número de servidores" ou "agrupar", você DEVE selecionar a coluna de interesse (ex: orgao) E a coluna situacao_padronizada E fazer um COUNT(*).
2. Sempre que houver um COUNT(*) junto com outras colunas, você DEVE usar GROUP BY para todas as outras colunas.
3. NUNCA invente funções. Use apenas SQL padrão.
4. "Adm direta" ou "Administração direta" -> tipo_orgao ILIKE '%DIRETA%'
5. "Número de servidores", "Quantidade", "Total" -> COUNT(*)

EXEMPLOS DE SUCESSO:
Pergunta: "Mostre o total de servidores por órgão e situação"
SQL: SELECT orgao, situacao_padronizada, COUNT(*) as total FROM {TABELA_CONSULTA} GROUP BY orgao, situacao_padronizada

Pergunta: "Quantos servidores ativos na adm direta por vinculo?"
SQL: SELECT vinculo, COUNT(*) as total FROM {TABELA_CONSULTA} WHERE situacao_padronizada ILIKE 'ATIVO' AND tipo_orgao ILIKE '%DIRETA%' GROUP BY vinculo

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
    # Limpeza de caracteres estranhos
    conteudo_limpo = "".join(i for i in conteudo_ia if ord(i) < 128)
    # Extração do bloco SQL
    match = re.search(r"(SELECT[\s\S]*)", conteudo_limpo, re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
        return sql.split(';')[0].strip() # Pega apenas antes do primeiro ponto e vírgula
    return conteudo_limpo

def validar_sql(sql: str) -> str:
    sql_upper = sql.upper()
    # Proteção contra injeção e comandos perigosos
    if any(p in sql_upper for p in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
        raise ValueError("Comando SQL não permitido.")
    if not sql_upper.startswith("SELECT"):
        raise ValueError("A query deve começar com SELECT.")
    
    # Correção de alucinações comuns
    sql = re.sub(r'\bvincolo\b', 'vinculo', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bsituacao\b(?!_padronizada)', 'situacao_padronizada', sql, flags=re.IGNORECASE)
    return sql

def aplicar_correcoes_finais(sql: str) -> str:
    # Garante GROUP BY se houver COUNT e colunas extras
    sql_upper = sql.upper()
    if "COUNT(" in sql_upper and "GROUP BY" not in sql_upper:
        match_select = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE)
        if match_select:
            colunas = [c.strip() for c in match_select.group(1).split(",")]
            sem_agregacao = [c for c in colunas if "COUNT" not in c.upper() and "AS" not in c.upper().split()[-2:]]
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

pergunta = st.chat_input("Ex: Qual o total de servidores por órgão e situação na adm direta?")

if pergunta:
    st.session_state.chat_history.append({"role": "user", "content": pergunta})
    with st.chat_message("user"): st.write(pergunta)
    
    with st.chat_message("assistant"):
        try:
            with st.spinner("Analisando dados..."):
                sql_bruto = gerar_sql_ia(pergunta)
                sql_limpo = extrair_sql(sql_bruto)
                sql_validado = validar_sql(sql_limpo)
                sql_final = aplicar_correcoes_finais(sql_validado)
                
                st.code(sql_final, language="sql")
                
                res = supabase_client.rpc("execute_sql", {"query": sql_final}).execute()
                
                if res.data:
                    df = pd.DataFrame(res.data)
                    
                    # Lógica de Pivot Table Automática para pedidos de "por situação"
                    if 'orgao' in df.columns and 'situacao_padronizada' in df.columns:
                        val_col = [c for c in df.columns if c not in ['orgao', 'situacao_padronizada']][0]
                        df_pivot = df.pivot_table(index='orgao', columns='situacao_padronizada', values=val_col, aggfunc='sum', fill_value=0)
                        df_pivot['TOTAL GERAL'] = df_pivot.sum(axis=1)
                        st.write("### Resumo Consolidado")
                        st.dataframe(df_pivot)
                        st.session_state.chat_history.append({"role": "assistant", "content": "Aqui está o resumo consolidado:", "data": df_pivot})
                    else:
                        st.write("### Resultados da Consulta")
                        st.dataframe(df)
                        st.session_state.chat_history.append({"role": "assistant", "content": "Aqui estão os dados encontrados:", "data": df})
                else:
                    st.warning("Nenhum dado encontrado para esta consulta.")
                    st.session_state.chat_history.append({"role": "assistant", "content": "Nenhum dado encontrado."})
                    
        except Exception as e:
            st.error(f"Erro no processamento: {e}")
            st.session_state.chat_history.append({"role": "assistant", "content": f"Erro: {e}"})

