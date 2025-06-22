import json
import os
import requests
import openpyxl
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("realocar_orcamento.log"),
        logging.StreamHandler()
    ]
)

logs_list = None

def log_message(msg):
    mensagem = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(mensagem)
    with open("run_log.txt", "a", encoding="utf-8") as f:
        f.write(mensagem + "\n")
    if logs_list is not None:
        logs_list.append(mensagem)
    logging.info(msg)

# Leitura de config.json
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    default_config = {
        "ACCESS_TOKEN": "",
        "AD_ACCOUNTS": [],
        "ABO_ACCOUNTS": [],
        "LIMITE_LUCRO_BAIXO": 1000,
        "LIMITE_LUCRO_ALTO": 5000,
        "PERCENTUAL_REALOCACAO": 0.30,
        "MINIMO_ORCAMENTO": 100,
        "MINIMO_ORCAMENTO_ABO": 8,
        "MAXIMO_ORCAMENTO": 10000,
        "WHATSAPP_GROUP": "#ZIP - ROAS IMPERIO",
        "DATE_PRESET": "today"
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=4, ensure_ascii=False)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

ACCESS_TOKEN = config.get("ACCESS_TOKEN", "")
AD_ACCOUNTS = config.get("AD_ACCOUNTS", [])
ABO_ACCOUNTS = config.get("ABO_ACCOUNTS", [])
SPREADSHEET_PATH = "campanhas_realocacao.xlsx"
LIMITE_LUCRO_BAIXO = float(config.get("LIMITE_LUCRO_BAIXO", 1000))
LIMITE_LUCRO_ALTO = float(config.get("LIMITE_LUCRO_ALTO", 5000))
PERCENTUAL_REALOCACAO = float(config.get("PERCENTUAL_REALOCACAO", 0.30))
MINIMO_ORCAMENTO = float(config.get("MINIMO_ORCAMENTO", 100))
MINIMO_ORCAMENTO_ABO = float(config.get("MINIMO_ORCAMENTO_ABO", 8))
MAXIMO_ORCAMENTO = float(config.get("MAXIMO_ORCAMENTO", 10000))
WHATSAPP_GROUP = config.get("WHATSAPP_GROUP", "#ZIP - ROAS IMPERIO")
DATE_PRESET = config.get("DATE_PRESET", "today")

# Armazena dados completos das campanhas para uso na realocação
campanhas_completas_data = {}

def criar_planilha():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "CAMPANHAS"
    sheet.append([
        "ID da Conta de Anúncio", "ID da Campanha", "Nome da Campanha", "Tipo",
        "Orçamento Diário", "Gasto", "Valor de Conversões",
        "ROAS", "Lucro", "Novo Orçamento", "Classificação", "Detalhes AdSets"
    ])
    workbook.save(SPREADSHEET_PATH)
    log_message("Planilha criada com sucesso.")

def limpar_planilha():
    if os.path.exists(SPREADSHEET_PATH):
        try:
            workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
            if "CAMPANHAS" in workbook.sheetnames:
                sheet = workbook["CAMPANHAS"]
                sheet.delete_rows(2, sheet.max_row)
            else:
                workbook.create_sheet("CAMPANHAS")
            workbook.save(SPREADSHEET_PATH)
            log_message("Planilha limpa no início da execução.")
        except Exception as e:
            log_message(f"[ERRO] Falha ao limpar a planilha: {e}")
    else:
        log_message("Planilha não encontrada. Criando nova planilha.")
        criar_planilha()

def buscar_dados_facebook(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        log_message(f"[ERRO] Falha ao buscar dados do Facebook: {e}\nResposta: {response.text if 'response' in locals() else ''}")
        return {}

def buscar_todos_dados_facebook(url):
    todos_dados = []
    while url:
        dados = buscar_dados_facebook(url)
        if "error" in dados:
            log_message(f"[ERRO] Graph API retornou: {dados['error']}")
            break
        page_data = dados.get("data", [])
        todos_dados.extend(page_data)
        url = dados.get("paging", {}).get("next")
    return todos_dados

def detectar_tipo_campanha(campanha, ad_account):
    """Detecta se a campanha é CBO ou ABO"""
    daily_budget = campanha.get("daily_budget", 0)
    
    if ad_account in ABO_ACCOUNTS:
        return "ABO"
    
    if daily_budget and int(daily_budget) > 0:
        return "CBO"
    else:
        return "ABO"

def buscar_adsets_campanha(campaign_id):
    """Busca todos os ad sets de uma campanha ABO"""
    url = (
        f"https://graph.facebook.com/v17.0/{campaign_id}/adsets"
        f"?fields=id,name,daily_budget,status&access_token={ACCESS_TOKEN}"
    )
    return buscar_todos_dados_facebook(url)

def buscar_insights_adset(ad_account, campaign_id, date_preset=None, start_date=None, end_date=None):
    """Busca insights no nível de ad set para campanhas ABO"""
    filtering = f'[{{"field":"campaign.id","operator":"EQUAL","value":"{campaign_id}"}}]'
    
    if date_preset:
        url = (
            f"https://graph.facebook.com/v17.0/{ad_account}/insights"
            f"?fields=adset_id,adset_name,campaign_id,spend,action_values"
            f"&date_preset={date_preset}&level=adset"
            f"&filtering={filtering}"
            f"&access_token={ACCESS_TOKEN}"
        )
    else:
        url = (
            f"https://graph.facebook.com/v17.0/{ad_account}/insights"
            f"?fields=adset_id,adset_name,campaign_id,spend,action_values"
            f"&time_range[since]={start_date}&time_range[until]={end_date}"
            f"&level=adset"
            f"&filtering={filtering}"
            f"&access_token={ACCESS_TOKEN}"
        )
    
    return buscar_todos_dados_facebook(url)

def processar_campanha_abo(campanha, ad_account, date_preset=None, start_date=None, end_date=None):
    """Processa campanhas ABO agregando dados de todos os ad sets ativos"""
    campaign_id = campanha["id"]
    log_message(f"Processando campanha ABO: {campanha['name']}")
    
    adsets = buscar_adsets_campanha(campaign_id)
    insights_adsets = buscar_insights_adset(ad_account, campaign_id, date_preset, start_date, end_date)
    
    # Agregar dados de todos os ad sets ativos
    total_orcamento = 0
    total_gasto = 0
    total_conversao = 0
    adsets_info = []
    adsets_ativos = 0
    
    for adset in adsets:
        if adset.get("status") == "ACTIVE":
            adsets_ativos += 1
            adset_id = adset["id"]
            daily_budget = float(adset.get("daily_budget", 0)) / 100
            total_orcamento += daily_budget
            
            # Buscar insight correspondente
            insight = next((i for i in insights_adsets if i.get("adset_id") == adset_id), None)
            
            if insight:
                gasto = float(insight.get("spend", 0))
                valor_conversao = sum(
                    float(a.get("value", 0))
                    for a in insight.get("action_values", [])
                    if a.get("action_type") in ['offsite_conversion.purchase', 'offsite_conversion.fb_pixel_purchase']
                )
                total_gasto += gasto
                total_conversao += valor_conversao
            else:
                gasto = 0
                valor_conversao = 0
            
            lucro = valor_conversao - gasto
            
            adsets_info.append({
                "adset_id": adset_id,
                "adset_name": adset["name"],
                "daily_budget": daily_budget,
                "gasto": gasto,
                "valor_conversao": valor_conversao,
                "lucro": lucro
            })
    
    log_message(f"Campanha ABO {campaign_id}: {adsets_ativos} adsets ativos, orçamento total: R$ {total_orcamento:.2f}")
    
    lucro = total_conversao - total_gasto
    roas = round(total_conversao / total_gasto, 2) if total_gasto > 0 else 0
    
    # Classificação baseada no lucro
    if lucro < LIMITE_LUCRO_BAIXO:
        classificacao = "BAIXO"
    elif lucro >= LIMITE_LUCRO_ALTO:
        classificacao = "ALTO"
    else:
        classificacao = "MÉDIO"
    
    return {
        "id_conta": ad_account,
        "id_campanha": campaign_id,
        "nome_campanha": campanha["name"],
        "tipo_campanha": "ABO",
        "orcamento_diario": total_orcamento,
        "gasto": total_gasto,
        "valor_conversao": total_conversao,
        "roas": roas,
        "lucro": lucro,
        "classificacao": classificacao,
        "adsets_info": adsets_info,
        "detalhes_adsets": f"{adsets_ativos} adsets ativos"
    }

def processar_dados_campanhas(campanhas, insights, ad_account, date_preset=None, start_date=None, end_date=None):
    """Processa dados das campanhas, detectando automaticamente se são CBO ou ABO"""
    campanhas_filtradas = []
    
    for campanha in campanhas:
        if campanha.get("status", "").upper().strip() == "ACTIVE":
            tipo_campanha = detectar_tipo_campanha(campanha, ad_account)
            
            if tipo_campanha == "ABO":
                # Processar como ABO
                dados_campanha = processar_campanha_abo(campanha, ad_account, date_preset, start_date, end_date)
                campanhas_filtradas.append(dados_campanha)
                # Armazenar dados completos para uso posterior
                campanhas_completas_data[campanha["id"]] = dados_campanha
            else:
                # Processar como CBO (código original)
                insight = next((i for i in insights if i.get("campaign_id") == campanha.get("id")), None)
                
                if insight:
                    gasto = float(insight.get("spend", 0))
                    valor_conversao = sum(
                        float(a.get("value", 0))
                        for a in insight.get("action_values", [])
                        if a.get("action_type") in ['offsite_conversion.purchase', 'offsite_conversion.fb_pixel_purchase']
                    )
                else:
                    gasto = 0.0
                    valor_conversao = 0.0
                
                daily_budget = float(campanha.get("daily_budget", 0)) / 100
                lucro = valor_conversao - gasto
                roas = round(valor_conversao / gasto, 2) if gasto > 0 else 0
                
                # Classificação baseada no lucro
                if lucro < LIMITE_LUCRO_BAIXO:
                    classificacao = "BAIXO"
                elif lucro >= LIMITE_LUCRO_ALTO:
                    classificacao = "ALTO"
                else:
                    classificacao = "MÉDIO"
                
                dados_campanha = {
                    "id_conta": ad_account,
                    "id_campanha": campanha["id"],
                    "nome_campanha": campanha["name"],
                    "tipo_campanha": "CBO",
                    "orcamento_diario": daily_budget,
                    "gasto": gasto,
                    "valor_conversao": valor_conversao,
                    "roas": roas,
                    "lucro": lucro,
                    "classificacao": classificacao,
                    "adsets_info": None,
                    "detalhes_adsets": "N/A"
                }
                
                campanhas_filtradas.append(dados_campanha)
                campanhas_completas_data[campanha["id"]] = dados_campanha
    
    return campanhas_filtradas

def salvar_campanhas_excel(campanhas):
    if not os.path.exists(SPREADSHEET_PATH):
        criar_planilha()
    
    try:
        workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
        sheet = workbook["CAMPANHAS"]
        
        for campanha in campanhas:
            sheet.append([
                campanha["id_conta"],
                campanha["id_campanha"],
                campanha["nome_campanha"],
                campanha.get("tipo_campanha", "CBO"),
                campanha["orcamento_diario"],
                campanha["gasto"],
                campanha["valor_conversao"],
                campanha["roas"],
                campanha["lucro"],
                "",  # Novo orçamento
                campanha["classificacao"],
                campanha.get("detalhes_adsets", "")
            ])
        
        workbook.save(SPREADSHEET_PATH)
        log_message(f"Dados de {len(campanhas)} campanhas salvos na planilha.")
    except Exception as e:
        log_message(f"[ERRO] Falha ao salvar planilha: {e}")

def atualizar_orcamento_adset(adset_id, novo_orcamento):
    """Atualiza o orçamento de um ad set específico"""
    url = f"https://graph.facebook.com/v17.0/{adset_id}"
    payload = {
        "daily_budget": int(novo_orcamento * 100),
        "access_token": ACCESS_TOKEN
    }
    
    try:
        log_message(f"Atualizando orçamento do AdSet {adset_id} para R$ {novo_orcamento:.2f}")
        response = requests.post(url, data=payload)
        result = response.json()
        
        if result.get("success"):
            log_message(f"Orçamento do AdSet {adset_id} atualizado com sucesso")
            return True
        else:
            erro_msg = result.get('error', {}).get('message', 'Erro desconhecido')
            log_message(f"[ERRO] Falha ao atualizar AdSet {adset_id}: {erro_msg}")
            return False
    except requests.exceptions.RequestException as e:
        log_message(f"[ERRO] Erro na requisição para atualizar AdSet {adset_id}: {e}")
        return False

def atualizar_orcamento_facebook(id_campanha, novo_orcamento):
    """Atualiza o orçamento de campanhas CBO"""
    url = f"https://graph.facebook.com/v17.0/{id_campanha}"
    payload = {
        "daily_budget": int(novo_orcamento * 100),
        "access_token": ACCESS_TOKEN
    }
    try:
        log_message(f"Enviando atualização de orçamento para campanha {id_campanha}")
        response = requests.post(url, data=payload)
        result = response.json()
        log_message(f"Resposta da API: {result}")
        if result.get("success"):
            log_message(f"Orçamento atualizado para a campanha {id_campanha}: R$ {novo_orcamento:.2f}")
            return True
        else:
            log_message(f"[ERRO] Falha ao atualizar campanha {id_campanha}: {result.get('error', {}).get('message')}")
            return False
    except requests.exceptions.RequestException as e:
        log_message(f"[ERRO] Erro na requisição para atualizar orçamento: {e}")
        return False

def calcular_orcamento_total():
    try:
        workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
        sheet = workbook["CAMPANHAS"]
        total = 0
        for row in sheet.iter_rows(min_row=2, values_only=True):
            novo_orcamento = row[9] if row[9] is not None and row[9] != "" else row[4]
            total += novo_orcamento
        return total
    except Exception as e:
        log_message(f"[ERRO] Falha ao calcular orçamento total: {e}")
        return 0

def realocar_orcamentos():
    """Realoca orçamentos entre unidades de baixo e alto lucro (CBO + AdSets ABO)"""
    if not os.path.exists(SPREADSHEET_PATH):
        log_message("[ERRO] Planilha de campanhas não encontrada.")
        return False
    
    workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
    if "CAMPANHAS" not in workbook.sheetnames:
        log_message("[ERRO] Aba 'CAMPANHAS' não encontrada na planilha.")
        return False
    
    sheet = workbook["CAMPANHAS"]
    
    # Lista unificada de unidades para reduzir e aumentar
    unidades_baixo_lucro = []
    unidades_alto_lucro = []
    
    # Processar todas as campanhas
    for row_index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        id_campanha = row[1]
        nome_campanha = row[2]
        tipo_campanha = row[3] if len(row) > 3 else "CBO"
        orcamento = row[4]
        lucro = row[8]
        
        if tipo_campanha == "ABO":
            # Para ABO, processar cada AdSet individualmente
            campanha_completa = campanhas_completas_data.get(id_campanha)
            if campanha_completa and campanha_completa.get("adsets_info"):
                log_message(f"Analisando AdSets da campanha ABO: {nome_campanha}")
                
                for adset in campanha_completa["adsets_info"]:
                    adset_lucro = adset.get('lucro', 0)
                    
                    unidade = {
                        "tipo": "ABO_ADSET",
                        "linha_index": row_index,
                        "id_campanha": id_campanha,
                        "id_adset": adset['adset_id'],
                        "nome": f"{nome_campanha} - {adset['adset_name']}",
                        "nome_campanha": nome_campanha,
                        "orcamento_atual": adset['daily_budget'],
                        "lucro": adset_lucro,
                        "adset_info": adset,
                        "campanha_info": campanha_completa
                    }
                    
                    if adset_lucro < LIMITE_LUCRO_BAIXO:
                        unidades_baixo_lucro.append(unidade)
                    elif adset_lucro >= LIMITE_LUCRO_ALTO:
                        unidades_alto_lucro.append(unidade)
        else:
            # Para CBO, usar a campanha inteira
            if lucro is not None:
                unidade = {
                    "tipo": "CBO",
                    "linha_index": row_index,
                    "id_campanha": id_campanha,
                    "nome": nome_campanha,
                    "nome_campanha": nome_campanha,
                    "orcamento_atual": orcamento,
                    "lucro": lucro
                }
                
                if lucro < LIMITE_LUCRO_BAIXO:
                    unidades_baixo_lucro.append(unidade)
                elif lucro >= LIMITE_LUCRO_ALTO:
                    unidades_alto_lucro.append(unidade)
    
    # Ordenar unidades
    unidades_baixo_lucro.sort(key=lambda x: x["lucro"])  # Piores primeiro
    unidades_alto_lucro.sort(key=lambda x: x["lucro"], reverse=True)  # Melhores primeiro
    
    log_message(f"[INFO] Unidades identificadas:")
    log_message(f"- Com lucro baixo (< R$ {LIMITE_LUCRO_BAIXO:.2f}): {len(unidades_baixo_lucro)}")
    log_message(f"  - Campanhas CBO: {sum(1 for u in unidades_baixo_lucro if u['tipo'] == 'CBO')}")
    log_message(f"  - AdSets ABO: {sum(1 for u in unidades_baixo_lucro if u['tipo'] == 'ABO_ADSET')}")
    log_message(f"- Com lucro alto (>= R$ {LIMITE_LUCRO_ALTO:.2f}): {len(unidades_alto_lucro)}")
    log_message(f"  - Campanhas CBO: {sum(1 for u in unidades_alto_lucro if u['tipo'] == 'CBO')}")
    log_message(f"  - AdSets ABO: {sum(1 for u in unidades_alto_lucro if u['tipo'] == 'ABO_ADSET')}")
    
    if not unidades_baixo_lucro or not unidades_alto_lucro:
        log_message("Não há unidades suficientes para realocação.")
        return False
    
    # Reduzir orçamentos das unidades com baixo lucro
    total_reducao = 0
    unidades_reduzidas = []
    campanhas_abo_modificadas = {}  # Para rastrear mudanças nas campanhas ABO
    
    for unidade in unidades_baixo_lucro:
        if unidade["tipo"] == "ABO_ADSET":
            # Reduzir AdSet ABO
            adset = unidade["adset_info"]
            reducao = adset['daily_budget'] * PERCENTUAL_REALOCACAO
            novo_orcamento = max(adset['daily_budget'] - reducao, MINIMO_ORCAMENTO_ABO)
            reducao_real = adset['daily_budget'] - novo_orcamento
            
            if reducao_real > 0 and atualizar_orcamento_adset(unidade["id_adset"], novo_orcamento):
                total_reducao += reducao_real
                unidades_reduzidas.append({
                    "nome": unidade['nome'],
                    "tipo": "ABO AdSet",
                    "reducao": reducao_real,
                    "de": adset['daily_budget'],
                    "para": novo_orcamento
                })
                
                # Rastrear mudanças na campanha
                if unidade["id_campanha"] not in campanhas_abo_modificadas:
                    campanhas_abo_modificadas[unidade["id_campanha"]] = {
                        "linha_index": unidade["linha_index"],
                        "orcamento_original": unidade["campanha_info"]["orcamento_diario"],
                        "mudanca_total": 0
                    }
                campanhas_abo_modificadas[unidade["id_campanha"]]["mudanca_total"] -= reducao_real
                
        else:  # CBO
            # Reduzir campanha CBO
            reducao = unidade["orcamento_atual"] * PERCENTUAL_REALOCACAO
            novo_orcamento = max(unidade["orcamento_atual"] - reducao, MINIMO_ORCAMENTO)
            reducao_real = unidade["orcamento_atual"] - novo_orcamento
            
            if atualizar_orcamento_facebook(unidade["id_campanha"], novo_orcamento):
                total_reducao += reducao_real
                sheet.cell(row=unidade["linha_index"], column=10).value = novo_orcamento
                unidades_reduzidas.append({
                    "nome": unidade['nome'],
                    "tipo": "CBO",
                    "reducao": reducao_real,
                    "de": unidade["orcamento_atual"],
                    "para": novo_orcamento
                })
    
    # Distribuir o valor reduzido entre as unidades com alto lucro
    unidades_aumentadas = []
    
    if total_reducao > 0 and unidades_alto_lucro:
        soma_lucro_alto = sum(u["lucro"] for u in unidades_alto_lucro)
        
        for unidade in unidades_alto_lucro:
            # Distribuir proporcionalmente ao lucro
            proporcao = unidade["lucro"] / soma_lucro_alto if soma_lucro_alto > 0 else 1.0 / len(unidades_alto_lucro)
            incremento = total_reducao * proporcao
            
            if unidade["tipo"] == "ABO_ADSET":
                # Aumentar AdSet ABO
                adset = unidade["adset_info"]
                novo_orcamento = min(adset['daily_budget'] + incremento, MAXIMO_ORCAMENTO)
                incremento_real = novo_orcamento - adset['daily_budget']
                
                if incremento_real > 0 and atualizar_orcamento_adset(unidade["id_adset"], novo_orcamento):
                    unidades_aumentadas.append({
                        "nome": unidade['nome'],
                        "tipo": "ABO AdSet",
                        "aumento": incremento_real,
                        "de": adset['daily_budget'],
                        "para": novo_orcamento
                    })
                    
                    # Rastrear mudanças na campanha
                    if unidade["id_campanha"] not in campanhas_abo_modificadas:
                        campanhas_abo_modificadas[unidade["id_campanha"]] = {
                            "linha_index": unidade["linha_index"],
                            "orcamento_original": unidade["campanha_info"]["orcamento_diario"],
                            "mudanca_total": 0
                        }
                    campanhas_abo_modificadas[unidade["id_campanha"]]["mudanca_total"] += incremento_real
                    
            else:  # CBO
                # Aumentar campanha CBO
                novo_orcamento = min(unidade["orcamento_atual"] + incremento, MAXIMO_ORCAMENTO)
                incremento_real = novo_orcamento - unidade["orcamento_atual"]
                
                if atualizar_orcamento_facebook(unidade["id_campanha"], novo_orcamento):
                    sheet.cell(row=unidade["linha_index"], column=10).value = novo_orcamento
                    unidades_aumentadas.append({
                        "nome": unidade['nome'],
                        "tipo": "CBO",
                        "aumento": incremento_real,
                        "de": unidade["orcamento_atual"],
                        "para": novo_orcamento
                    })
    
    # Atualizar orçamentos totais das campanhas ABO na planilha
    for id_campanha, info in campanhas_abo_modificadas.items():
        novo_orcamento_total = info["orcamento_original"] + info["mudanca_total"]
        sheet.cell(row=info["linha_index"], column=10).value = novo_orcamento_total
    
    # Salvar planilha
    workbook.save(SPREADSHEET_PATH)
    
    # Calcular orçamento total atual
    total_orcamento_atual = calcular_orcamento_total()
    
    # Preparar mensagem detalhada
    mensagem = (
        f"✅ REALOCAÇÃO CONCLUÍDA!\n\n"
        f"📊 RESUMO DA OPERAÇÃO\n"
        f"{'='*30}\n\n"
        f"⚙️ PARÂMETROS UTILIZADOS:\n"
        f"• Lucro baixo: < R$ {LIMITE_LUCRO_BAIXO:.2f}\n"
        f"• Lucro alto: ≥ R$ {LIMITE_LUCRO_ALTO:.2f}\n"
        f"• Percentual: {int(PERCENTUAL_REALOCACAO * 100)}%\n\n"
        f"📉 REDUÇÕES ({len(unidades_reduzidas)} unidades)\n"
        f"{'='*30}\n"
        f"💰 Total reduzido: R$ {total_reducao:.2f}\n\n"
    )
    
    # Top 5 reduções
    unidades_reduzidas.sort(key=lambda x: x['reducao'], reverse=True)
    for i, u in enumerate(unidades_reduzidas[:5]):
        mensagem += f"{i+1}. {u['nome'][:40]}... ({u['tipo']})\n"
        mensagem += f"   R$ {u['de']:.2f} → R$ {u['para']:.2f} (-R$ {u['reducao']:.2f})\n\n"
    
    if len(unidades_reduzidas) > 5:
        mensagem += f"... e mais {len(unidades_reduzidas) - 5} unidades\n\n"
    
    mensagem += (
        f"📈 AUMENTOS ({len(unidades_aumentadas)} unidades)\n"
        f"{'='*30}\n"
        f"💰 Total distribuído: R$ {sum(u['aumento'] for u in unidades_aumentadas):.2f}\n\n"
    )
    
    # Top 5 aumentos
    unidades_aumentadas.sort(key=lambda x: x['aumento'], reverse=True)
    for i, u in enumerate(unidades_aumentadas[:5]):
        mensagem += f"{i+1}. {u['nome'][:40]}... ({u['tipo']})\n"
        mensagem += f"   R$ {u['de']:.2f} → R$ {u['para']:.2f} (+R$ {u['aumento']:.2f})\n\n"
    
    if len(unidades_aumentadas) > 5:
        mensagem += f"... e mais {len(unidades_aumentadas) - 5} unidades\n\n"
    
    mensagem += (
        f"📊 ESTATÍSTICAS FINAIS\n"
        f"{'='*30}\n"
        f"• Orçamento total: R$ {total_orcamento_atual:.2f}\n"
        f"• Unidades CBO reduzidas: {sum(1 for u in unidades_reduzidas if u['tipo'] == 'CBO')}\n"
        f"• AdSets ABO reduzidos: {sum(1 for u in unidades_reduzidas if u['tipo'] == 'ABO AdSet')}\n"
        f"• Unidades CBO aumentadas: {sum(1 for u in unidades_aumentadas if u['tipo'] == 'CBO')}\n"
        f"• AdSets ABO aumentados: {sum(1 for u in unidades_aumentadas if u['tipo'] == 'ABO AdSet')}\n"
    )
    
    # Log resumo
    log_message("[RESUMO] Realocação concluída:")
    log_message(f"[RESUMO] Total reduzido: R$ {total_reducao:.2f}")
    log_message(f"[RESUMO] Unidades reduzidas: {len(unidades_reduzidas)}")
    log_message(f"[RESUMO] Unidades aumentadas: {len(unidades_aumentadas)}")
    
    # Enviar relatório via WhatsApp com timeout maior
    sucesso_whatsapp = enviar_mensagem_whatsapp(WHATSAPP_GROUP, mensagem)
    
    if not sucesso_whatsapp:
        log_message(f"[AVISO] Falha ao enviar mensagem WhatsApp, mas a realocação foi concluída")
    else:
        log_message(f"[INFO] Mensagem enviada com sucesso")
    
    log_message("Processo de realocação concluído com sucesso!")
    return True

def limpar_mensagem_whatsapp(mensagem):
    """Remove caracteres especiais e emojis que podem causar problemas no WhatsApp Web"""
    import re
    
    # Substituir emojis específicos por texto
    substituicoes = {
        '✅': '[OK]',
        '💰': '[$$]',
        '📊': '[DADOS]',
        '📈': '[SUBIU]',
        '📉': '[DESCEU]',
        '🔥': '[HOT]',
        '⚙️': '[CONFIG]',
        '🎯': '[ALVO]',
        '🔄': '[CICLO]',
        '•': '-',
        '→': '->',
        '='*30: '-'*30
    }
    
    for emoji, texto in substituicoes.items():
        mensagem = mensagem.replace(emoji, texto)
    
    # Remover outros caracteres Unicode problemáticos
    mensagem = ''.join(char for char in mensagem if ord(char) < 256)
    
    return mensagem

def enviar_mensagem_whatsapp(grupo, mensagem_original):
    """Função para enviar mensagens para um grupo do WhatsApp com melhor tratamento de timeout"""
    # Limpar mensagem antes de enviar
    mensagem = limpar_mensagem_whatsapp(mensagem_original)
    
    log_message(f"Iniciando envio de mensagem para o grupo: {grupo}")
    log_message(f"Tamanho da mensagem: {len(mensagem)} caracteres")
    
    driver = None
    
    try:
        # Configuração do navegador Chrome/Brave
        brave_options = Options()
        brave_options.binary_location = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
        brave_options.add_argument(r"--user-data-dir=C:\Users\Pichau\AppData\Local\BraveSoftware\Brave-Browser\User Data")
        brave_options.add_argument(r"--profile-directory=Default")
        brave_options.add_argument("--start-maximized")
        brave_options.add_argument("--window-size=1920,1080")
        brave_options.add_argument("--disable-blink-features=AutomationControlled")
        brave_options.add_argument("--disable-extensions")
        brave_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        brave_options.add_experimental_option("useAutomationExtension", False)
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=brave_options)
        
        # Remover flag navigator.webdriver
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
            """
        })
        
        # Abrir WhatsApp Web
        log_message("Abrindo WhatsApp Web...")
        driver.get("https://web.whatsapp.com")
        
        # Aguardar carregamento inicial mais longo
        time.sleep(5)
        
        # Verificar se o WhatsApp Web carregou
        whatsapp_loaded = False
        for attempt in range(3):
            try:
                # Tentar encontrar elemento que indica carregamento completo
                WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='textbox'][aria-label='Caixa de texto de pesquisa']"))
                )
                whatsapp_loaded = True
                log_message("WhatsApp Web carregado com sucesso")
                break
            except:
                log_message(f"Tentativa {attempt + 1} de carregar WhatsApp Web...")
                time.sleep(5)
        
        if not whatsapp_loaded:
            log_message("Falha ao carregar WhatsApp Web")
            return False
        
        # Aguardar estabilização da página
        time.sleep(3)
        
        # Encontrar campo de pesquisa
        search_element = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div[role='textbox'][aria-label='Caixa de texto de pesquisa']"))
        )
        
        # Clicar e pesquisar grupo
        search_element.click()
        time.sleep(1)
        search_element.clear()
        search_element.send_keys(grupo)
        log_message(f"Pesquisando grupo: {grupo}")
        
        # Aguardar resultados da pesquisa
        time.sleep(4)
        
        # Clicar no grupo
        group_element = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, f"//span[@title='{grupo}']"))
        )
        group_element.click()
        log_message("Grupo encontrado e clicado")
        
        # Aguardar conversa abrir
        time.sleep(3)
        
        # Encontrar campo de mensagem
        message_box = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@role='textbox' and @data-tab='10']"))
        )
        
        # Dividir mensagem em partes menores se for muito grande
        max_chars = 4000
        if len(mensagem) > max_chars:
            log_message(f"Mensagem muito grande, dividindo em partes...")
            partes = [mensagem[i:i+max_chars] for i in range(0, len(mensagem), max_chars)]
            
            for i, parte in enumerate(partes):
                log_message(f"Enviando parte {i+1} de {len(partes)}...")
                message_box.click()
                time.sleep(1)
                message_box.clear()
                message_box.send_keys(parte)
                time.sleep(2)
                message_box.send_keys(Keys.ENTER)
                time.sleep(3)
        else:
            # Enviar mensagem inteira
            message_box.click()
            time.sleep(1)
            message_box.clear()
            
            # Digitar mensagem em blocos para evitar problemas
            for i in range(0, len(mensagem), 500):
                message_box.send_keys(mensagem[i:i+500])
                time.sleep(0.5)
            
            log_message("Mensagem digitada, enviando...")
            time.sleep(2)
            
            # Enviar mensagem
            message_box.send_keys(Keys.ENTER)
        
        # Aguardar confirmação de envio
        time.sleep(5)
        
        log_message("Processo de envio concluído")
        return True
        
    except Exception as e:
        log_message(f"Erro ao enviar mensagem no WhatsApp: {e}")
        if driver:
            try:
                driver.save_screenshot("whatsapp_error_realocar.png")
            except:
                pass
        return False
        
    finally:
        if driver:
            try:
                # Dar tempo para mensagem ser enviada antes de fechar
                time.sleep(3)
                driver.quit()
            except:
                pass

def run(token, accounts, group, logs, date_range='today', start_date=None, end_date=None, low_profit=None, high_profit=None, realloc_pct=None, abo_accounts=None):
    """
    Função principal com suporte a ABO
    """
    global ACCESS_TOKEN, AD_ACCOUNTS, WHATSAPP_GROUP, DATE_PRESET, LIMITE_LUCRO_BAIXO, LIMITE_LUCRO_ALTO, PERCENTUAL_REALOCACAO, logs_list, ABO_ACCOUNTS
    
    ACCESS_TOKEN = token
    AD_ACCOUNTS = accounts if accounts is not None else []
    WHATSAPP_GROUP = group
    logs_list = logs
    
    # Definir contas ABO se fornecidas
    if abo_accounts:
        ABO_ACCOUNTS = abo_accounts
        # IMPORTANTE: Adicionar contas ABO à lista de contas a processar
        # para garantir que sejam incluídas no processamento
        for conta_abo in abo_accounts:
            if conta_abo not in AD_ACCOUNTS:
                AD_ACCOUNTS.append(conta_abo)
                log_message(f"Conta ABO {conta_abo} adicionada à lista de processamento")
    
    # Limpar dados de campanhas anteriores
    global campanhas_completas_data
    campanhas_completas_data = {}
    
    if date_range == 'custom' and start_date and end_date:
        DATE_PRESET = None
    else:
        presets = {'today': 'today', 'yesterday': 'yesterday', 'last7': 'last_7d'}
        DATE_PRESET = presets.get(date_range, 'today')
    
    if low_profit is not None:
        LIMITE_LUCRO_BAIXO = float(low_profit)
    if high_profit is not None:
        LIMITE_LUCRO_ALTO = float(high_profit)
    if realloc_pct is not None:
        PERCENTUAL_REALOCACAO = float(realloc_pct) if float(realloc_pct) <= 1.0 else float(realloc_pct)/100.0
    
    log_message("Iniciando realocação com: Token=" + token[:5] + "..." + token[-5:] + 
               f", Contas={AD_ACCOUNTS}, Grupo={group}")
    log_message(f"Parâmetros: Date Range={date_range}, Low Profit={low_profit}, High Profit={high_profit}, Realloc %={realloc_pct}")
    log_message(f"Contas ABO configuradas: {ABO_ACCOUNTS}")
    
    try:
        limpar_planilha()
        todas_campanhas = []
        
        # Processar TODAS as contas (incluindo ABO)
        for ad_account in AD_ACCOUNTS:
            tipo_conta = "ABO" if ad_account in ABO_ACCOUNTS else "CBO"
            log_message(f"Processando conta de anúncio {tipo_conta}: {ad_account}")
            log_message(f"Buscando campanhas para conta {ad_account}...")
            
            campaigns_url = f"https://graph.facebook.com/v17.0/{ad_account}/campaigns?fields=id,name,daily_budget,status&access_token={ACCESS_TOKEN}"
            
            if date_range == 'custom' and start_date and end_date:
                insights_url = (
                    f"https://graph.facebook.com/v17.0/{ad_account}/insights?fields=campaign_id,campaign_name,spend,action_values"
                    f"&time_range[since]={start_date}&time_range[until]={end_date}&level=campaign&access_token={ACCESS_TOKEN}"
                )
            else:
                insights_url = (
                    f"https://graph.facebook.com/v17.0/{ad_account}/insights?fields=campaign_id,campaign_name,spend,action_values"
                    f"&date_preset={DATE_PRESET}&level=campaign&access_token={ACCESS_TOKEN}"
                )
            
            campaigns = buscar_todos_dados_facebook(campaigns_url)
            log_message(f"Encontradas {len(campaigns)} campanhas.")
            
            insights = buscar_todos_dados_facebook(insights_url)
            log_message(f"Encontrados {len(insights)} insights.")
            
            # Processar campanhas com suporte a ABO
            campanhas_processadas = processar_dados_campanhas(
                campaigns, insights, ad_account,
                DATE_PRESET if DATE_PRESET else None,
                start_date if date_range == 'custom' else None,
                end_date if date_range == 'custom' else None
            )
            
            log_message(f"Processadas {len(campanhas_processadas)} campanhas ativas.")
            
            # Log detalhado para campanhas ABO
            if ad_account in ABO_ACCOUNTS:
                campanhas_abo_desta_conta = [c for c in campanhas_processadas if c.get("tipo_campanha") == "ABO"]
                if campanhas_abo_desta_conta:
                    for camp in campanhas_abo_desta_conta:
                        log_message(f"  - Campanha ABO: {camp['nome_campanha']} com {len(camp.get('adsets_info', []))} adsets")
            
            todas_campanhas.extend(campanhas_processadas)
        
        log_message(f"Total de {len(todas_campanhas)} campanhas ativas encontradas.")
        
        # Contar campanhas por tipo
        campanhas_cbo = [c for c in todas_campanhas if c.get("tipo_campanha") == "CBO"]
        campanhas_abo = [c for c in todas_campanhas if c.get("tipo_campanha") == "ABO"]
        log_message(f"Campanhas CBO: {len(campanhas_cbo)}, Campanhas ABO: {len(campanhas_abo)}")
        
        # Log detalhado de campanhas ABO
        if campanhas_abo:
            total_adsets = sum(len(c.get("adsets_info", [])) for c in campanhas_abo)
            log_message(f"Total de AdSets em campanhas ABO: {total_adsets}")
        
        salvar_campanhas_excel(todas_campanhas)
        
        resultado = realocar_orcamentos()
        return resultado
        
    except Exception as e:
        log_message(f"Erro durante o processo de realocação: {e}")
        import traceback
        log_message(traceback.format_exc())
        return False

if __name__ == "__main__":
    limpar_planilha()
    todas_campanhas = []
    
    for ad_account in AD_ACCOUNTS:
        log_message(f"[INFO] Processando conta de anúncio: {ad_account}")
        campaigns_url = f"https://graph.facebook.com/v17.0/{ad_account}/campaigns?fields=id,name,daily_budget,status&access_token={ACCESS_TOKEN}"
        insights_url = f"https://graph.facebook.com/v17.0/{ad_account}/insights?fields=campaign_id,campaign_name,spend,action_values&date_preset={DATE_PRESET}&level=campaign&access_token={ACCESS_TOKEN}"
        
        campaigns = buscar_todos_dados_facebook(campaigns_url)
        insights = buscar_todos_dados_facebook(insights_url)
        
        campanhas_processadas = processar_dados_campanhas(
            campaigns, insights, ad_account, DATE_PRESET
        )
        todas_campanhas.extend(campanhas_processadas)
    
    salvar_campanhas_excel(todas_campanhas)
    realocar_orcamentos()