import pandas as pd
import numpy as np
import gspread
import requests
import base64
from datetime import datetime
import time
import streamlit as st
import re
import unicodedata
from streamlit_cookies_manager import EncryptedCookieManager
import json

st.set_page_config(page_title="OPERAÇÃO CTV", page_icon="📱", layout="centered")

# ==========================================
# GERENCIADOR DE COOKIES E ESTADOS
# ==========================================
cookies = EncryptedCookieManager(
    prefix="operacao_ctv_",
    password="senha_peao_super_secreta_456" 
)

if not cookies.ready():
    st.stop()

if "os_aberta" not in st.session_state:
    st.session_state.os_aberta = None

if "status_forcado" not in st.session_state:
    st.session_state.status_forcado = None

if "foto_ampliada" not in st.session_state:
    st.session_state.foto_ampliada = None

if "bairro_expandido" not in st.session_state:
    st.session_state.bairro_expandido = None

if "confirmar_fim" not in st.session_state:
    st.session_state.confirmar_fim = False

if cookies.get("autenticado") == "True":
    st.session_state.autenticado = True
    st.session_state.operador_logado = cookies.get("operador_logado", "")
else:
    st.session_state.autenticado = False
    st.session_state.operador_logado = ""

# ==========================================
# TRADUÇÃO FORÇADA DOS BOTÕES (CSS HACK)
# ==========================================
st.markdown("""
    <style>
    .block-container { padding-top: 2rem !important; }
    
    button[title="Take photo"], button[title="Take Photo"],
    button[aria-label="Take photo"], button[aria-label="Take Photo"],
    div[data-testid="stCameraInput"] button:first-of-type { 
        color: transparent !important; position: relative; 
    }
    
    button[title="Take photo"]::after, button[title="Take Photo"]::after,
    button[aria-label="Take photo"]::after, button[aria-label="Take Photo"]::after,
    div[data-testid="stCameraInput"] button:first-of-type::after { 
        content: "📸 TIRAR FOTO" !important; color: white !important; 
        position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); 
        font-size: 16px; font-weight: bold; width: 100%; display: block;
    }
    
    button[title="Clear photo"], button[title="Clear Photo"],
    button[aria-label="Clear photo"], button[aria-label="Clear Photo"],
    div[data-testid="stCameraInput"] button:nth-of-type(2) { 
        color: transparent !important; position: relative; 
    }
    
    button[title="Clear photo"]::after, button[title="Clear Photo"]::after,
    button[aria-label="Clear photo"]::after, button[aria-label="Clear Photo"]::after,
    div[data-testid="stCameraInput"] button:nth-of-type(2):after { 
        content: "🗑️ APAGAR FOTO" !important; color: white !important; 
        position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); 
        font-size: 16px; font-weight: bold; width: 100%; display: block;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# CONFIGURAÇÕES E FUNÇÕES
# ==========================================
IMGBB_API_KEY = "dc43a47e760fb70d50f9578108cddf3b"
COL_MATRICULA = "Informe a Matrícula do Imóvel"
COL_CIDADE = "Informe cidade do Serviço"
COL_BAIRRO = "Informe o BAIRRO de Campina Grande"
COL_SERVICO = "Qual o Serviço ?"
COL_CONCLUSAO = "Conclusão"
COL_DATA = "Carimbo de data/hora"

def obter_conexao():
    try:
        segredo = st.secrets["google_credentials"]
        credenciais = json.loads(segredo) if isinstance(segredo, str) else dict(segredo)
        
        chave_privada = credenciais.get("private_key", "")
        chave_privada = chave_privada.replace("\\n", "\n").strip('"').strip("'")
        credenciais["private_key"] = chave_privada
        
        return gspread.service_account_from_dict(credenciais)
    except Exception as e:
        st.error(f"Erro ao conectar com o Google: {e}")
        st.stop()

def fazer_upload_foto(foto_bytes):
    try:
        url = "https://api.imgbb.com/1/upload"
        foto_b64 = base64.b64encode(foto_bytes).decode('utf-8')
        payload = {"key": IMGBB_API_KEY, "image": foto_b64}
        resposta = requests.post(url, data=payload)
        if resposta.status_code == 200:
            return resposta.json()['data']['url']
        else:
            return "FALHA_NO_UPLOAD"
    except:
        return "FALHA_NO_UPLOAD"

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

def definir_status(row):
    conclusao_original = str(row.get(COL_CONCLUSAO, "")).upper()
    conclusao = ''.join(c for c in unicodedata.normalize('NFD', conclusao_original) if unicodedata.category(c) != 'Mn')
    if "EXECUTAD" in conclusao or "FIZ O SERVICO" in conclusao: return "EXECUTADA", "#4CAF50"
    elif "DEVOLVID" in conclusao: return "DEVOLVIDA", "#F44336"
    elif "ANDAMENTO" in conclusao: return "EM ANDAMENTO", "#2196F3"
    else: return "PENDENTE", "#FF9800"

@st.cache_data(ttl=60, show_spinner=False)
def carregar_tarefas(operador):
    try:
        client = obter_conexao()
        aba_coords = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("PARAMETROS_MATRICULA")
        df_coords = pd.DataFrame(aba_coords.get_all_records())
        df_coords.columns = df_coords.columns.str.strip()
        df_coords = df_coords.loc[:, ~df_coords.columns.duplicated()]
        df_coords['Matrícula'] = df_coords['Matrícula'].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        df_coords = df_coords.drop_duplicates(subset=['Matrícula'], keep='last')
        
        aba_respostas = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("Respostas ao formulário 1")
        
        raw_values = aba_respostas.get_all_values()
        if not raw_values: return pd.DataFrame(), False, False
        headers = [str(h).strip() for h in raw_values[0]]
        
        df_respostas = pd.DataFrame(raw_values[1:], columns=headers)
        df_respostas = df_respostas.loc[:, ~df_respostas.columns.duplicated()]
        df_respostas['Linha_Planilha'] = df_respostas.index + 2
        
        df_formulas = pd.DataFrame(aba_respostas.get_all_values(value_render_option='FORMULA')[1:], columns=headers)
        df_formulas = df_formulas.loc[:, ~df_formulas.columns.duplicated()]
        
        if "Operador Atribuído" not in df_respostas.columns: df_respostas["Operador Atribuído"] = ""
        if "Data Programada" not in df_respostas.columns: df_respostas["Data Programada"] = ""
        if "Fotos" not in df_respostas.columns: df_respostas["Fotos"] = ""
            
        df_respostas['OS'] = "OS-" + (df_respostas.index + 2).astype(str)
        df_respostas[COL_MATRICULA] = df_respostas[COL_MATRICULA].astype(str).apply(lambda x: x.split('.')[0]).str.strip()
        
        # PROPAGANDO INFORMAÇÃO PELA PLANILHA ANTES DE FILTRAR
        df_respostas['Operador Atribuído'] = df_respostas.groupby(COL_MATRICULA)['Operador Atribuído'].ffill().fillna("")
        df_respostas['Data Programada'] = df_respostas.groupby(COL_MATRICULA)['Data Programada'].ffill().fillna("")
        df_respostas['Operador Atribuído'] = df_respostas['Operador Atribuído'].replace('-', '')
        df_respostas['Data Programada'] = df_respostas['Data Programada'].replace('-', '')

        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        # =========================================================================
        # INÍCIO DO "GUARDIÃO DA MEIA-NOITE" (App do Operador)
        # =========================================================================
        df_respostas['Data_Prog_Date'] = pd.to_datetime(df_respostas['Data Programada'], format='%d/%m/%Y', errors='coerce')
        hoje_date = pd.Timestamp(datetime.now().date())
        
        is_pendente = ~df_respostas.get(COL_CONCLUSAO, pd.Series()).str.contains("EXECUTAD|DEVOLVID", na=False)
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
                if col_conc: celulas.append(gspread.Cell(row=linha, col=col_conc, value=""))
                
                df_respostas.at[idx, 'Operador Atribuído'] = ""
                df_respostas.at[idx, 'Data Programada'] = ""
                
            if celulas:
                aba_respostas.update_cells(celulas)
        # =========================================================================

        # LENDO O STATUS DA NOVA ABA SEPARADA
        roteiro_iniciado = False
        roteiro_finalizado = False
        
        try:
            aba_status = client.open("Cópia de Controle Calçadas e Paredes TESTE").worksheet("STATUS_OPERADORES")
            df_status = pd.DataFrame(aba_status.get_all_records())
            
            if not df_status.empty:
                mask_eventos = (df_status['Operador'].astype(str).str.strip() == operador.strip()) & \
                               (df_status['Data Referencia'].astype(str).str.strip() == data_hoje)
                df_eventos = df_status[mask_eventos]
                
                if not df_eventos.empty:
                    ultimo_evento = str(df_eventos.iloc[-1]['Evento']).strip().upper()
                    if ultimo_evento == "INICIADO": roteiro_iniciado = True
                    elif ultimo_evento == "FINALIZADO": roteiro_finalizado = True
        except Exception:
            pass 
                
        mask_validas = df_respostas[COL_MATRICULA] != 'ROTEIRO_SISTEMA' 
        df_respostas = df_respostas[mask_validas].reset_index(drop=True)
        df_formulas = df_formulas[mask_validas].reset_index(drop=True)
        
        urls_extraidas = []
        for i in range(len(df_respostas)):
            url_found = ""
            val_f = str(df_formulas.iloc[i].get('Fotos', ''))
            if 'HYPERLINK' in val_f.upper():
                m = re.search(r'HYPERLINK\(\s*"([^"]+)"', val_f, re.IGNORECASE)
                if m: url_found = m.group(1)
            elif 'http' in val_f:
                m = re.search(r'(https?://[^\s,"]+)', val_f)
                if m: url_found = m.group(1)
            if not url_found:
                val_n = str(df_respostas.iloc[i].get('Fotos', ''))
                if 'http' in val_n:
                    m = re.search(r'(https?://[^\s,"]+)', val_n)
                    if m: url_found = m.group(1)
            if not url_found:
                for col in headers:
                    if ('foto' in col.lower() or 'link' in col.lower()) and col != 'Fotos':
                        val_f_col = str(df_formulas.iloc[i].get(col, ''))
                        if 'HYPERLINK' in val_f_col.upper():
                            m = re.search(r'HYPERLINK\(\s*"([^"]+)"', val_f_col, re.IGNORECASE)
                            if m: url_found = m.group(1); break
                        if 'http' in val_f_col:
                            m = re.search(r'(https?://[^\s,"]+)', val_f_col)
                            if m: url_found = m.group(1); break
                        val_n_col = str(df_respostas.iloc[i].get(col, ''))
                        if 'http' in val_n_col:
                            m = re.search(r'(https?://[^\s,"]+)', val_n_col)
                            if m: url_found = m.group(1); break
            if "drive.google.com" in url_found:
                id_match = re.search(r'id=([a-zA-Z0-9_-]+)', url_found)
                if not id_match: id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', url_found)
                if id_match: url_found = f"https://drive.google.com/file/d/{id_match.group(1)}/view"
            urls_extraidas.append(url_found)
            
        df_respostas['Fotos_Processadas'] = urls_extraidas
        
        df_respostas = df_respostas[df_respostas[COL_MATRICULA] != ""]
        df_respostas = df_respostas.drop_duplicates(subset=[COL_MATRICULA], keep='last')

        df_respostas['Status_Temp'] = df_respostas.apply(lambda row: definir_status(row)[0], axis=1)
        
        is_operador = df_respostas["Operador Atribuído"].astype(str).str.strip() == operador.strip()
        is_hoje = df_respostas["Data Programada"].astype(str).str.strip() == data_hoje
        is_pendente = df_respostas["Status_Temp"].isin(["PENDENTE", "EM ANDAMENTO"])
        
        # NOVA REGRA: Verifica se a ordem foi executada ou devolvida na data de hoje
        is_modificada_hoje = df_respostas[COL_DATA].astype(str).str.contains(data_hoje, na=False)
        
        # A ordem fica na tela se: for de hoje, OU estiver pendente, OU tiver sido alterada hoje
        df_tarefas = df_respostas[is_operador & (is_hoje | is_pendente | is_modificada_hoje)].copy()
        
        if df_tarefas.empty: return pd.DataFrame(), roteiro_iniciado, roteiro_finalizado
            
        df_completo = pd.merge(df_tarefas, df_coords, left_on=COL_MATRICULA, right_on='Matrícula', how='inner')
        return df_completo, roteiro_iniciado, roteiro_finalizado
    except Exception as e:
        st.error(f"Erro ao descarregar as tarefas: {e}")
        return pd.DataFrame(), False, False

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

def salvar_linha_segura(aba, nova_linha):
    coluna_a = aba.col_values(1)
    proxima_linha = len(coluna_a) + 1
    intervalo = f"A{proxima_linha}:J{proxima_linha}"
    try:
        try: aba.update(range_name=intervalo, values=[nova_linha], value_input_option='USER_ENTERED')
        except TypeError: aba.update(intervalo, [nova_linha], value_input_option='USER_ENTERED')
    except Exception:
        aba.add_rows(10)
        try: aba.update(range_name=intervalo, values=[nova_linha], value_input_option='USER_ENTERED')
        except TypeError: aba.update(intervalo, [nova_linha], value_input_option='USER_ENTERED')

def atualizar_status_linha(linha_planilha, novo_status):
    try:
        client = obter_conexao()
        planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
        aba = planilha.worksheet("Respostas ao formulário 1")
        header = [str(h).strip().upper() for h in aba.row_values(1)]
        
        col_idx_conc = None
        if "CONCLUSÃO" in header: col_idx_conc = header.index("CONCLUSÃO") + 1
        elif "CONCLUSAO" in header: col_idx_conc = header.index("CONCLUSAO") + 1
        
        if col_idx_conc is not None:
            aba.update_cell(int(linha_planilha), col_idx_conc, novo_status)
    except Exception:
        pass 

def registrar_execucao(matricula, servico, operador, cidade, bairro, f1, f2, f3):
    client = obter_conexao()
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    aba = planilha.worksheet("Respostas ao formulário 1")
    agora = datetime.now()
    data_formatada = agora.strftime("%d/%m/%Y %H:%M:%S")
    link1 = fazer_upload_foto(f1) if f1 else ""
    if link1 == "FALHA_NO_UPLOAD": return False
    link2 = fazer_upload_foto(f2) if f2 else ""
    if link2 == "FALHA_NO_UPLOAD": return False
    link3 = fazer_upload_foto(f3) if f3 else ""
    if link3 == "FALHA_NO_UPLOAD": return False
    
    nova_linha = [data_formatada, matricula, servico, "Executado ( Eu fiz o serviço )", operador, link1, link2, link3, cidade, bairro]
    salvar_linha_segura(aba, nova_linha)
    st.cache_data.clear()
    return True

def registrar_devolucao(matricula, servico, cidade, bairro, motivo, operador, foto_bytes, linha_planilha):
    client = obter_conexao()
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    aba = planilha.worksheet("Respostas ao formulário 1")
    
    agora = datetime.now()
    data_formatada = agora.strftime("%d/%m/%Y %H:%M:%S")
    link_foto = fazer_upload_foto(foto_bytes) if foto_bytes else ""
    if link_foto == "FALHA_NO_UPLOAD": return False
    conclusao_devolucao = f"DEVOLVIDO: {motivo}"
    
    nova_linha = [data_formatada, matricula, servico, conclusao_devolucao, operador, link_foto, "", "", cidade, bairro]
    salvar_linha_segura(aba, nova_linha)
    
    header_upper = [str(h).strip().upper() for h in aba.row_values(1)]
    col_op = header_upper.index("OPERADOR ATRIBUÍDO") + 1 if "OPERADOR ATRIBUÍDO" in header_upper else None
    col_dt = header_upper.index("DATA PROGRAMADA") + 1 if "DATA PROGRAMADA" in header_upper else None
    
    celulas = []
    if col_op: celulas.append(gspread.Cell(row=int(linha_planilha), col=col_op, value="-"))
    if col_dt: celulas.append(gspread.Cell(row=int(linha_planilha), col=col_dt, value="-"))
    
    if celulas:
        aba.update_cells(celulas)
        
    st.cache_data.clear() 
    return True

def registrar_evento_roteiro(operador, evento):
    client = obter_conexao()
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    
    try:
        aba_status = planilha.worksheet("STATUS_OPERADORES")
    except gspread.exceptions.WorksheetNotFound:
        aba_status = planilha.add_worksheet(title="STATUS_OPERADORES", rows=1000, cols=4)
        aba_status.append_row(["Data/Hora", "Operador", "Evento", "Data Referencia"])

    agora = datetime.now()
    data_formatada = agora.strftime("%d/%m/%Y %H:%M:%S")
    data_hoje = agora.strftime("%d/%m/%Y")
    
    nova_linha = [data_formatada, operador, evento, data_hoje]
    
    aba_status.append_row(nova_linha, value_input_option='USER_ENTERED')
    return True

def finalizar_roteiro_sem_poluir(df_pendentes):
    if df_pendentes.empty: return True
    client = obter_conexao()
    planilha = client.open("Cópia de Controle Calçadas e Paredes TESTE")
    aba = planilha.worksheet("Respostas ao formulário 1")
    header = [str(h).strip() for h in aba.row_values(1)]
    header_upper = [h.upper() for h in header]
    
    col_idx_conc = None
    if "CONCLUSÃO" in header_upper: col_idx_conc = header_upper.index("CONCLUSÃO") + 1
    elif "CONCLUSAO" in header_upper: col_idx_conc = header_upper.index("CONCLUSAO") + 1
    
    col_idx_op = header_upper.index("OPERADOR ATRIBUÍDO") + 1 if "OPERADOR ATRIBUÍDO" in header_upper else None
    col_idx_dt = header_upper.index("DATA PROGRAMADA") + 1 if "DATA PROGRAMADA" in header_upper else None
    
    celulas = []
    for _, row in df_pendentes.iterrows():
        linha = int(row['Linha_Planilha'])
        if col_idx_conc: celulas.append(gspread.Cell(row=linha, col=col_idx_conc, value=""))
        if col_idx_op: celulas.append(gspread.Cell(row=linha, col=col_idx_op, value="-"))
        if col_idx_dt: celulas.append(gspread.Cell(row=linha, col=col_idx_dt, value="-"))
        
    if celulas:
        aba.update_cells(celulas)
    return True

# ==========================================
# INTERFACE MOBILE (APP)
# ==========================================
st.markdown("<h2 style='text-align: center; color: #1E88E5;'>📱 APP OPERAÇÃO CTV</h2>", unsafe_allow_html=True)

if not st.session_state.autenticado:
    operador_selecionado = st.selectbox(
        "👷 Identifique-se:", 
        options=["Julio Cesar", "Joseilton", "Alberth"],
        index=None, placeholder="Escolha o operador"
    )
    if operador_selecionado:
        st.divider()
        banco_senhas = {"Alberth": "123", "Julio Cesar": "456", "Joseilton": "789"}
        with st.form(key="form_login"):
            senha_digitada = st.text_input("🔑 Digite sua senha de acesso:", type="password")
            botao_entrar = st.form_submit_button("Entrar no Sistema", use_container_width=True)
            if botao_entrar:
                if senha_digitada == banco_senhas.get(operador_selecionado):
                    cookies["autenticado"] = "True"
                    cookies["operador_logado"] = operador_selecionado
                    cookies.save()
                    time.sleep(0.5)
                    st.session_state.autenticado = True
                    st.session_state.operador_logado = operador_selecionado
                    st.rerun()
                else: st.error("❌ Senha incorreta! Por favor, tente novamente.")

if st.session_state.autenticado:
    operador = st.session_state.operador_logado
    
    with st.spinner("Atualizando roteiro..."):
        df_tarefas, roteiro_iniciado, roteiro_finalizado = carregar_tarefas(operador)
        
    if not df_tarefas.empty:
        df_tarefas[['Status', 'Cor_Status']] = df_tarefas.apply(definir_status, axis=1, result_type='expand')
        df_pendentes_gerais = df_tarefas[(df_tarefas['Status'] != 'EXECUTADA') & (df_tarefas['Status'] != 'DEVOLVIDA')]
        qtd_pendentes_reais = len(df_pendentes_gerais)
        
        if roteiro_finalizado and qtd_pendentes_reais > 0:
            roteiro_finalizado = False
            roteiro_iniciado = False
            st.warning("🚨 **NOVA MISSÃO NA ÁREA!** O Controle acabou de despachar ordens fresquinhas para o seu roteiro. O descanso vai ter que esperar um pouquinho! Clique em 'INICIAR MEU ROTEIRO' abaixo para puxar as novas OS.")

    if roteiro_finalizado:
        st.balloons()
        st.markdown("""
        <div style='background-color: #1b5e20; padding: 20px; border-radius: 10px; text-align: center; border: 2px solid #4CAF50; margin-top: 20px;'>
            <h2 style='color: white; margin-bottom: 10px;'>🍻 MISSÃO CUMPRIDA!</h2>
            <p style='color: white; font-size: 16px; margin-bottom: 0;'>Você já encerrou o expediente. As ordens não executadas foram recolhidas pela Base.<br><br><b>Bom descanso guerreiro, até a próxima! 🚀😎</b></p>
        </div>
        """, unsafe_allow_html=True)
        st.write("---")
        
        if st.button("🔄 Checar Novas Ordens da Base", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
            
        if st.button("🚪 Sair", use_container_width=True):
            cookies["autenticado"] = "False"; cookies["operador_logado"] = ""; cookies.save()
            st.session_state.autenticado = False; st.session_state.operador_logado = ""; st.session_state.os_aberta = None
            st.session_state.status_forcado = None; st.session_state.foto_ampliada = None; st.session_state.bairro_expandido = None
            st.rerun()
        st.stop()
    
    # =========================================
    # TELA CHEIA PARA A FOTO
    # =========================================
    elif st.session_state.foto_ampliada is not None:
        st.markdown("<h3 style='text-align: center; color: white;'>📸 Foto do Local</h3>", unsafe_allow_html=True)
        foto_amp = st.session_state.foto_ampliada
        
        img_src_amp = foto_amp
        if "drive.google.com" in foto_amp:
            m_id = re.search(r'/d/([a-zA-Z0-9_-]+)', foto_amp)
            if m_id:
                img_src_amp = f"https://drive.google.com/thumbnail?id={m_id.group(1)}&sz=w1000"
                
        safe_img_src = img_src_amp.replace('https://', '//').replace('http://', '//')
        st.markdown(f"<img src='{safe_img_src}' style='width:100%; border-radius:8px; margin-bottom:15px;'>", unsafe_allow_html=True)
            
        st.write("")
        if st.button("⬅️ VOLTAR", use_container_width=True, type="primary"):
            st.session_state.foto_ampliada = None
            st.rerun()
            
    # =========================================
    # TELA DE DETALHES DA ORDEM
    # =========================================
    elif st.session_state.os_aberta is not None:
        if not df_tarefas.empty:
            df_tarefas['Bairro_Exibicao'] = df_tarefas.apply(extrair_bairro_inteligente, axis=1)
            matricula_ativa = st.session_state.os_aberta
            df_filtrado = df_tarefas[df_tarefas[COL_MATRICULA].astype(str) == str(matricula_ativa)]
            
            if df_filtrado.empty:
                st.warning("Ordem de serviço não encontrada ou já processada.")
                if st.button("⬅️ Voltar", use_container_width=True):
                    st.session_state.os_aberta = None
                    st.rerun()
            else:
                row = df_filtrado.iloc[0]
                linha_planilha = row['Linha_Planilha']
                matricula = row[COL_MATRICULA]
                servico = row[COL_SERVICO]
                os_num = row['OS']
                lat, lon = row.get('Coordenada X'), row.get('Coordenada Y')
                lat = limpar_coordenadas(lat, 'lat')
                lon = limpar_coordenadas(lon, 'lon')
                endereco = row.get('Endereço', 'Endereço não informado')
                cidade_bairro = row[COL_CIDADE].title()
                nome_bairro = row['Bairro_Exibicao'].title()
                
                if st.button("⬅️ Voltar para a Lista", use_container_width=True):
                    with st.spinner("Voltando..."):
                        atualizar_status_linha(linha_planilha, "PENDENTE") # DEVOLVE O STATUS PARA PENDENTE NA PLANILHA
                        st.session_state.os_aberta = None
                        if "status_forcado" in st.session_state: del st.session_state["status_forcado"]
                        st.cache_data.clear()
                        st.rerun()
                
                st.markdown(f"## 📄 {os_num}")
                st.markdown(f"### 📍 {nome_bairro} / {cidade_bairro}")
                st.info(f"**Endereço:** {endereco}")
                st.warning(f"**Serviço:** {servico}")
                st.code(f"Matrícula: {matricula}")
                
                st.write("---")
                st.write("🖼️ **Foto do Serviço Anterior:**")
                
                raw_foto_texto = str(row.get('Fotos', '')).strip()
                foto_url = str(row.get('Fotos_Processadas', '')).strip()

                if foto_url and foto_url.startswith('http'):
                    img_src = foto_url
                    if "drive.google.com" in foto_url:
                        m_id = re.search(r'/d/([a-zA-Z0-9_-]+)', foto_url)
                        if m_id:
                            img_src = f"https://drive.google.com/thumbnail?id={m_id.group(1)}&sz=w800"
                            
                    safe_img_src = img_src.replace('https://', '//').replace('http://', '//')
                    st.markdown(f"<img src='{safe_img_src}' style='width:100%; height:250px; object-fit:cover; border-radius:8px; margin-bottom:15px; border: 1px solid #555;'>", unsafe_allow_html=True)
                        
                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        if st.button("🖼️ Ampliar Foto", use_container_width=True):
                            st.session_state.foto_ampliada = foto_url
                            st.rerun()
                    with col_f2:
                        st.link_button("🔗 Abrir no Navegador", foto_url, use_container_width=True)
                elif raw_foto_texto:
                    m_link = re.search(r'(https?://[^\s,"]+)', raw_foto_texto)
                    if m_link:
                        st.success("Link encontrado no registro!")
                        st.link_button("🔗 Abrir Link Registrado", m_link.group(1), use_container_width=True)
                    else:
                        st.error(f"⚠️ Link oculto pelo Google Sheets.")
                        st.warning(f"O Google enviou apenas o nome do arquivo: **{raw_foto_texto}**")
                        st.caption("Para o link voltar a funcionar, vá na planilha, clique na célula da foto e remova o formato de 'Chip Inteligente', deixando o link começar com http:// normal.")
                else:
                    st.caption("Nenhuma foto/link registrado pela equipe anterior.")
                
                st.write("---")
                
                if pd.notna(lat) and pd.notna(lon):
                    link_gps = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
                    st.link_button("🧭 Iniciar Navegação GPS (Google Maps)", link_gps, use_container_width=True)
                    st.caption("Dica: Após clicar em Navegar, minimize ou volte para o app para ativar o mapa flutuante!")
                
                st.write("📸 **Registros Fotográficos (Execução)**")
                foto1 = st.camera_input("Foto 1 (Obrigatória)", key=f"cam1_{matricula}")
                foto2 = st.camera_input("Foto 2 (Opcional)", key=f"cam2_{matricula}")
                foto3 = st.camera_input("Foto 3 (Opcional)", key=f"cam3_{matricula}")
                
                st.write("---")
                
                chave_devolucao = f"devolver_{matricula}"
                if chave_devolucao not in st.session_state:
                    st.session_state[chave_devolucao] = False
                
                if st.session_state[chave_devolucao]:
                    st.error("⚠️ Processo de Devolução de OS")
                    motivo_dev = st.text_area("Motivo detalhado da devolução:", key=f"texto_dev_{matricula}")
                    
                    c_cancel, c_confirm = st.columns(2)
                    with c_cancel:
                        if st.button("❌ Cancelar", key=f"canc_dev_{matricula}", use_container_width=True):
                            st.session_state[chave_devolucao] = False
                            st.rerun()
                    with c_confirm:
                        if st.button("✅ Confirmar Devolução", key=f"conf_dev_{matricula}", type="primary", use_container_width=True):
                            texto_motivo = motivo_dev.strip()
                            if len(texto_motivo) < 5:
                                st.error("Escreva um motivo detalhado.")
                            else:
                                f_bytes = foto1.getvalue() if foto1 is not None else None
                                with st.spinner("Devolvendo..."):
                                    sucesso = registrar_devolucao(matricula, servico, cidade_bairro, nome_bairro, texto_motivo, operador, f_bytes, linha_planilha)
                                    if sucesso:
                                        st.session_state.os_aberta = None
                                        if "status_forcado" in st.session_state: del st.session_state["status_forcado"]
                                        st.session_state[chave_devolucao] = False
                                        st.success("OS devolvida com sucesso!")
                                        time.sleep(2)
                                        st.rerun()
                                    else:
                                        st.error("Falha no envio.")
                else:
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("↩️ Solicitar Devolução", key=f"btn_devolver_{matricula}", use_container_width=True):
                            st.session_state[chave_devolucao] = True
                            st.rerun()
                    with col2:
                        if st.button("✅ FINALIZAR SERVIÇO", key=f"btn_{matricula}", type="primary", use_container_width=True):
                            if foto1 is not None:
                                f1_bytes = foto1.getvalue()
                                f2_bytes = foto2.getvalue() if foto2 is not None else None
                                f3_bytes = foto3.getvalue() if foto3 is not None else None
                                with st.spinner("Encerrando..."):
                                    sucesso = registrar_execucao(matricula, servico, operador, cidade_bairro, nome_bairro, f1_bytes, f2_bytes, f3_bytes)
                                    if sucesso:
                                        st.session_state.os_aberta = None
                                        if "status_forcado" in st.session_state: del st.session_state["status_forcado"]
                                        st.success("Serviço concluído!")
                                        time.sleep(2)
                                        st.rerun()
                                    else:
                                        st.error("Falha no envio.")
                            else:
                                st.warning("⚠️ A Foto 1 é obrigatória!")

    # =========================================
    # TELA DE LISTAGEM DE ROTAS (LISTA PRINCIPAL)
    # =========================================
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"🔓 Logado como: **{operador}**")
        with col2:
            if st.button("🚪 Sair", use_container_width=True):
                cookies["autenticado"] = "False"
                cookies["operador_logado"] = ""
                cookies.save()
                st.session_state.autenticado = False
                st.session_state.operador_logado = ""
                st.session_state.os_aberta = None
                st.session_state.status_forcado = None
                st.session_state.foto_ampliada = None
                st.session_state.bairro_expandido = None
                st.rerun()
        
        if st.button("🔄 Atualizar Lista", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
            
        if not df_tarefas.empty:
            df_tarefas['lat'] = df_tarefas['Coordenada X'].apply(lambda x: limpar_coordenadas(x, 'lat'))
            df_tarefas['lon'] = df_tarefas['Coordenada Y'].apply(lambda y: limpar_coordenadas(y, 'lon'))
            
            df_tarefas['Bairro_Exibicao'] = df_tarefas.apply(extrair_bairro_inteligente, axis=1)
            df_tarefas = df_tarefas.sort_values(by=[COL_CIDADE, 'Bairro_Exibicao', 'Endereço'])
            
            df_pendentes_gerais = df_tarefas[(df_tarefas['Status'] != 'EXECUTADA') & (df_tarefas['Status'] != 'DEVOLVIDA')]
            qtd_pendentes = len(df_pendentes_gerais)
            total_servicos = len(df_tarefas)
            
            if not roteiro_iniciado and qtd_pendentes > 0:
                st.markdown("<br>", unsafe_allow_html=True)
                st.info(f"🎯 **O expediente vai começar!**\n\nVocê tem **{qtd_pendentes}** ordens alocadas no seu roteiro de hoje. Clique abaixo para iniciar os trabalhos.")
                if st.button("▶️ INICIAR MEU ROTEIRO", type="primary", use_container_width=True):
                    with st.spinner("Avisando a Central..."):
                        registrar_evento_roteiro(operador, "INICIADO")
                        st.cache_data.clear()
                        st.rerun()
                st.stop()
            
            aba_lista, aba_mapa = st.tabs(["📋 LISTA", "🗺️ MAPA"])
            
            with aba_lista:
                if qtd_pendentes == 0 and total_servicos > 0:
                    st.balloons()
                    st.markdown("<div style='background-color: #1b5e20; padding: 20px; border-radius: 10px; text-align: center; border: 2px solid #4CAF50; margin-bottom: 20px;'><h2 style='color: white; margin-bottom: 10px;'>🍻 CABOCO BOM DA PESTE!</h2><p style='color: white; font-size: 18px; margin-bottom: 0;'>Botou pra torar! O roteiro de hoje tá todo matado. Pode encostar a viatura, lavar as mãos e pegar o beco, que o serviço tá no mato! 😎🔧</p></div>", unsafe_allow_html=True)
                else:
                    detalhes_list = []
                    for status, qtd in df_tarefas['Status'].value_counts().items():
                        if status != 'PENDENTE':
                            nome_status = "finalizada" if status == "EXECUTADA" else status.lower()
                            detalhes_list.append(f"{qtd} {nome_status}")
                    texto_detalhes = ", ".join(detalhes_list)
                    prefixo_detalhes = f" sendo {texto_detalhes}" if texto_detalhes else ""
                    st.success(f"📍 Roteiro de Hoje: {total_servicos} serviços no total{prefixo_detalhes} ({qtd_pendentes} pendentes).")
                
                cidades_unicas = sorted(df_tarefas[COL_CIDADE].unique())
                
                for cidade in cidades_unicas:
                    st.markdown(f"<h3 style='color: #4fc3f7; padding-top: 15px; border-bottom: 1px solid #555; padding-bottom: 5px;'>🏙️ {cidade.upper()}</h3>", unsafe_allow_html=True)
                    
                    df_cidade = df_tarefas[df_tarefas[COL_CIDADE] == cidade]
                    bairros_cidade = sorted(df_cidade['Bairro_Exibicao'].unique())
                    
                    for bairro in bairros_cidade:
                        df_bairro = df_cidade[df_cidade['Bairro_Exibicao'] == bairro]
                        nome_bairro_tela = bairro.title()
                        
                        is_expanded = (st.session_state.bairro_expandido == nome_bairro_tela)
                        
                        with st.expander(f"🗺️ {nome_bairro_tela} ({len(df_bairro)} serviços)", expanded=is_expanded):
                            for index, row in df_bairro.iterrows():
                                matricula = row[COL_MATRICULA]
                                servico = row[COL_SERVICO]
                                endereco = row.get('Endereço', 'Endereço não informado')
                                status = row['Status']
                                cor_badge = row['Cor_Status']
                                linha_planilha = row['Linha_Planilha']
                                
                                foto_url = str(row.get('Fotos_Processadas', '')).strip()
                                raw_foto = str(row.get('Fotos', '')).strip()
                                
                                if foto_url and foto_url.startswith('http'):
                                    img_src_list = foto_url
                                    if "drive.google.com" in foto_url:
                                        m_id = re.search(r'/d/([a-zA-Z0-9_-]+)', foto_url)
                                        if m_id:
                                            img_src_list = f"https://drive.google.com/thumbnail?id={m_id.group(1)}&sz=w800"
                                            
                                    bg_url = img_src_list.replace('https://', '//').replace('http://', '//')
                                    bg_style = f"background: linear-gradient(to right, rgba(20,20,20,0.95) 0%, rgba(20,20,20,0.8) 45%, rgba(20,20,20,0.1) 100%), url('{bg_url}') center/cover no-repeat;"
                                    
                                    html_card = f"""
                                    <div style="border: 1px solid #555; border-radius: 8px; padding: 15px; margin-bottom: 15px; {bg_style} min-height: 180px; box-shadow: 0 4px 10px rgba(0,0,0,0.5);">
                                        <div style="background-color: {cor_badge}; color: white; display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-bottom: 12px;">{status}</div>
                                        <div style="font-size: 18px; font-weight: bold; color: white; text-shadow: 1px 1px 3px black;">Matrícula: {matricula}</div>
                                        <div style="font-size: 14px; margin-top: 8px; color: #eee; text-shadow: 1px 1px 3px black; width: 75%; line-height: 1.4;">{endereco}</div>
                                        <div style="font-size: 12px; color: #ccc; margin-top: 12px; text-shadow: 1px 1px 3px black;">Serviço</div>
                                        <div style="font-size: 14px; color: white; font-weight: bold; text-shadow: 1px 1px 3px black; margin-bottom: 15px;">{servico}</div>
                                        <div style="display: inline-block; background: rgba(0,0,0,0.7); border: 1px solid #4fc3f7; color: #4fc3f7; padding: 6px 12px; border-radius: 4px; font-size: 11px; font-weight: bold;">👇 USE O BOTÃO 'AMPLIAR' ABAIXO PARA TELA CHEIA</div>
                                    </div>
                                    """.replace('\n', '')
                                    
                                else:
                                    m_raw = re.search(r'(https?://[^\s,"]+)', raw_foto)
                                    if m_raw:
                                        safe_href = m_raw.group(1).replace('https://', '//').replace('http://', '//')
                                        indicador_foto = f"<a href='{safe_href}' target='_blank' style='color: #4fc3f7; text-decoration: none; display: block; width: 100%; font-weight: bold;'>📸 CLIQUE AQUI PARA ABRIR A FOTO</a>"
                                    else:
                                        indicador_foto = f"<span style='color: #f44336;'>Sem foto anterior</span>" if not raw_foto else f"⚠️ O Google Sheets bloqueou o link (Chip Inteligente). Nome: {raw_foto}"
                                        
                                    html_card = f"""
                                    <div style="border: 1px solid #444; border-radius: 8px; padding: 15px; margin-bottom: 15px; background-color: #1e1e1e;">
                                        <div style="background-color: {cor_badge}; color: white; display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-bottom: 12px;">{status}</div>
                                        <div style="font-size: 18px; font-weight: bold; color: white;">Matrícula: {matricula}</div>
                                        <div style="font-size: 14px; margin-top: 8px; color: #ddd;">{endereco}</div>
                                        <div style="font-size: 12px; color: #aaa; margin-top: 12px;">Serviço</div>
                                        <div style="font-size: 14px; color: white; font-weight: 500; margin-bottom: 15px;">{servico}</div>
                                        <div style="font-size: 12px; white-space: normal; background: rgba(0,0,0,0.8); padding: 8px; border-radius: 4px;">{indicador_foto}</div>
                                    </div>
                                    """.replace('\n', '')
                                
                                st.markdown(html_card, unsafe_allow_html=True)
                                
                                if status == "PENDENTE":
                                    if foto_url and foto_url.startswith('http'):
                                        col_btn1, col_btn2 = st.columns(2)
                                        with col_btn1:
                                            if st.button("📂 Abrir Ordem", key=f"abrir_{matricula}", use_container_width=True):
                                                with st.spinner("Abrindo..."):
                                                    atualizar_status_linha(linha_planilha, "EM ANDAMENTO") # ENVIA O STATUS PARA A PLANILHA
                                                    st.session_state.os_aberta = matricula
                                                    st.session_state.status_forcado = matricula
                                                    st.session_state.bairro_expandido = nome_bairro_tela
                                                    st.cache_data.clear()
                                                    st.rerun()
                                        with col_btn2:
                                            if st.button("🖼️ Ampliar", key=f"foto_{matricula}", use_container_width=True):
                                                st.session_state.foto_ampliada = foto_url
                                                st.session_state.bairro_expandido = nome_bairro_tela
                                                st.rerun()
                                    else:
                                        if st.button("📂 Abrir Ordem", key=f"abrir_unica_{matricula}", use_container_width=True):
                                            with st.spinner("Abrindo..."):
                                                atualizar_status_linha(linha_planilha, "EM ANDAMENTO") # ENVIA O STATUS PARA A PLANILHA
                                                st.session_state.os_aberta = matricula
                                                st.session_state.status_forcado = matricula
                                                st.session_state.bairro_expandido = nome_bairro_tela
                                                st.cache_data.clear()
                                                st.rerun()
                                elif status == "EM ANDAMENTO":
                                    if st.button("🚧 Continuar Execução", key=f"cont_{matricula}", type="primary", use_container_width=True):
                                        with st.spinner("Abrindo..."):
                                            atualizar_status_linha(linha_planilha, "EM ANDAMENTO") # ENVIA O STATUS PARA A PLANILHA
                                            st.session_state.os_aberta = matricula
                                            st.session_state.status_forcado = matricula
                                            st.session_state.bairro_expandido = nome_bairro_tela
                                            st.cache_data.clear()
                                            st.rerun()
                                else:
                                    st.caption(f"✔️ Serviço registrado como {status.lower()} hoje.")
                                
                                st.write("") 
                                
                if roteiro_iniciado or total_servicos > 0:
                    st.write("---")
                    if not st.session_state.confirmar_fim:
                        if st.button("🛑 FINALIZAR ROTEIRO DO DIA", use_container_width=True):
                            st.session_state.confirmar_fim = True
                            st.rerun()
                    else:
                        st.error("⚠️ Atenção: Isso encerrará seu expediente. Ordens pendentes voltarão para a base. Tem certeza?")
                        col_cf1, col_cf2 = st.columns(2)
                        with col_cf1:
                            if st.button("❌ Cancelar", use_container_width=True):
                                st.session_state.confirmar_fim = False
                                st.rerun()
                        with col_cf2:
                            if st.button("✅ Sim, Finalizar Roteiro", type="primary", use_container_width=True):
                                with st.spinner("Encerrando expediente..."):
                                    finalizar_roteiro_sem_poluir(df_pendentes_gerais)
                                    registrar_evento_roteiro(operador, "FINALIZADO")
                                    st.session_state.confirmar_fim = False
                                    st.cache_data.clear()
                                    time.sleep(2)
                                    st.rerun()

            with aba_mapa:
                st.info("Visualização geográfica das ordens do dia.")
                df_mapa = df_tarefas.dropna(subset=['lat', 'lon']).copy()
                if not df_mapa.empty:
                    st.map(df_mapa, latitude='lat', longitude='lon', color='Cor_Status', use_container_width=True)
                else:
                    st.warning("Nenhuma coordenada válida encontrada para exibir o mapa.")
        else:
            st.markdown("<div style='background-color: #e65100; padding: 20px; border-radius: 10px; text-align: center; border: 2px solid #ff9800; margin-bottom: 20px;'><h2 style='color: white; margin-bottom: 10px;'>😎 TÁ DE FOLGA, CHEFIA?</h2><p style='color: white; font-size: 18px; margin-bottom: 0;'>O roteiro de hoje tá mais limpo que bolso de liso. Não tem ordem programada pra você não. Fica na maciota aí até o controle despachar alguma coisa!</p></div>", unsafe_allow_html=True)
