import streamlit as st
import pandas as pd
import numpy as np
import gspread
import re
import unicodedata
from datetime import datetime
import time
from streamlit_cookies_manager import EncryptedCookieManager
import plotly.express as px  
import json

st.set_page_config(page_title="Gestão de Rotas", page_icon="🗺️", layout="wide")

# ==========================================
# GERENCIADOR DE COOKIES
# ==========================================
cookies = EncryptedCookieManager(
    prefix="gestao_rotas_",
    password="senha_super_secreta_e_segura_123"
)

if not cookies.ready():
    st.stop()

# ==========================================
# ESTADOS DE MEMÓRIA (SESSION STATE)
# ==========================================
if "os_aberta" not in st.session_state:
    st.session_state.os_aberta = None

if "refresh_counter" not in st.session_state:
    st.session_state.refresh_counter = 0

# ==========================================
# AJUSTE DE LAYOUT E TABELAS
# ==========================================
st.markdown("""
    <style>
    .block-container { padding-top: 2rem !important; }
    [data-testid="stSidebarHeader"] { padding-top: 0.5rem !important; padding-bottom: 0rem !important; min-height: 0px !important; }
    [data-testid="stSidebarContent"] { padding-top: 0rem !important; padding-bottom: 4rem !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# CONTROLE DE ACESSO
# ==========================================
if cookies.get("admin_logado") == "True":
    st.session_state.admin_logado = True
    st.session_state.admin_user = cookies.get("admin_user", "")
else:
    st.session_state.admin_logado = False
    st.session_state.admin_user = ""

# ==========================================
# CONSTANTES
# ==========================================
COL_DATA = "Carimbo de data/hora" 
COL_MATRICULA = "Informe a Matrícula do Imóvel"
COL_CIDADE = "Informe cidade do Serviço"
COL_BAIRRO = "Informe o BAIRRO de Campina Grande"
COL_SERVICO = "Qual o Serviço ?"
COL_CONCLUSAO = "Conclusão"

# ==========================================
# FUNÇÕES DE DADOS
# ==========================================
def obter_conexao():
    try:
        # Lê as credenciais de forma segura direto do Cofre do Streamlit
        credenciais = json.loads(st.secrets["google_credentials"])
        # CORREÇÃO MÁGICA: Conserta as quebras de linha da chave privada que o Streamlit bagunça
        if "\\n" in credenciais["private_key"]:
            credenciais["private_key"] = credenciais["private_key"].replace("\\n", "\n")
        return gspread.service_account_from_dict(credenciais)
    except Exception as e:
        st.error(f"Erro ao conectar com o Google: {e}")
        st.stop()

def extrair_bairro_inteligente(row):
    bairro_form = str(row.get(COL_BAIRRO, "")).strip()
    if bairro_form and bairro_form.lower() not in ['nan', 'none', '']: return bairro_form.upper()
    endereco = str(row.get('Endereço', '')).upper().strip()
    cidade = str(row.get(COL_CIDADE, '')).upper().strip()
    def remover_acentos(txt):
        return ''.join(c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn')
    cidade_norm = remover_acentos(cidade)
    if endereco and endereco != 'NAN' and endereco != 'ENDEREÇO NÃO ENCONTRADO':
        texto_limpo = re.sub(r'\s*PB\s*\d{5}-?\d{3}\s*$', '', endereco)
        texto_limpo = re.sub(r'\s*PB\s*$', '', texto_limpo)
        endereco_norm = remover_acentos(texto_limpo)
        if cidade_norm and cidade_norm in endereco_norm:
            idx = endereco_norm.rfind(cidade_norm)
            parte_antes_cidade = texto_limpo[:idx].strip()
            partes = parte_antes_cidade.split('-')
            bairro_extraido = partes[-1].strip()
            if bairro_extraido: return bairro_extraido.upper()
        partes = texto_limpo.split('-')
        if len(partes) > 1: return partes[-1].replace(cidade, "").strip().upper()
    return "BAIRRO NÃO IDENTIFICADO"

def formatar_status_visual(s):
    s = str(s).upper()
    if "EXECUTAD" in s or "FIZ O SERVICO" in s: return "🟢 EXECUTADO"
    if "DEVOLVID" in s: return "🔴 DEVOLVIDO"
    if "ANDAMENTO" in s: return "🔵 EM ANDAMENTO"
    if "PENDENTE" in s or s.strip() == "": return "🟡 PENDENTE"
    return f"⚪ {s}"

def classificar_status_puro(s):
    s = str(s).upper()
    if "EXECUTAD" in s or "FIZ O SERVICO" in s: return "EXECUTADA"
    if "DEVOLVID" in s: return "DEVOLVIDA"
    if "ANDAMENTO" in s: return "EM ANDAMENTO"
    return "PENDENTE"

@st.cache_data(ttl=60) 
def carregar_dados():
    try:
        client = obter_conexao()
        aba_coords = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("PARAMETROS_MATRICULA")
        df_coords = pd.DataFrame(aba_coords.get_all_records())
        df_coords.columns = df_coords.columns.str.strip()
        df_coords = df_coords.loc[:, ~df_coords.columns.duplicated()]
        df_coords['Matrícula'] = df_coords['Matrícula'].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        df_coords = df_coords.drop_duplicates(subset=['Matrícula'], keep='last')
        
        aba_respostas = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("Respostas ao formulário 1")
        df_respostas = pd.DataFrame(aba_respostas.get_all_records())
        df_respostas.columns = df_respostas.columns.str.strip()
        
        df_respostas = df_respostas.loc[:, ~df_respostas.columns.duplicated()]
        
        df_respostas['Linha_Planilha'] = df_respostas.index + 2
        df_respostas['OS'] = "OS-" + df_respostas['Linha_Planilha'].astype(str)
        
        if "Operador Atribuído" not in df_respostas.columns: df_respostas["Operador Atribuído"] = ""
        if "Data Programada" not in df_respostas.columns: df_respostas["Data Programada"] = ""
        if "Fotos" not in df_respostas.columns: df_respostas["Fotos"] = "" 
        
        df_respostas[COL_MATRICULA] = df_respostas[COL_MATRICULA].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        df_respostas[COL_CONCLUSAO] = df_respostas[COL_CONCLUSAO].astype(str).str.strip().str.upper()

        df_respostas['Operador Atribuído'] = df_respostas['Operador Atribuído'].astype(str).replace(r'^\s*$', np.nan, regex=True).replace('None', np.nan).replace('nan', np.nan)
        df_respostas['Data Programada'] = df_respostas['Data Programada'].astype(str).replace(r'^\s*$', np.nan, regex=True).replace('None', np.nan).replace('nan', np.nan)
        df_respostas['Fotos'] = df_respostas['Fotos'].astype(str).replace(r'^\s*$', np.nan, regex=True).replace('None', np.nan).replace('nan', np.nan)
        
        df_respostas['Operador Atribuído'] = df_respostas.groupby(COL_MATRICULA)['Operador Atribuído'].ffill().fillna("")
        df_respostas['Data Programada'] = df_respostas.groupby(COL_MATRICULA)['Data Programada'].ffill().fillna("")
        df_respostas['Fotos'] = df_respostas.groupby(COL_MATRICULA)['Fotos'].ffill().fillna("")
        
        df_respostas['Operador Atribuído'] = df_respostas['Operador Atribuído'].replace('-', '')
        df_respostas['Data Programada'] = df_respostas['Data Programada'].replace('-', '')

        # =========================================================================
        # INÍCIO DO "GUARDIÃO DA MEIA-NOITE": LIMPEZA AUTOMÁTICA DE ORDENS VENCIDAS
        # =========================================================================
        df_respostas['Data_Prog_Date'] = pd.to_datetime(df_respostas['Data Programada'], format='%d/%m/%Y', errors='coerce')
        hoje_date = pd.Timestamp(datetime.now().date())
        
        is_pendente = ~df_respostas[COL_CONCLUSAO].str.contains("EXECUTAD|DEVOLVID", na=False)
        is_anterior = df_respostas['Data_Prog_Date'] < hoje_date
        has_operador = (df_respostas['Operador Atribuído'] != "") & (df_respostas['Operador Atribuído'] != "-")
        
        vencidas = df_respostas[is_pendente & is_anterior & has_operador]
        
        if not vencidas.empty:
            header_upper = [str(h).strip().upper() for h in aba_respostas.row_values(1)]
            col_op = header_upper.index("OPERADOR ATRIBUÍDO") + 1 if "OPERADOR ATRIBUÍDO" in header_upper else None
            col_dt = header_upper.index("DATA PROGRAMADA") + 1 if "DATA PROGRAMADA" in header_upper else None
            col_conc = None
            if "CONCLUSÃO" in header_upper: col_conc = header_upper.index("CONCLUSÃO") + 1
            elif "CONCLUSAO" in header_upper: col_conc = header_upper.index("CONCLUSAO") + 1
            
            celulas = []
            for idx, row in vencidas.iterrows():
                linha = int(row['Linha_Planilha'])
                if col_op: celulas.append(gspread.Cell(row=linha, col=col_op, value="-"))
                if col_dt: celulas.append(gspread.Cell(row=linha, col=col_dt, value="-"))
                # Deixa a conclusão em branco (Silencioso)
                if col_conc: celulas.append(gspread.Cell(row=linha, col=col_conc, value=""))
                
                df_respostas.at[idx, 'Operador Atribuído'] = "-"
                df_respostas.at[idx, 'Data Programada'] = "-"
                df_respostas.at[idx, COL_CONCLUSAO] = ""
                
            if celulas:
                aba_respostas.update_cells(celulas)
        # =========================================================================
        
        # Lê os eventos da nova aba separada para o Dashboard
        try:
            aba_status = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("STATUS_OPERADORES")
            df_eventos = pd.DataFrame(aba_status.get_all_records())
            # Renomeamos as colunas em memória para não quebrar o layout
            if not df_eventos.empty:
                df_eventos = df_eventos.rename(columns={
                    "Operador": "Operador Atribuído", 
                    "Evento": "Conclusão", 
                    "Data Referencia": "Data Programada"
                })
        except:
            df_eventos = pd.DataFrame(columns=["Operador Atribuído", "Conclusão", "Data Programada"])

        df_respostas = df_respostas[df_respostas[COL_MATRICULA] != "ROTEIRO_SISTEMA"] # Limpeza por segurança de registros antigos
        df_respostas = df_respostas[df_respostas[COL_MATRICULA] != ""]
        
        df_respostas = df_respostas.drop_duplicates(subset=[COL_MATRICULA], keep='last')
        df_respostas[COL_SERVICO] = df_respostas[COL_SERVICO].astype(str).str.strip().str.upper()
        
        df_validas = df_respostas[~df_respostas[COL_CONCLUSAO].str.contains("GERADO", na=False)]
        df_validas = df_validas[df_validas[COL_SERVICO].str.contains("PAREDE|INSTALA|ASSENTAMENTO|TAMPA", regex=True, na=False)]
        df_validas[COL_CIDADE] = df_validas[COL_CIDADE].fillna("NÃO INFORMADA").astype(str).str.strip().str.upper()
        df_validas[COL_BAIRRO] = df_validas[COL_BAIRRO].fillna("").astype(str).str.strip().str.upper()
        df_validas[COL_DATA] = df_validas[COL_DATA].astype(str).str.split(' ').str[0]
        
        df_completo = pd.merge(df_validas, df_coords, left_on=COL_MATRICULA, right_on='Matrícula', how='inner')
        if 'Endereço' not in df_completo.columns: df_completo['Endereço'] = "Endereço não encontrado"
        df_completo[COL_BAIRRO] = df_completo.apply(extrair_bairro_inteligente, axis=1)
        
        def encurtar_endereco(row):
            end = str(row.get('Endereço', '')).upper()
            bairro = str(row.get(COL_BAIRRO, '')).upper()
            cidade = str(row.get(COL_CIDADE, '')).upper()
            
            end = re.sub(r'\s*PB\s*\d{5}-?\d{3}\s*$', '', end)
            end = re.sub(r'\s*PB\s*$', '', end)
            
            if cidade and end.endswith(cidade):
                end = end[:-len(cidade)].strip()
            end = re.sub(r'[-\s]+$', '', end)
            
            if bairro and end.endswith(bairro):
                end = end[:-len(bairro)].strip()
            end = re.sub(r'[-\s]+$', '', end)
            
            return end

        df_completo['Endereço'] = df_completo.apply(encurtar_endereco, axis=1)
        
        return df_completo, df_eventos
    except Exception as e:
        st.error(f"Erro ao cruzar os dados: {e}")
        return pd.DataFrame(), pd.DataFrame()

def limpar_coordenadas(valor, tipo):
    try:
        texto = str(valor).replace(".", "").replace(",", "").strip()
        if not texto or texto in ["ERRO", "Sem X", "Sem Y", ""]: return None
        sinal = -1 if texto.startswith('-') else 1
        nums = texto.replace('-', '')
        if not nums.isdigit(): return None
        if tipo == 'lat': return sinal * float(nums[0] + "." + nums[1:])
        elif tipo == 'lon': return sinal * float(nums[:2] + "." + nums[2:])
    except: return None

def mover_para_pasta(df_alvo, nome_operador, data_programada=""):
    client = obter_conexao()
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    aba = planilha.worksheet("Respostas ao formulário 1")
    header = [str(h).strip() for h in aba.row_values(1)]
    header_upper = [h.upper() for h in header]
    
    if "OPERADOR ATRIBUÍDO" not in header_upper:
        col_idx_op = len(header) + 1
        aba.update_cell(1, col_idx_op, "Operador Atribuído")
        header.append("Operador Atribuído")
        header_upper.append("OPERADOR ATRIBUÍDO")
    else: col_idx_op = header_upper.index("OPERADOR ATRIBUÍDO") + 1
    
    if "DATA PROGRAMADA" not in header_upper:
        col_idx_data = len(header) + 1
        aba.update_cell(1, col_idx_data, "Data Programada")
        header.append("Data Programada")
        header_upper.append("DATA PROGRAMADA")
    else: col_idx_data = header_upper.index("DATA PROGRAMADA") + 1
    
    if "CONCLUSÃO" in header_upper:
        col_idx_conc = header_upper.index("CONCLUSÃO") + 1
    elif "CONCLUSAO" in header_upper:
        col_idx_conc = header_upper.index("CONCLUSAO") + 1
    else:
        col_idx_conc = None
    
    val_op = nome_operador if nome_operador != "" else "-"
    val_dt = data_programada if data_programada != "" else "-"

    celulas = []
    for linha in df_alvo['Linha_Planilha']:
        celulas.append(gspread.Cell(row=int(linha), col=col_idx_op, value=val_op))
        celulas.append(gspread.Cell(row=int(linha), col=col_idx_data, value=val_dt))
        if col_idx_conc:
            celulas.append(gspread.Cell(row=int(linha), col=col_idx_conc, value="")) 
    if celulas: aba.update_cells(celulas)
    st.cache_data.clear() 

# ==========================================
# INTERFACE E LOGIN
# ==========================================
banco_senhas_admin = {"Tiago": "883237", "Gabriel": "123456"}

if not st.session_state.admin_logado:
    st.markdown("<br><br><br>", unsafe_allow_html=True) 
    col1, col2, col3 = st.columns([1, 1, 1]) 
    with col2:
        st.markdown("<h2 style='text-align: center; color: #1E88E5;'>🔐 Acesso Restrito</h2>", unsafe_allow_html=True)
        with st.form(key="form_login_admin"):
            admin_selecionado = st.selectbox("👤 Programador:", options=["Tiago", "Gabriel"], index=None, placeholder="Escolha o programador")
            senha_admin = st.text_input("🔑 Senha:", type="password")
            if st.form_submit_button("Entrar no Sistema", type="primary", use_container_width=True):
                if admin_selecionado is None: st.warning("⚠️ Selecione o programador.")
                elif senha_admin == banco_senhas_admin.get(admin_selecionado):
                    cookies["admin_logado"] = "True"
                    cookies["admin_user"] = admin_selecionado
                    cookies.save()
                    st.session_state.admin_logado = True
                    st.session_state.admin_user = admin_selecionado
                    st.rerun()
                else: st.error("❌ Senha incorreta!")

# ==========================================
# TELA PRINCIPAL
# ==========================================
if st.session_state.admin_logado:
    st.sidebar.markdown(f"👤 **Logado como:** {st.session_state.admin_user}")
    if st.sidebar.button("🔄 Atualizar Dados", use_container_width=True): 
        st.cache_data.clear()
        st.session_state.refresh_counter += 1
        st.rerun()
    if st.sidebar.button("🚪 Sair do Sistema", use_container_width=True):
        cookies["admin_logado"] = "False"; cookies["admin_user"] = ""; cookies.save()
        st.session_state.admin_logado = False; st.session_state.admin_user = ""; st.rerun()
    st.sidebar.divider()
    
    st.title("🗺️ Centro de Despacho e Rotas CTV")
    df, df_eventos = carregar_dados()

    if not df.empty:
        df['lat'] = df['Coordenada X'].apply(lambda x: limpar_coordenadas(x, 'lat'))
        df['lon'] = df['Coordenada Y'].apply(lambda y: limpar_coordenadas(y, 'lon'))
        df = df.dropna(subset=['lat', 'lon'])
        
        opcoes_menu = ["📥 Caixa de Entrada", "📂 Pastas dos Operadores", "📊 Dashboard e Relatórios"]
        
        if "aba_ativa_real" not in st.session_state:
            aba_salva = cookies.get("aba_salva", "📥 Caixa de Entrada")
            if aba_salva not in opcoes_menu:
                aba_salva = "📥 Caixa de Entrada"
            st.session_state.aba_ativa_real = aba_salva
            
        idx_aba = opcoes_menu.index(st.session_state.aba_ativa_real)

        aba_selecionada = st.radio(
            "Visualização Atual:",
            options=opcoes_menu,
            horizontal=True,
            index=idx_aba
        )
        
        if aba_selecionada != st.session_state.aba_ativa_real:
            st.session_state.aba_ativa_real = aba_selecionada
            cookies["aba_salva"] = aba_selecionada
            cookies.save()
            
        st.write("---")

        config_colunas_layout = {
            "✔️": st.column_config.CheckboxColumn("Sel.", width=40),
            COL_DATA: st.column_config.TextColumn("Data", width=80),
            COL_MATRICULA: st.column_config.TextColumn("Matrícula", width=80),
            "Local": st.column_config.TextColumn("📍 Local (Bairro/Cidade)", width=190),
            "Endereço": st.column_config.TextColumn("Endereço", width=None),
            COL_SERVICO: st.column_config.TextColumn("Serviço", width=90),
            "Status_Visual": st.column_config.TextColumn("Status", width=130),
            "Fotos": st.column_config.LinkColumn("📸", display_text="Abrir", width=50) 
        }

        # ---------------------------------------------------------
        # ABA 1: CAIXA DE ENTRADA
        # ---------------------------------------------------------
        if aba_selecionada == "📥 Caixa de Entrada":
            is_unassigned = df["Operador Atribuído"] == ""
            is_devolved = df["Conclusão"].str.contains("DEVOLVID", na=False)
            is_dash = df["Operador Atribuído"] == "-"
            is_not_executed = ~df["Conclusão"].str.contains("EXECUTAD", na=False)
            
            df_caixa = df[(is_unassigned | is_devolved | is_dash) & is_not_executed].copy()
            
            if not df_caixa.empty:
                df_caixa['Status_Visual'] = df_caixa[COL_CONCLUSAO].apply(formatar_status_visual)
                df_caixa['Local'] = df_caixa[COL_BAIRRO] + " / " + df_caixa[COL_CIDADE]
            
            st.sidebar.header("🔍 Filtros: Caixa de Entrada")
            lista_cidades = sorted(df_caixa[COL_CIDADE].unique().tolist()) if not df_caixa.empty else []
            
            cidade_selecionada = st.sidebar.selectbox("Cidade:", ["Todas as Cidades"] + lista_cidades, key="cx_cidade")
            if cidade_selecionada != "Todas as Cidades": df_caixa = df_caixa[df_caixa[COL_CIDADE] == cidade_selecionada]
            
            lista_bairros = sorted([b for b in df_caixa[COL_BAIRRO].unique().tolist() if b.strip() != ""]) if not df_caixa.empty else []
            bairro_selecionado = "Todos os Bairros"
            if lista_bairros:
                bairro_selecionado = st.sidebar.selectbox("Bairro:", ["Todos os Bairros"] + lista_bairros, key="cx_bairro")
                if bairro_selecionado != "Todos os Bairros": df_caixa = df_caixa[df_caixa[COL_BAIRRO] == bairro_selecionado]
            
            container_despacho = st.container()
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1: st.subheader("Pendentes Globais")
            with col2: operador_destino = st.selectbox("👷 Enviar Para:", ["Julio Cesar", "Joseilton", "Alberth"], key="op_destino_cx")
            with col3: data_formatada = st.date_input("📅 Data:", format="DD/MM/YYYY", key="data_dest_cx").strftime("%d/%m/%Y")

            if not df_caixa.empty:
                marcar_todos = st.checkbox("☑️ Selecionar todos", key="chk_todos_cx")
                df_caixa.insert(0, "✔️", marcar_todos)
                
                colunas_caixa_exibicao = ['✔️', COL_DATA, COL_MATRICULA, 'Local', 'Endereço', COL_SERVICO, 'Status_Visual', 'Fotos']
                colunas_caixa_exibicao = [c for c in colunas_caixa_exibicao if c in df_caixa.columns]

                df_editado_caixa = st.data_editor(
                    df_caixa[colunas_caixa_exibicao],
                    use_container_width=True, hide_index=True, 
                    height=min(len(df_caixa) * 35 + 50, 450),
                    disabled=[COL_DATA, COL_MATRICULA, "Local", "Endereço", COL_SERVICO, "Status_Visual", "Fotos"],
                    column_config=config_colunas_layout,
                    key="editor_caixa"
                )
                
                idx_selecionados_cx = df_editado_caixa[df_editado_caixa["✔️"] == True].index
                df_selecionado_completo_cx = df_caixa.loc[idx_selecionados_cx]
                
                with container_despacho:
                    if st.button(f"🚀 Despachar {len(df_selecionado_completo_cx)} ordens", type="primary", key="btn_despachar_cx"):
                        if not df_selecionado_completo_cx.empty:
                            mover_para_pasta(df_selecionado_completo_cx, operador_destino, data_formatada)
                            st.rerun()
                        else:
                            st.warning("Selecione ordens antes de despachar.")
                
                st.map(df_caixa[['lat', 'lon']].dropna())
            else:
                st.info("A Caixa de Entrada está vazia.")

        # ---------------------------------------------------------
        # ABA 2: PASTAS DOS OPERADORES 
        # ---------------------------------------------------------
        elif aba_selecionada == "📂 Pastas dos Operadores":
            st.markdown("### 🗂️ Visão Geral das Equipes")
            
            ops_com_os = set(df["Operador Atribuído"].unique())
            ops_com_eventos = set(df_eventos["Operador Atribuído"].unique())
            operadores = sorted(list(ops_com_os.union(ops_com_eventos)))
            operadores = [op for op in operadores if str(op).strip() not in ["", "-"]]
            
            if not operadores:
                st.info("Nenhum operador possui histórico de ordens no momento.")
            else:
                data_hoje = datetime.now().strftime("%d/%m/%Y")
                todas_datas = sorted(list(set(df["Data Programada"].unique()).union(set(df_eventos["Data Programada"].unique()))))
                todas_datas = [str(d).strip() for d in todas_datas if str(d).strip() != ""]
                
                if data_hoje not in todas_datas:
                    todas_datas.append(data_hoje)
                    todas_datas = sorted(todas_datas)
                
                opcoes_data = ["Todas"] + todas_datas
                idx_padrao = opcoes_data.index(data_hoje) if data_hoje in opcoes_data else 0
                
                col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
                with col_f3:
                    data_global = st.selectbox("📅 Filtrar Data (Todas as Equipes):", opcoes_data, index=idx_padrao, key="filtro_data_global")
                
                st.write("") 
                
                for op in operadores:
                    df_pasta = df[df["Operador Atribuído"].astype(str).str.strip() == str(op).strip()].copy()
                    eventos_op = df_eventos[df_eventos['Operador Atribuído'].astype(str).str.strip() == str(op).strip()].copy()
                    
                    if data_global != "Todas":
                        df_pasta = df_pasta[df_pasta["Data Programada"] == data_global]
                        eventos_op = eventos_op[eventos_op['Data Programada'] == data_global]
                        
                    if df_pasta.empty and eventos_op.empty:
                        continue 
                    
                    if not df_pasta.empty:
                        df_pasta['Status_Visual'] = df_pasta[COL_CONCLUSAO].apply(formatar_status_visual)
                        df_pasta['Local'] = df_pasta[COL_BAIRRO] + " / " + df_pasta[COL_CIDADE]
                        
                    qtd_total_pasta = len(df_pasta)
                    qtd_executadas = len(df_pasta[df_pasta[COL_CONCLUSAO].str.contains("EXECUTAD", na=False)])
                    qtd_devolvidas = len(df_pasta[df_pasta[COL_CONCLUSAO].str.contains("DEVOLVID", na=False)])
                    qtd_retornadas = qtd_executadas + qtd_devolvidas
                    
                    situacao = "AGUARDANDO INÍCIO ⏳"
                    
                    if not eventos_op.empty:
                        ultimo_evento = str(eventos_op.iloc[-1]['Conclusão']).strip().upper()
                        if ultimo_evento == "INICIADO":
                            situacao = "EM CAMPO 🚧"
                        elif ultimo_evento == "FINALIZADO":
                            situacao = "FINALIZADO ✅"
                    
                    if qtd_total_pasta > 0 and qtd_retornadas == qtd_total_pasta and situacao != "FINALIZADO ✅":
                        situacao = "LIVRE (RETORNADAS) ✅"
                    
                    titulo_sanfona = f"👷 EQUIPE {op.upper()}  |  📊 {qtd_retornadas}/{qtd_total_pasta} OS Retornadas  |  Status: {situacao}"
                    
                    with st.expander(titulo_sanfona, expanded=False, key=f"exp_{op}_{st.session_state.refresh_counter}"):
                        if not df_pasta.empty:
                            marcar_todos_pasta = st.checkbox("☑️ Selecionar todos", key=f"chk_todos_{op}")
                            df_pasta.insert(0, "✔️", marcar_todos_pasta)
                            
                            colunas_pasta_alvo = ['✔️', COL_DATA, COL_MATRICULA, 'Local', 'Endereço', COL_SERVICO, 'Status_Visual', 'Fotos']
                            colunas_pasta_validas = [c for c in colunas_pasta_alvo if c in df_pasta.columns]
                            
                            df_editado_pasta = st.data_editor(
                                df_pasta[colunas_pasta_validas],
                                use_container_width=True, hide_index=True, 
                                height=min(len(df_pasta) * 35 + 50, 450),
                                disabled=[c for c in colunas_pasta_validas if c != '✔️'],
                                column_config=config_colunas_layout,
                                key=f"editor_pasta_{op}"
                            )
                            
                            idx_selecionados_pt = df_editado_pasta[df_editado_pasta["✔️"] == True].index
                            df_selecionado_completo_pt = df_pasta.loc[idx_selecionados_pt]
                            
                            if not df_selecionado_completo_pt.empty:
                                if st.button(f"↩️ Devolver {len(df_selecionado_completo_pt)} OS para a Caixa (Retirar da Pasta)", key=f"btn_dev_{op}"):
                                    
                                    os_nao_executadas = df_selecionado_completo_pt[~df_selecionado_completo_pt[COL_CONCLUSAO].str.contains("EXECUTAD")]
                                    
                                    if len(os_nao_executadas) == 0:
                                        st.error("❌ Ordens EXECUTADAS não podem ser devolvidas para a Caixa de Entrada. O Histórico foi mantido.")
                                    else:
                                        if len(os_nao_executadas) < len(df_selecionado_completo_pt):
                                            st.warning("⚠️ Atenção: Apenas ordens Pendentes/Devolvidas foram movidas. Ordens Executadas foram protegidas na pasta.")
                                        mover_para_pasta(os_nao_executadas, "", "")
                                        st.success("Ordens retiradas desta pasta e devolvidas para a Caixa de Entrada!")
                                        time.sleep(2)
                                        st.rerun()
                            
                            st.map(df_pasta[['lat', 'lon']].dropna())
                        else:
                            st.info("Nenhuma ordem na pasta neste momento. O operador já finalizou ou teve as ordens remanejadas.")
        
        # ---------------------------------------------------------
        # ABA 3: DASHBOARD E RELATÓRIOS 
        # ---------------------------------------------------------
        elif aba_selecionada == "📊 Dashboard e Relatórios":
            st.markdown("### 📈 Indicadores e Relatórios Operacionais")
            
            df_dash = df.copy()
            df_dash['Status_Geral'] = df_dash[COL_CONCLUSAO].apply(classificar_status_puro)
            
            df_dash['Data_Obj'] = pd.to_datetime(df_dash['Data Programada'], format='%d/%m/%Y', errors='coerce')
            
            col_f1, col_f2 = st.columns(2)
            
            with col_f1:
                filtro_tempo = st.selectbox(
                    "📅 Filtro Rápido de Tempo:",
                    ["Todo o Período", "Hoje", "Última Semana", "Últimos 15 Dias", "Último Mês", "Calendário Personalizado..."],
                    index=1, 
                    key="dash_filtro_tempo"
                )
                
                hoje = datetime.now().date()
                data_ini, data_fim = None, None
                
                if filtro_tempo == "Todo o Período":
                    pass 
                elif filtro_tempo == "Hoje":
                    data_ini, data_fim = hoje, hoje
                elif filtro_tempo == "Última Semana":
                    data_ini, data_fim = hoje - pd.Timedelta(days=7), hoje
                elif filtro_tempo == "Últimos 15 Dias":
                    data_ini, data_fim = hoje - pd.Timedelta(days=15), hoje
                elif filtro_tempo == "Último Mês":
                    data_ini, data_fim = hoje - pd.Timedelta(days=30), hoje
                elif filtro_tempo == "Calendário Personalizado...":
                    datas_selecionadas = st.date_input(
                        "Selecione o Período (Data Inicial e Final):",
                        value=(hoje, hoje),
                        format="DD/MM/YYYY",
                        key="dash_periodo_custom"
                    )
                    if isinstance(datas_selecionadas, tuple) and len(datas_selecionadas) == 2:
                        data_ini, data_fim = datas_selecionadas
                    elif isinstance(datas_selecionadas, tuple) and len(datas_selecionadas) == 1:
                        data_ini, data_fim = datas_selecionadas[0], datas_selecionadas[0]
                    elif isinstance(datas_selecionadas, datetime.date):
                        data_ini, data_fim = datas_selecionadas, datas_selecionadas
            
            with col_f2:
                todas_cidades = sorted([str(c).strip() for c in df_dash[COL_CIDADE].unique() if str(c).strip() != ""])
                cidade_dash = st.selectbox("🏙️ Cidade:", ["Todas as Cidades"] + todas_cidades, key="dash_cidade")
            
            if data_ini is not None and data_fim is not None:
                data_ini_ts = pd.Timestamp(data_ini)
                data_fim_ts = pd.Timestamp(data_fim)
                df_dash = df_dash[(df_dash['Data_Obj'] >= data_ini_ts) & (df_dash['Data_Obj'] <= data_fim_ts)]
                    
            if cidade_dash != "Todas as Cidades":
                df_dash = df_dash[df_dash[COL_CIDADE] == cidade_dash]
                
            st.write("---")
            
            if df_dash.empty:
                st.warning("Nenhum dado encontrado para os filtros selecionados.")
            else:
                total_os = len(df_dash)
                qtd_exec = len(df_dash[df_dash['Status_Geral'] == 'EXECUTADA'])
                qtd_dev = len(df_dash[df_dash['Status_Geral'] == 'DEVOLVIDA'])
                
                taxa_sucesso = (qtd_exec / (qtd_exec + qtd_dev)) * 100 if (qtd_exec + qtd_dev) > 0 else 0
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("📌 Total de OS", total_os)
                col2.metric("🟢 Executadas", qtd_exec)
                col3.metric("🔴 Devolvidas", qtd_dev)
                col4.metric("🏆 Taxa de Eficiência", f"{taxa_sucesso:.1f}%")
                
                st.write("---")
                
                col_g1, col_g2 = st.columns(2)
                
                with col_g1:
                    st.markdown("**Desempenho por Equipe**")
                    df_equipe = df_dash[df_dash['Operador Atribuído'].astype(str).str.strip() != '']
                    if not df_equipe.empty:
                        contagem_equipe = df_equipe.groupby(['Operador Atribuído', 'Status_Geral']).size().reset_index(name='Quantidade')
                        fig_eq = px.bar(contagem_equipe, x='Operador Atribuído', y='Quantidade', color='Status_Geral', 
                                        color_discrete_map={'EXECUTADA': '#4CAF50', 'DEVOLVIDA': '#F44336', 'PENDENTE': '#FF9800', 'EM ANDAMENTO': '#2196F3'},
                                        barmode='group')
                        fig_eq.update_layout(xaxis_title="Equipe", yaxis_title="Nº de Ordens", legend_title="Status")
                        st.plotly_chart(fig_eq, use_container_width=True)
                    else:
                        st.info("Sem dados de equipes para o período.")
                        
                with col_g2:
                    st.markdown("**Tipos de Serviço Solicitados**")
                    contagem_servico = df_dash[COL_SERVICO].value_counts().reset_index()
                    contagem_servico.columns = ['Serviço', 'Quantidade']
                    fig_serv = px.pie(contagem_servico, names='Serviço', values='Quantidade', hole=0.4)
                    st.plotly_chart(fig_serv, use_container_width=True)
                    
                st.write("---")
                
                col_g3, col_g4 = st.columns(2)
                
                with col_g3:
                    st.markdown("**Volume Geográfico (Top 10 Bairros)**")
                    df_bairro = df_dash[df_dash[COL_BAIRRO] != '']
                    if not df_bairro.empty:
                        contagem_bairro = df_bairro[COL_BAIRRO].value_counts().head(10).reset_index()
                        contagem_bairro.columns = ['Bairro', 'Quantidade']
                        fig_bairro = px.bar(contagem_bairro, x='Quantidade', y='Bairro', orientation='h', color='Quantidade', color_continuous_scale='Blues')
                        fig_bairro.update_layout(yaxis={'categoryorder':'total ascending'})
                        st.plotly_chart(fig_bairro, use_container_width=True)
                    else:
                        st.info("Sem dados de bairro.")
                        
                with col_g4:
                    st.markdown("**Gargalos: Motivos de Devolução**")
                    df_devolucoes = df_dash[df_dash['Status_Geral'] == 'DEVOLVIDA'].copy()
                    if not df_devolucoes.empty:
                        df_devolucoes['Motivo'] = df_devolucoes[COL_CONCLUSAO].apply(lambda x: str(x).replace('DEVOLVIDO:', '').strip() if 'DEVOLVIDO:' in str(x) else x)
                        contagem_motivos = df_devolucoes['Motivo'].value_counts().reset_index()
                        contagem_motivos.columns = ['Motivo Detalhado', 'Quantidade']
                        st.dataframe(contagem_motivos, use_container_width=True, hide_index=True)
                    else:
                        st.success("Nenhuma devolução registrada neste filtro! 🎉")
                        
                st.write("---")
                st.markdown("### 💾 Exportar Relatório")
                st.caption("Baixe os dados que estão na sua tela agora mesmo no formato Excel/CSV.")
                
                df_export = df_dash.drop(columns=['Data_Obj'])
                csv = df_export.to_csv(index=False, sep=';', encoding='utf-8-sig')
                st.download_button(
                    label="📥 Baixar Dados Filtrados (CSV)",
                    data=csv,
                    file_name=f"Relatorio_CTV_{datetime.now().strftime('%d_%m_%Y')}.csv",
                    mime='text/csv',
                    type="primary"
                )
