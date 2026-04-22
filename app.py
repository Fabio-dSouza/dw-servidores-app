import streamlit as st
from supabase import create_client
from groq import Groq
import pandas as pd
import re

# --- 1. Configuração Inicial --- #

# Carrega as chaves secretas do Streamlit
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

# Inicializa clientes Supabase e Groq
supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

# Define a tabela principal para consulta
TABELA_CONSULTA = "dw.view_completa_limpa"

# Colunas permitidas para consulta
COLUNAS_PERMITIDAS = "tipo_orgao, orgao, cargo, categoria, vinculo, situacao"

# --- 2. Funções de Geração e Validação de SQL --- #

def gerar_prompt_sql(pergunta: str) -> str:
    """
    Gera o prompt completo para a IA, incluindo regras e exemplos para a criação de SQL.
    """
    prompt = f"""
Você é um especialista em PostgreSQL e sua tarefa é gerar queries SQL.

Com base na pergunta do usuário, gere uma query SQL para a tabela `{TABELA_CONSULTA}`.

COLUNAS PERMITIDAS PARA FILTRO E SELEÇÃO:
{COLUNAS_PERMITIDAS}

REGRAS OBRIGATÓRIAS PARA A GERAÇÃO DO SQL:
- Retorne SOMENTE UMA LINHA com a query SQL. NÃO inclua texto explicativo antes ou depois.
- NÃO use quebras de linha dentro da query SQL.
- NÃO escreva "resposta:", "query:", ou qualquer outra explicação.
- A query DEVE ser um comando SELECT.
- NUNCA use INSERT, UPDATE, DELETE, DROP, ALTER ou qualquer outro comando que modifique o banco de dados.
- NUNCA invente colunas que não estejam listadas em COLUNAS PERMITIDAS.
- Para contagens, utilize COUNT(*).

REGRAS CRÍTICAS E CONTEXTO DA BASE DE DADOS:
- Todos os dados são extraídos do sistema RHE (Sistema de Recursos Humanos do estado do Rio Grande do Sul) e pertencem ao PODER EXECUTIVO DO RS.
- Para "administração direta" ou "adm direta", o filtro correto para `tipo_orgao` é `tipo_orgao ILIKE '%DIRETA%'`.
- A coluna `orgao` refere-se ao local de exercício do servidor (geralmente uma secretaria, mas pode ser um órgão específico).
- Se a pergunta for incompleta ou ambígua, NÃO gere SQL. Responda APENAS: "PERGUNTA_INSUFICIENTE".
- Utilize os filtros solicitados pelo prompt do usuário.
- Cada linha da tabela representa um registro de servidor, com vários campos passíveis de filtro.
- Se o usuário solicitar quantidades ou números, priorize uma contagem de linhas com os filtros solicitados.

REGRAS PARA FILTROS TEXTUAIS:
- Para `situacao`, use correspondência exata (ex: `situacao ILIKE 'ATIVO'` ou `situacao ILIKE 'INATIVO'`).
- Para `orgao`, `cargo`, `categoria`, use `ILIKE '%VALOR%'` (ex: `orgao ILIKE '%EDUCACAO%'`, `cargo ILIKE '%APPGG%'`, `categoria ILIKE '%MAGISTERIO%'`).
- NUNCA use "=" para filtros textuais.
- NUNCA inclua ponto e vírgula (`;`) no final da query SQL.

REGRAS DA TABELA:
- `Tipo_órgão`: Classificação do órgão, aceita apenas "ADMINISTRACAO DIRETA", "AUTARQUIA", "FUNDAÇÃO".
  - "ADMINISTRAÇÃO DIRETA" pode ser referenciado como "ADM. DIRETA", "admi. direta", "direta".
  - "ADMINISTRAÇÃO INDIRETA" ou "INDIRETA" agrupa "AUTARQUIA" e "FUNDAÇÃO".
- `vinculo`: Tipo de contrato do servidor.
- `categoria`: Valor agregado do cargo. Uma categoria pode ter vários cargos, mas um cargo pertence a apenas uma categoria.

EXEMPLOS:
PERGUNTA: Quantos servidores ativos existem na Administração Direta?
QUERY: SELECT COUNT(*) FROM dw.view_completa WHERE situacao ILIKE 'ATIVO' AND tipo_orgao ILIKE '%DIRETA%'

PERGUNTA: quantos servidores ativos que possuem o cargo APPGG?
QUERY: SELECT COUNT(*) FROM dw.view_completa WHERE situacao ILIKE 'ATIVO' AND tipo_orgao ILIKE '%DIRETA%' AND cargo ILIKE '%APPGG%'

Pergunta do Usuário: {pergunta}
"""
    return prompt

def gerar_sql_ia(pergunta: str) -> str:
    """
    Envia a pergunta do usuário para a IA e retorna a query SQL gerada.
    Lida com a resposta 'PERGUNTA_INSUFICIENTE'.
    """
    prompt_completo = gerar_prompt_sql(pergunta)
    
    try:
        resposta_ia = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "user", "content": prompt_completo}
            ]
        )
        conteudo = resposta_ia.choices[0].message.content.strip()

        st.write("ðŸ§  RESPOSTA BRUTA IA:", conteudo)

        if "PERGUNTA_INSUFICIENTE" in conteudo.upper():
            raise ValueError("Pergunta incompleta. Por favor, seja mais específico.")
        
        return conteudo

    except Exception as e:
        st.error(f"Erro ao gerar SQL pela IA: {e}")
        raise

def extrair_sql(conteudo_ia: str) -> str:
    """
    Extrai a query SQL de uma string, removendo markdown e garantindo que seja um SELECT.
    """
    # Remove blocos de código markdown (```sql, ```)
    conteudo_limpo = re.sub(r"```(?:sql)?\s*([\s\S]*?)\s*```", r"\1", conteudo_ia, flags=re.IGNORECASE).strip()
    
    # Tenta encontrar um SELECT que termine com ;
    match = re.search(r"(SELECT[\s\S]*?)(?:;|$)", conteudo_limpo, re.IGNORECASE)

    if match:
        sql = match.group(1).strip()
    else:
        raise ValueError(f"Nenhum comando SELECT válido encontrado na resposta da IA: {conteudo_ia}")
    
    # Remove qualquer ponto e vírgula remanescente no final
    if sql.endswith(';'):
        sql = sql[:-1].strip()

    return sql

def validar_sql(sql: str) -> str:
    """
    Valida a query SQL para garantir que não contenha comandos proibidos e comece com SELECT.
    """
    sql_upper = sql.upper()
    
    comandos_proibidos = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE"]
    for comando in comandos_proibidos:
        if comando in sql_upper:
            raise ValueError(f"Comando SQL não permitido detectado: {comando}")
            
    if not sql_upper.startswith("SELECT"):
        raise ValueError("Apenas comandos SELECT são permitidos.")
        
    return sql

def corrigir_group_by(sql: str) -> str:
    """
    Adiciona GROUP BY se houver COUNT(*) e outras colunas no SELECT sem GROUP BY.
    """
    sql_upper = sql.upper()

    if "COUNT(" in sql_upper and "GROUP BY" not in sql_upper:
        match_select = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE)
        if not match_select: 
            return sql

        select_part = match_select.group(1)
        colunas = [c.strip() for c in select_part.split(",")]
        
        colunas_sem_agregacao = [
            c for c in colunas 
            if not re.search(r"COUNT\(|SUM\(|AVG\(|MIN\(|MAX\(", c, re.IGNORECASE)
        ]

        if colunas_sem_agregacao:
            group_by_clause = ", ".join(colunas_sem_agregacao)
            # Encontra a posição do FROM para inserir o GROUP BY antes de ORDER BY ou LIMIT, se existirem
            from_match = re.search(r"FROM\s+\S+\s*(.*)", sql, re.IGNORECASE)
            if from_match:
                rest_of_query = from_match.group(1)
                # Verifica se já existe ORDER BY ou LIMIT
                order_by_match = re.search(r"ORDER BY", rest_of_query, re.IGNORECASE)
                limit_match = re.search(r"LIMIT", rest_of_query, re.IGNORECASE)

                if order_by_match:
                    insert_pos = sql.upper().find("ORDER BY")
                    return sql[:insert_pos] + f" GROUP BY {group_by_clause} " + sql[insert_pos:]
                elif limit_match:
                    insert_pos = sql.upper().find("LIMIT")
                    return sql[:insert_pos] + f" GROUP BY {group_by_clause} " + sql[insert_pos:]
                else:
                    return sql + f" GROUP BY {group_by_clause}"
            else:
                return sql + f" GROUP BY {group_by_clause}"

    return sql

def corrigir_ilike(sql: str) -> str:
    """
    Corrige padrões ILIKE inválidos como 'ATIVO'% para '%ATIVO%'.
    """
    # Padrão para encontrar ILIKE 'valor'% ou ILIKE 'valor'
    pattern = r"ILIKE\s+\'([^\']+)\'(%?)"
    
    def replace_ilike(match):
        value = match.group(1)
        # Se o valor já contém %, não adiciona novamente
        if '%' in value:
            return f"ILIKE '{value}'"
        return f"ILIKE '%{value}%'"

    sql_corrigido = re.sub(pattern, replace_ilike, sql, flags=re.IGNORECASE)
    return sql_corrigido

# --- 3. Funções de Execução de SQL --- #

def executar_sql_supabase(sql: str):
    """
    Executa a query SQL no Supabase e retorna os resultados.
    Aplica validações e correções antes da execução.
    """
    if not sql:
        raise ValueError("A query SQL está vazia. Não há nada para executar.")

    # Aplica as validações e correções
    sql_validado = validar_sql(sql)
    sql_corrigido_group_by = corrigir_group_by(sql_validado)
    sql_final = corrigir_ilike(sql_corrigido_group_by)

    st.info(f"ðŸ› ï¸ SQL FINAL EXECUTADO: `{sql_final}`")

    try:
        # Supabase RPC para executar SQL (assumindo que 'execute_sql' é uma função pg no Supabase)
        # ATENÇÃO: Esta abordagem assume que 'execute_sql' é uma função segura no seu banco de dados
        # que filtra ou sanitiza a entrada. Para maior segurança, considere usar parâmetros de consulta
        # ou construir a query de forma mais controlada se o Supabase permitir.
        res = supabase_client.rpc("execute_sql", {"query": sql_final}).execute()
        
        if res.data is None:
            return "Nenhum resultado encontrado ou a função retornou nulo."

        # Se for uma contagem, retorna o valor diretamente
        if isinstance(res.data, list) and len(res.data) > 0 and "count" in res.data[0]:
            return res.data[0]["count"]
        
        return res.data

    except Exception as e:
        st.error(f"Erro ao executar SQL no Supabase: {e}")
        raise

# --- 4. Funções de Geração de Resposta --- #

def gerar_resposta_final(pergunta: str, resultado: any) -> str:
    """
    Gera uma resposta amigável para o usuário com base na pergunta e no resultado da consulta.
    """
    if isinstance(resultado, int):
        return f"O total de servidores é de {resultado}."
    
    if isinstance(resultado, str) and resultado == "Nenhum resultado encontrado ou a função retornou nulo.":
        return resultado

    # Se o resultado for uma lista de dicionários (dados tabulares)
    if isinstance(resultado, list) and resultado:
        # Tenta usar a IA para resumir os dados se houver muitos
        if len(resultado) > 5:
            prompt_resumo = f"""
            Com base na pergunta do usuário e nos resultados da consulta SQL, gere um resumo conciso.
            Pergunta: {pergunta}
            Resultados (primeiras 5 linhas para contexto): {resultado[:5]}
            
            Regras:
            - Responda de forma amigável e informativa.
            - NÃO mencione que você é uma IA ou que está usando SQL.
            - NÃO invente informações.
            - Se os resultados forem muitos, apenas diga que há muitos resultados e apresente os dados brutos.
            """
            try:
                resposta_ia = groq_client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "user", "content": prompt_resumo}
                    ]
                )
                return resposta_ia.choices[0].message.content.strip()
            except Exception:
                # Fallback se a IA de resumo falhar
                return f"Foram encontrados {len(resultado)} registros. Veja os dados brutos abaixo."
        else:
            # Para poucos resultados, pode-se listar ou apenas apresentar a tabela
            return "Aqui estão os resultados encontrados:"

    return "Não foi possível gerar uma resposta textual para o resultado. Veja os dados brutos abaixo."

# --- 5. Interface do Usuário (Streamlit) --- #

st.set_page_config(page_title="Consulta Inteligente RH-RS", page_icon="ðŸ“Š", layout="wide")
st.title("ðŸ“Š Consulta Inteligente RH-RS")
st.markdown("Uma ferramenta para consultar dados do sistema RHE via linguagem natural.")

# Inicializa o histórico do chat na sessão do Streamlit
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Campo de entrada para a pergunta do usuário
pergunta_usuario = st.chat_input("Ex: quantos servidores ativos na administração direta?")

if pergunta_usuario:
    # Adiciona a pergunta do usuário ao histórico
    st.session_state.chat_history.append({"role": "user", "content": pergunta_usuario})
    
    with st.spinner("Processando sua consulta..."):
        try:
            # 1. Gerar SQL pela IA
            sql_gerado_ia = gerar_sql_ia(pergunta_usuario)
            
            # Permite ao usuário editar o SQL gerado
            sql_editavel = st.text_area(
                "âœï¸ SQL Gerado (edite se necessário):",
                value=sql_gerado_ia,
                height=150,
                key=f"sql_editor_{len(st.session_state.chat_history)}"
            )

            # 2. Executar SQL
            resultado_execucao = executar_sql_supabase(sql_editavel)
            
            st.write("ðŸ“Š Resultado Bruto da Consulta:", resultado_execucao)

            # 3. Gerar resposta final
            resposta_final = gerar_resposta_final(pergunta_usuario, resultado_execucao)
            
            # Adiciona a resposta do assistente ao histórico
            msg_assistente = {"role": "assistant", "content": resposta_final}
            if isinstance(resultado_execucao, list) and resultado_execucao and not isinstance(resultado_execucao, str):
                msg_assistente["data"] = pd.DataFrame(resultado_execucao)
            st.session_state.chat_history.append(msg_assistente)

        except ValueError as ve:
            st.error(f"Erro na validação: {ve}")
            st.session_state.chat_history.append({"role": "assistant", "content": f"Erro: {ve}"})
        except Exception as e:
            st.error(f"Ocorreu um erro inesperado: {e}")
            st.session_state.chat_history.append({"role": "assistant", "content": f"Ocorreu um erro inesperado ao processar sua solicitação. Por favor, tente novamente ou reformule a pergunta. Detalhes: {e}"})

# Exibe o histórico do chat
for mensagem in st.session_state.chat_history:
    with st.chat_message(mensagem["role"]):
        st.write(mensagem["content"])
        if "data" in mensagem:
            st.dataframe(mensagem["data"])"])))
