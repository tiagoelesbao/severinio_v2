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
        logging.FileHandler("escala_lucro.log"),
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

# Leitura de config.json (não altera valores aqui – são passados via run())
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    default_config = {
        "ACCESS_TOKEN": "",
        "AD_ACCOUNTS": [],
        "LIMITE_LUCRO": 1,
        "VALOR_TOTAL_ESCALA": 1000,
        "MINIMO_ORCAMENTO": 100,
        "WHATSAPP_GROUP": "#ZIP - ROAS IMPERIO",
        "DATE_PRESET": "today"
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=4, ensure_ascii=False)
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

ACCESS_TOKEN = config.get("ACCESS_TOKEN", "")
AD_ACCOUNTS = config.get("AD_ACCOUNTS", [])
SPREADSHEET_PATH = "campanhas_lucro.xlsx"
LIMITE_LUCRO = float(config.get("LIMITE_LUCRO", 1))
VALOR_TOTAL_ESCALA = float(config.get("VALOR_TOTAL_ESCALA", 10000))
MINIMO_ORCAMENTO = float(config.get("MINIMO_ORCAMENTO", 100))
WHATSAPP_GROUP = config.get("WHATSAPP_GROUP", "#ZIP - ROAS IMPERIO")
DATE_PRESET = config.get("DATE_PRESET", "today")

def criar_planilha():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "CAMPANHAS"
    sheet.append([
        "ID da Conta de Anúncio", "ID da Campanha", "Nome da Campanha",
        "Orçamento Diário", "Gasto", "Valor de Conversões",
        "ROAS", "Lucro", "Novo Orçamento"
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
        log_message("Planilha não encontrada. Será criada uma nova ao salvar os dados.")
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

def processar_dados_campanhas(campanhas, insights, ad_account):
    campanhas_filtradas = []
    for campanha in campanhas:
        # Apenas processa campanhas ativas (sem log para cada campanha)
        if campanha.get("status", "").upper().strip() == "ACTIVE":
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
            campanhas_filtradas.append({
                "id_conta": ad_account,
                "id_campanha": campanha["id"],
                "nome_campanha": campanha["name"],
                "orcamento_diario": daily_budget,
                "gasto": gasto,
                "valor_conversao": valor_conversao,
                "roas": roas,
                "lucro": lucro
            })
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
                campanha["orcamento_diario"],
                campanha["gasto"],
                campanha["valor_conversao"],
                campanha["roas"],
                campanha["lucro"],
                ""
            ])
        workbook.save(SPREADSHEET_PATH)
        log_message("Dados das campanhas salvos na planilha.")
    except Exception as e:
        log_message(f"[ERRO] Falha ao salvar planilha: {e}")

def calcular_orcamento_total():
    try:
        workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
        sheet = workbook["CAMPANHAS"]
        total = 0
        for row in sheet.iter_rows(min_row=2, values_only=True):
            novo_orcamento = row[8] if row[8] is not None else row[3]
            total += novo_orcamento
        return total
    except Exception as e:
        log_message(f"[ERRO] Falha ao calcular orçamento total: {e}")
        return 0

def escalar_campanhas():
    if not os.path.exists(SPREADSHEET_PATH):
        log_message("[ERRO] Planilha de campanhas não encontrada.")
        return False
    
    workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
    if "CAMPANHAS" not in workbook.sheetnames:
        log_message("[ERRO] Aba 'CAMPANHAS' não encontrada na planilha.")
        return False
    
    sheet = workbook["CAMPANHAS"]
    campanhas_para_escalar = []
    for row_index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        lucro = row[7]
        if lucro is not None and lucro >= LIMITE_LUCRO:
            campanhas_para_escalar.append({
                "linha_index": row_index,
                "id_campanha": row[1],
                "orcamento_diario": row[3],
                "lucro": row[7]
            })
    
    if not campanhas_para_escalar:
        log_message("[INFO] Nenhuma campanha para escalar.")
        return False
    
    soma_lucro = sum(c["lucro"] for c in campanhas_para_escalar)
    log_message(f"[INFO] {len(campanhas_para_escalar)} campanhas para escalonamento. Soma dos lucros: R$ {soma_lucro:.2f}")
    
    campanhas_escaladas = 0
    for campanha in campanhas_para_escalar:
        if soma_lucro > 0:
            proporcao = campanha["lucro"] / soma_lucro
            incremento = VALOR_TOTAL_ESCALA * proporcao
        else:
            incremento = VALOR_TOTAL_ESCALA / len(campanhas_para_escalar)
        
        novo_orcamento = max(campanha["orcamento_diario"] + incremento, MINIMO_ORCAMENTO)
        resultado = atualizar_orcamento_facebook(campanha["id_campanha"], novo_orcamento)
        
        if resultado:
            sheet.cell(row=campanha["linha_index"], column=9).value = novo_orcamento
            log_message(f"Campanha {campanha['id_campanha']} escalada para R$ {novo_orcamento:.2f}")
            campanhas_escaladas += 1
    
    workbook.save(SPREADSHEET_PATH)
    total_orcamento_atual = calcular_orcamento_total()
    
    mensagem = (
        f"Escala realizada: R$ {VALOR_TOTAL_ESCALA:.2f} distribuídos entre {campanhas_escaladas} campanhas "
        f"com lucro >= R$ {LIMITE_LUCRO:.2f}. Orçamento total atual: R$ {total_orcamento_atual:.2f}."
    )
    
    sucesso_whatsapp = enviar_mensagem_whatsapp(WHATSAPP_GROUP, mensagem)
    
    if not sucesso_whatsapp:
        log_message(f"[AVISO] Falha ao enviar mensagem WhatsApp, mas a escala foi concluída: {mensagem}")
    else:
        log_message(f"[INFO] Mensagem enviada com sucesso: {mensagem}")
    
    log_message("Processo de escala concluído com sucesso!")
    return True

def atualizar_orcamento_facebook(id_campanha, novo_orcamento):
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

def enviar_mensagem_whatsapp(grupo, mensagem):
    """
    Função atualizada para enviar mensagens para um grupo do WhatsApp Web/Business
    usando os novos seletores da interface.
    
    Args:
        grupo (str): Nome do grupo para enviar a mensagem
        mensagem (str): Texto da mensagem a ser enviada
        
    Returns:
        bool: True se a mensagem foi enviada com sucesso, False caso contrário
    """
    log_message(f"Iniciando envio de mensagem para o grupo: {grupo}")
    driver = None
    
    try:
        # Configuração do navegador Chrome/Brave
        brave_options = Options()
        brave_options.binary_location = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
        # Aumentar estabilidade evitando uso do perfil do usuário que pode estar em uso
        # brave_options.add_argument("--user-data-dir=C:\\temp\\whatsapp_profile")
        # brave_options.add_argument("--profile-directory=WhatsApp")
        brave_options.add_argument("--start-maximized")
        # Adicionar opção para evitar detecção de automação
        brave_options.add_argument("--disable-blink-features=AutomationControlled")
        brave_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        brave_options.add_experimental_option("useAutomationExtension", False)
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=brave_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Abrir WhatsApp Web
        log_message("Abrindo WhatsApp Web...")
        driver.get("https://web.whatsapp.com")
        
        # Aguardar carregamento inicial (elemento do painel lateral)
        log_message("Aguardando carregamento do WhatsApp Web...")
        pane_side = WebDriverWait(driver, 360).until(
            EC.presence_of_element_located((By.ID, "pane-side"))
        )
        log_message("WhatsApp Web carregado, procurando campo de pesquisa...")
        
        # Tentar diversos seletores para o campo de pesquisa (em ordem de especificidade)
        search_selectors = [
            # Seletor que você compartilhou
            "div.x1n2onr6.xh8yej3.lexical-rich-text-input div[aria-label='Caixa de texto de pesquisa'][role='textbox'][data-tab='3']",
            # Alternativas
            "div[aria-label='Caixa de texto de pesquisa'][role='textbox']",
            "div.lexical-rich-text-input div[role='textbox'][data-tab='3']",
            "div[data-tab='3'][role='textbox']",
            "div[aria-placeholder='Pesquisar ou começar uma nova conversa']"
        ]
        
        search_box = None
        for selector in search_selectors:
            try:
                search_box = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                log_message(f"Campo de pesquisa encontrado com seletor: {selector}")
                break
            except:
                continue
        
        if not search_box:
            # Última tentativa - tentar clicar no campo baseado em coordenadas
            log_message("Tentando clicar na área de pesquisa...")
            try:
                # Clique na região onde geralmente fica o campo de pesquisa
                search_area = driver.find_element(By.CSS_SELECTOR, "div#pane-side")
                driver.execute_script("arguments[0].scrollIntoView();", search_area)
                actions = webdriver.ActionChains(driver)
                actions.move_to_element_with_offset(search_area, 150, -50).click().perform()
                time.sleep(2)
            except Exception as e:
                log_message(f"Falha ao clicar na área de pesquisa: {e}")
                driver.save_screenshot("campo_pesquisa_nao_encontrado.png")
                raise Exception("Campo de pesquisa não encontrado")
        
        # Limpar campo de pesquisa (se necessário) e digitar nome do grupo
        time.sleep(1)  # Pequena pausa para garantir que o campo está pronto
        if search_box:
            search_box.clear()
            search_box.send_keys(grupo)
        else:
            # Se usou o clique por coordenadas, digitar diretamente
            actions = webdriver.ActionChains(driver)
            actions.send_keys(grupo)
            actions.perform()
        
        log_message(f"Pesquisando pelo grupo: {grupo}")
        time.sleep(3)  # Aguardar a pesquisa carregar resultados
        
        # Localizar e clicar no grupo/contato - usando o novo seletor
        group_selectors = [
            f"div[aria-selected='true'] span[title='{grupo}']",
            f"div[aria-selected='true'] div[title='{grupo}']",
            f"div._ak72 span[title='{grupo}']",
            f"div span[title='{grupo}']",
            f"div[title='{grupo}']"
        ]
        
        group_element = None
        for selector in group_selectors:
            try:
                group_element = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                log_message(f"Grupo encontrado com seletor: {selector}")
                break
            except:
                continue
        
        if not group_element:
            # Tentar clique diretamente no primeiro resultado da pesquisa
            try:
                first_result = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div[aria-selected='true']"))
                )
                first_result.click()
                log_message("Clicado no primeiro resultado da pesquisa")
            except Exception as e:
                log_message(f"Grupo não encontrado: {e}")
                driver.save_screenshot("grupo_nao_encontrado.png")
                raise Exception(f"Grupo/contato '{grupo}' não encontrado")
        else:
            group_element.click()
        
        time.sleep(2)  # Pequena pausa após clicar no grupo
        
        # Localizar o campo de mensagem usando o novo seletor
        log_message("Localizando campo de mensagem...")
        message_selectors = [
            # Seletor que você compartilhou
            "div.x1n2onr6.xh8yej3.xjdcl3y.lexical-rich-text-input div[aria-label='Digite uma mensagem'][role='textbox'][data-tab='10']",
            # Alternativas
            "div[aria-label='Digite uma mensagem'][role='textbox']",
            "div.lexical-rich-text-input div[role='textbox'][data-tab='10']",
            "div[data-tab='10'][role='textbox']",
            "div[aria-placeholder='Digite uma mensagem']"
        ]
        
        message_box = None
        for selector in message_selectors:
            try:
                message_box = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                log_message(f"Campo de mensagem encontrado com seletor: {selector}")
                break
            except:
                continue
        
        if not message_box:
            # Última tentativa - tentar clicar no campo baseado em coordenadas
            log_message("Tentando clicar na área de mensagem...")
            try:
                # Clique na região onde geralmente fica o campo de mensagem
                footer = driver.find_element(By.CSS_SELECTOR, "footer")
                driver.execute_script("arguments[0].scrollIntoView();", footer)
                actions = webdriver.ActionChains(driver)
                actions.move_to_element_with_offset(footer, 200, -30).click().perform()
                time.sleep(1)
            except Exception as e:
                log_message(f"Falha ao clicar na área de mensagem: {e}")
                driver.save_screenshot("campo_mensagem_nao_encontrado.png")
                raise Exception("Campo de mensagem não encontrado")
        
        # Digitar a mensagem
        log_message("Digitando mensagem...")
        if message_box:
            message_box.clear()
            message_box.send_keys(mensagem)
        else:
            # Se usou o clique por coordenadas, digitar diretamente
            actions = webdriver.ActionChains(driver)
            actions.send_keys(mensagem)
            actions.perform()
        
        time.sleep(1)  # Pequena pausa após digitar a mensagem
        
        # Localizar e clicar no botão de enviar usando o novo seletor
        log_message("Enviando mensagem...")
        send_selectors = [
            # Seletor que você compartilhou
            "button[aria-label='Enviar'][data-tab='11']",
            # Alternativas
            "button[aria-label='Enviar']",
            "button[data-icon='wds-ic-send-filled']",
            "button svg[data-icon='wds-ic-send-filled']",
            "span[data-icon='wds-ic-send-filled']"
        ]
        
        send_button = None
        for selector in send_selectors:
            try:
                send_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                log_message(f"Botão de enviar encontrado com seletor: {selector}")
                break
            except:
                continue
        
        if not send_button:
            # Última tentativa - enviar com ENTER
            log_message("Tentando enviar mensagem com ENTER...")
            try:
                actions = webdriver.ActionChains(driver)
                actions.send_keys(Keys.ENTER)
                actions.perform()
            except Exception as e:
                log_message(f"Falha ao enviar mensagem: {e}")
                driver.save_screenshot("botao_enviar_nao_encontrado.png")
                raise Exception("Botão de enviar não encontrado")
        else:
            send_button.click()
        
        # Aguardar um pouco para garantir que a mensagem foi enviada
        time.sleep(20)
        log_message("Mensagem enviada com sucesso!")
        return True
        
    except Exception as e:
        log_message(f"Problema ao enviar mensagem no WhatsApp: {e}")
        if driver:
            try:
                driver.save_screenshot("whatsapp_error_final.png")
            except:
                pass
        return False
        
    finally:
        if driver:
            driver.quit()

def run(token, accounts, group, logs, date_range='today', start_date=None, end_date=None, min_profit=None, scale_value=None):
    """
    Função principal que executa o processo de escala de orçamento
    
    Args:
        token (str): Token de acesso da API do Facebook
        accounts (list): Lista de IDs de contas de anúncios
        group (str): Nome do grupo do WhatsApp para enviar notificações
        logs (list): Lista para armazenar logs
        date_range (str): Período de dados a considerar (today, yesterday, last7, custom)
        start_date (str): Data inicial (se date_range for custom)
        end_date (str): Data final (se date_range for custom)
        min_profit (float): Lucro mínimo para considerar escala
        scale_value (float): Valor total para escalar
        
    Returns:
        bool: True se o processo foi concluído com sucesso, False caso contrário
    """
    global ACCESS_TOKEN, AD_ACCOUNTS, WHATSAPP_GROUP, DATE_PRESET, LIMITE_LUCRO, VALOR_TOTAL_ESCALA, logs_list
    ACCESS_TOKEN = token
    AD_ACCOUNTS = accounts if accounts is not None else []
    WHATSAPP_GROUP = group
    logs_list = logs
    if date_range == 'custom' and start_date and end_date:
        DATE_PRESET = None
    else:
        presets = {'today': 'today', 'yesterday': 'yesterday', 'last7': 'last_7d'}
        DATE_PRESET = presets.get(date_range, 'today')
    if min_profit is not None:
        LIMITE_LUCRO = float(min_profit)
    if scale_value is not None:
        VALOR_TOTAL_ESCALA = float(scale_value)
        
    log_message("Iniciando escala com: Token=" + token[:5] + "..." + token[-5:] + 
               f", Contas={accounts}, Grupo={group}")
    log_message(f"Parâmetros: Date Range={date_range}, Min Profit={min_profit}, Scale Value={scale_value}")
    
    try:
        limpar_planilha()
        todas_campanhas = []
        for ad_account in AD_ACCOUNTS:
            log_message(f"Processando conta de anúncio: {ad_account}")
            log_message(f"Buscando campanhas para conta {ad_account}...")
            campaigns_url = f"https://graph.facebook.com/v17.0/{ad_account}/campaigns?fields=id,name,daily_budget,status&access_token={ACCESS_TOKEN}"
            if date_range == 'custom' and start_date and end_date:
                insights_url = f"https://graph.facebook.com/v17.0/{ad_account}/insights?fields=campaign_id,campaign_name,spend,action_values&time_range[since]={start_date}&time_range[until]={end_date}&level=campaign&access_token={ACCESS_TOKEN}"
            else:
                insights_url = f"https://graph.facebook.com/v17.0/{ad_account}/insights?fields=campaign_id,campaign_name,spend,action_values&date_preset={DATE_PRESET}&level=campaign&access_token={ACCESS_TOKEN}"
            
            campaigns = buscar_todos_dados_facebook(campaigns_url)
            log_message(f"Encontradas {len(campaigns)} campanhas.")
            
            insights = buscar_todos_dados_facebook(insights_url)
            log_message(f"Encontrados {len(insights)} insights.")
            
            campanhas_processadas = processar_dados_campanhas(campaigns, insights, ad_account)
            log_message(f"Processadas {len(campanhas_processadas)} campanhas ativas.")
            
            todas_campanhas.extend(campanhas_processadas)
        
        log_message(f"Total de {len(todas_campanhas)} campanhas ativas encontradas.")
        salvar_campanhas_excel(todas_campanhas)
        
        resultado = escalar_campanhas()
        return resultado
    except Exception as e:
        log_message(f"Erro durante o processo de escala: {e}")
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
        campanhas_processadas = processar_dados_campanhas(campaigns, insights, ad_account)
        todas_campanhas.extend(campanhas_processadas)
    salvar_campanhas_excel(todas_campanhas)
    escalar_campanhas()