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

# Leitura de config.json (não altera valores aqui – são passados via run())
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    default_config = {
        "ACCESS_TOKEN": "",
        "AD_ACCOUNTS": [],
        "LIMITE_LUCRO_BAIXO": 1000,
        "LIMITE_LUCRO_ALTO": 5000,
        "PERCENTUAL_REALOCACAO": 0.30,
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
SPREADSHEET_PATH = "campanhas_realocacao.xlsx"
LIMITE_LUCRO_BAIXO = float(config.get("LIMITE_LUCRO_BAIXO", 1000))
LIMITE_LUCRO_ALTO = float(config.get("LIMITE_LUCRO_ALTO", 5000))
PERCENTUAL_REALOCACAO = float(config.get("PERCENTUAL_REALOCACAO", 0.30))
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
        "ROAS", "Lucro", "Novo Orçamento", "Classificação"
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
            
            # Classificação baseada no lucro
            if lucro < LIMITE_LUCRO_BAIXO:
                classificacao = "BAIXO"
            elif lucro >= LIMITE_LUCRO_ALTO:
                classificacao = "ALTO"
            else:
                classificacao = "MÉDIO"
            
            campanhas_filtradas.append({
                "id_conta": ad_account,
                "id_campanha": campanha["id"],
                "nome_campanha": campanha["name"],
                "orcamento_diario": daily_budget,
                "gasto": gasto,
                "valor_conversao": valor_conversao,
                "roas": roas,
                "lucro": lucro,
                "classificacao": classificacao
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
                "",  # Novo orçamento (será preenchido depois)
                campanha["classificacao"]
            ])
        workbook.save(SPREADSHEET_PATH)
        log_message(f"Dados de {len(campanhas)} campanhas salvos na planilha.")
    except Exception as e:
        log_message(f"[ERRO] Falha ao salvar planilha: {e}")

def calcular_orcamento_total():
    try:
        workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
        sheet = workbook["CAMPANHAS"]
        total = 0
        for row in sheet.iter_rows(min_row=2, values_only=True):
            novo_orcamento = row[8] if row[8] is not None and row[8] != "" else row[3]
            total += novo_orcamento
        return total
    except Exception as e:
        log_message(f"[ERRO] Falha ao calcular orçamento total: {e}")
        return 0

def realocar_orcamentos():
    """
    Realoca orçamentos entre campanhas baixas e altas:
    - Reduz o orçamento das campanhas com lucro baixo
    - Aumenta o orçamento das campanhas com lucro alto
    """
    if not os.path.exists(SPREADSHEET_PATH):
        log_message("[ERRO] Planilha de campanhas não encontrada.")
        return False
    
    workbook = openpyxl.load_workbook(SPREADSHEET_PATH)
    if "CAMPANHAS" not in workbook.sheetnames:
        log_message("[ERRO] Aba 'CAMPANHAS' não encontrada na planilha.")
        return False
    
    sheet = workbook["CAMPANHAS"]
    
    # Identificar campanhas com lucro baixo e alto
    campanhas_baixo = []
    campanhas_alto = []
    
    for row_index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        orcamento = row[3]  # Orçamento atual
        classificacao = row[9]  # Classificação
        
        if classificacao == "BAIXO":
            campanhas_baixo.append({
                "linha_index": row_index,
                "id_campanha": row[1],
                "orcamento_diario": orcamento,
                "lucro": row[7]
            })
        elif classificacao == "ALTO":
            campanhas_alto.append({
                "linha_index": row_index,
                "id_campanha": row[1],
                "orcamento_diario": orcamento,
                "lucro": row[7]
            })
    
    log_message(f"Encontradas {len(campanhas_baixo)} campanhas com lucro BAIXO e {len(campanhas_alto)} com lucro ALTO")
    
    # Se não houver campanhas para reduzir ou aumentar, finalizar
    if not campanhas_baixo or not campanhas_alto:
        log_message("Não há campanhas suficientes para realocação.")
        return False
    
    # Calcular total a ser realocado
    total_reducao = 0
    campanhas_reduzidas = 0
    
    # Reduzir orçamentos das campanhas com lucro baixo
    for campanha in campanhas_baixo:
        reducao = campanha["orcamento_diario"] * PERCENTUAL_REALOCACAO
        novo_orcamento = max(campanha["orcamento_diario"] - reducao, MINIMO_ORCAMENTO)
        
        # Calcular a redução real
        reducao_real = campanha["orcamento_diario"] - novo_orcamento
        total_reducao += reducao_real
        
        # Atualizar na planilha
        sheet.cell(row=campanha["linha_index"], column=9).value = novo_orcamento
        
        # Atualizar no Facebook
        resultado = atualizar_orcamento_facebook(campanha["id_campanha"], novo_orcamento)
        if resultado:
            log_message(f"Campanha {campanha['id_campanha']} reduzida de R$ {campanha['orcamento_diario']:.2f} para R$ {novo_orcamento:.2f}")
            campanhas_reduzidas += 1
    
    # Distribuir o valor reduzido entre as campanhas com lucro alto
    if total_reducao > 0 and campanhas_alto:
        # Calcular o valor a ser adicionado a cada campanha de lucro alto
        soma_lucro_alto = sum(c["lucro"] for c in campanhas_alto)
        campanhas_escaladas = 0
        
        for campanha in campanhas_alto:
            # Distribuir proporcionalmente ao lucro
            proporcao = campanha["lucro"] / soma_lucro_alto if soma_lucro_alto > 0 else 1.0 / len(campanhas_alto)
            incremento = total_reducao * proporcao
            
            # Calcular novo orçamento
            novo_orcamento = campanha["orcamento_diario"] + incremento
            
            # Atualizar na planilha
            sheet.cell(row=campanha["linha_index"], column=9).value = novo_orcamento
            
            # Atualizar no Facebook
            resultado = atualizar_orcamento_facebook(campanha["id_campanha"], novo_orcamento)
            if resultado:
                log_message(f"Campanha {campanha['id_campanha']} aumentada de R$ {campanha['orcamento_diario']:.2f} para R$ {novo_orcamento:.2f}")
                campanhas_escaladas += 1
    
    # Salvar planilha
    workbook.save(SPREADSHEET_PATH)
    
    # Calcular orçamento total atual
    total_orcamento_atual = calcular_orcamento_total()
    
    # Preparar mensagem de relatório
    mensagem = (
        f"Realocação concluída: {int(PERCENTUAL_REALOCACAO * 100)}% dos orçamentos de {campanhas_reduzidas} campanhas "
        f"com lucro abaixo de R$ {LIMITE_LUCRO_BAIXO} foram realocados para {len(campanhas_alto)} campanhas "
        f"com lucro acima de R$ {LIMITE_LUCRO_ALTO}. "
        f"Total realocado: R$ {total_reducao:.2f}. Orçamento total: R$ {total_orcamento_atual:.2f}."
    )
    
    # Enviar relatório via WhatsApp
    sucesso_whatsapp = enviar_mensagem_whatsapp(WHATSAPP_GROUP, mensagem)
    
    if not sucesso_whatsapp:
        log_message(f"[AVISO] Falha ao enviar mensagem WhatsApp, mas a realocação foi concluída: {mensagem}")
    else:
        log_message(f"[INFO] Mensagem enviada com sucesso: {mensagem}")
    
    log_message("Processo de realocação concluído com sucesso!")
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
    usando técnicas mais robustas de localização de elementos.
    
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
        brave_options.add_argument(r"--user-data-dir=C:\Users\Pichau\AppData\Local\BraveSoftware\Brave-Browser\User Data")
        brave_options.add_argument(r"--profile-directory=Default")
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
        
        # Múltiplos seletores para verificar se o WhatsApp Web carregou
        whatsapp_loaded_selectors = [
            (By.CSS_SELECTOR, "div[role='textbox'][aria-label='Caixa de texto de pesquisa']"),
            (By.CSS_SELECTOR, "div[role='textbox'][aria-placeholder='Pesquisar ou começar uma nova conversa']"),
            (By.XPATH, "//div[@role='textbox' and contains(@aria-label, 'Pesquisar')]"),
            (By.XPATH, "//div[contains(@class, '_ai04')]"),
            (By.XPATH, "//div[@id='pane-side']"),
            (By.ID, "pane-side")
        ]
        
        # Aguardar carregamento da página com múltiplos seletores
        log_message("Aguardando carregamento do WhatsApp Web...")
        for selector_type, selector_value in whatsapp_loaded_selectors:
            try:
                WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                log_message(f"WhatsApp Web carregado, elemento detectado: {selector_value}")
                break
            except:
                continue
        
        time.sleep(2)  # Pequena pausa para garantir que a interface esteja pronta
        
        # Múltiplos seletores para o campo de pesquisa
        search_selectors = [
            (By.CSS_SELECTOR, "div[role='textbox'][aria-label='Caixa de texto de pesquisa']"),
            (By.CSS_SELECTOR, "div[role='textbox'][aria-placeholder='Pesquisar ou começar uma nova conversa']"),
            (By.XPATH, "//div[@role='textbox' and contains(@aria-label, 'Pesquisar')]"),
            (By.XPATH, "//button[@aria-label='Pesquisar ou começar uma nova conversa']"),
            (By.XPATH, "//div[contains(@class, 'x10l6tqk')]"),
            (By.XPATH, "//div[contains(@class, 'lexical-rich-text-input')]//div[@role='textbox']"),
            (By.XPATH, "//div[@data-tab='3' and @role='textbox']")
        ]
        
        # Tentar encontrar e clicar no campo de pesquisa
        search_element = None
        for selector_type, selector_value in search_selectors:
            try:
                search_element = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((selector_type, selector_value))
                )
                log_message(f"Campo de pesquisa encontrado com seletor: {selector_value}")
                break
            except:
                continue
        
        if not search_element:
            # Tentar clicar na área onde geralmente fica o campo de pesquisa
            try:
                pane_side = driver.find_element(By.ID, "pane-side")
                driver.execute_script("arguments[0].scrollIntoView();", pane_side)
                actions = webdriver.ActionChains(driver)
                actions.move_to_element_with_offset(pane_side, 150, -50).click().perform()
                time.sleep(2)
                log_message("Clique realizado na área de pesquisa via coordenadas")
                
                # Tentar novamente encontrar o campo após o clique
                for selector_type, selector_value in search_selectors:
                    try:
                        search_element = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((selector_type, selector_value))
                        )
                        if search_element:
                            log_message(f"Campo de pesquisa encontrado após clique: {selector_value}")
                            break
                    except:
                        continue
            except Exception as e:
                log_message(f"Falha ao clicar na área de pesquisa: {e}")
                driver.save_screenshot("area_pesquisa_nao_encontrada.png")
        
        # Inserir texto de pesquisa
        if search_element:
            driver.execute_script("arguments[0].click();", search_element)
            time.sleep(1)
            search_element.clear()
            search_element.send_keys(grupo)
        else:
            # Se ainda não encontrou o elemento, tentar enviar as teclas diretamente
            actions = webdriver.ActionChains(driver)
            actions.send_keys(grupo)
            actions.perform()
        
        log_message(f"Pesquisando pelo grupo: {grupo}")
        time.sleep(3)  # Aguardar a pesquisa carregar resultados
        
        # Múltiplos seletores para encontrar o grupo
        group_selectors = [
            (By.XPATH, f"//span[@title='{grupo}']"),
            (By.XPATH, f"//span[contains(text(), '{grupo}')]"),
            (By.XPATH, f"//div[contains(text(), '{grupo}')]"),
            (By.CSS_SELECTOR, f"div[aria-selected='true'] span[title='{grupo}']"),
            (By.CSS_SELECTOR, f"div[aria-selected='true'] div[title='{grupo}']"),
            (By.XPATH, f"//div[contains(@class, '_21S-L')]//span[@title='{grupo}']")
        ]
        
        # Tentar encontrar e clicar no grupo
        group_element = None
        for selector_type, selector_value in group_selectors:
            try:
                group_element = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((selector_type, selector_value))
                )
                log_message(f"Grupo encontrado com seletor: {selector_value}")
                break
            except:
                continue
        
        if group_element:
            # Tentar clicar via JavaScript (mais confiável)
            try:
                driver.execute_script("arguments[0].click();", group_element)
                log_message("Clicado no grupo usando JavaScript")
            except:
                # Se falhar, tentar clique normal
                group_element.click()
                log_message("Clicado no grupo com método padrão")
        else:
            # Tentar clicar no primeiro resultado da pesquisa
            try:
                first_result = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div[aria-selected='true']"))
                )
                driver.execute_script("arguments[0].click();", first_result)
                log_message("Clicado no primeiro resultado da pesquisa")
            except Exception as e:
                log_message(f"Grupo não encontrado: {e}")
                driver.save_screenshot("grupo_nao_encontrado.png")
                raise Exception(f"Grupo/contato '{grupo}' não encontrado")
        
        time.sleep(3)  # Pausa após clicar no grupo
        
        # Múltiplos seletores para o campo de mensagem
        message_selectors = [
            (By.XPATH, "//div[@role='textbox' and @data-tab='10']"),
            (By.XPATH, "//div[@role='textbox' and contains(@aria-label, 'Digite uma mensagem')]"),
            (By.CSS_SELECTOR, "div[role='textbox'][data-tab='10']"),
            (By.CSS_SELECTOR, "div[role='textbox'][aria-label='Digite uma mensagem']"),
            (By.XPATH, "//div[contains(@class, 'lexical-rich-text-input')]//div[@role='textbox']"),
            (By.XPATH, "//footer//div[@role='textbox']"),
            (By.XPATH, "//div[contains(@class, '_3Uu1_')]")
        ]
        
        # Tentar encontrar o campo de mensagem
        log_message("Localizando campo de mensagem...")
        message_box = None
        for selector_type, selector_value in message_selectors:
            try:
                message_box = WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                log_message(f"Campo de mensagem encontrado com seletor: {selector_value}")
                break
            except:
                continue
        
        if not message_box:
            # Tentar encontrar qualquer footer ou área de mensagem na parte inferior
            try:
                footers = driver.find_elements(By.TAG_NAME, "footer")
                if footers:
                    footer = footers[0]
                    driver.execute_script("arguments[0].scrollIntoView();", footer)
                    
                    # Tentar clicar em um ponto relativo ao footer
                    actions = webdriver.ActionChains(driver)
                    actions.move_to_element_with_offset(footer, 200, -30).click().perform()
                    log_message("Clique realizado na área de mensagem via coordenadas")
                    time.sleep(2)
                    
                    # Tentar novamente após o clique
                    for selector_type, selector_value in message_selectors:
                        try:
                            message_box = WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((selector_type, selector_value))
                            )
                            if message_box:
                                log_message(f"Campo de mensagem encontrado após clique: {selector_value}")
                                break
                        except:
                            continue
                else:
                    # Tentar clicar em uma posição absoluta no centro-inferior da tela
                    window_size = driver.get_window_size()
                    x_position = window_size['width'] // 2
                    y_position = window_size['height'] - 100
                    actions = webdriver.ActionChains(driver)
                    actions.move_by_offset(x_position, y_position).click().perform()
                    log_message("Clique realizado em posição absoluta na tela")
                    time.sleep(2)
            except Exception as e:
                log_message(f"Falha ao localizar área de mensagem: {e}")
                driver.save_screenshot("area_mensagem_nao_encontrada.png")
        
        # Digitar a mensagem
        log_message("Tentando digitar mensagem...")
        if message_box:
            # Tentar clicar e limpar o campo antes de digitar
            driver.execute_script("arguments[0].click();", message_box)
            time.sleep(1)
            message_box.clear()
            message_box.send_keys(mensagem)
            log_message("Mensagem digitada com sucesso")
        else:
            # Tentar enviar as teclas diretamente
            actions = webdriver.ActionChains(driver)
            actions.send_keys(mensagem)
            actions.perform()
            log_message("Mensagem digitada via ActionChains")
        
        time.sleep(2)  # Pequena pausa após digitar a mensagem
        
        # Múltiplos seletores para o botão de enviar
        send_selectors = [
            (By.CSS_SELECTOR, "button[aria-label='Enviar']"),
            (By.CSS_SELECTOR, "button[data-tab='11']"),
            (By.XPATH, "//button[contains(@class, '_3wFFT')]"),
            (By.XPATH, "//button[@data-icon='send']"),
            (By.XPATH, "//button[contains(@class, '_1Ae7k')]"),
            (By.XPATH, "//span[@data-icon='send']")
        ]
        
        # Tentar encontrar e clicar no botão de enviar
        log_message("Procurando botão de enviar...")
        send_button = None
        for selector_type, selector_value in send_selectors:
            try:
                send_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((selector_type, selector_value))
                )
                log_message(f"Botão de enviar encontrado com seletor: {selector_value}")
                break
            except:
                continue
        
        if send_button:
            # Tentar clicar via JavaScript (mais confiável)
            try:
                driver.execute_script("arguments[0].click();", send_button)
                log_message("Botão de enviar clicado via JavaScript")
            except:
                # Se falhar, tentar clique normal
                send_button.click()
                log_message("Botão de enviar clicado com método padrão")
        else:
            # Tentar enviar com ENTER
            log_message("Tentando enviar mensagem com ENTER...")
            actions = webdriver.ActionChains(driver)
            actions.send_keys(Keys.ENTER)
            actions.perform()
            log_message("Tecla ENTER enviada")
        
        # Aguardar um pouco para garantir que a mensagem foi enviada
        time.sleep(5)
        
        # Verificar se a mensagem foi enviada (procurar por marca de verificação)
        try:
            time.sleep(5)  # Tempo adicional para que a mensagem seja processada
            # Tentar localizar elementos que indicam mensagem enviada (check marks)
            check_marks = driver.find_elements(By.XPATH, "//span[@data-icon='msg-check']")
            double_check_marks = driver.find_elements(By.XPATH, "//span[@data-icon='msg-dcheck']")
            
            if check_marks or double_check_marks:
                log_message("Mensagem enviada com sucesso (confirmado por marcadores)")
            else:
                log_message("Mensagem possivelmente enviada, mas sem confirmação visual")
        except:
            # Ignorar erros na verificação de confirmação
            pass
        
        log_message("Processo de envio de mensagem concluído")
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

def run(token, accounts, group, logs, date_range='today', start_date=None, end_date=None, low_profit=None, high_profit=None, realloc_pct=None):
    global ACCESS_TOKEN, AD_ACCOUNTS, WHATSAPP_GROUP, DATE_PRESET, LIMITE_LUCRO_BAIXO, LIMITE_LUCRO_ALTO, PERCENTUAL_REALOCACAO, logs_list
    ACCESS_TOKEN = token
    AD_ACCOUNTS = accounts if accounts is not None else []
    WHATSAPP_GROUP = group
    logs_list = logs
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
               f", Contas={accounts}, Grupo={group}")
    log_message(f"Parâmetros: Date Range={date_range}, Low Profit={low_profit}, High Profit={high_profit}, Realloc %={realloc_pct}")
    
    limpar_planilha()
    todas_campanhas = []
    for ad_account in AD_ACCOUNTS:
        log_message(f"Processando conta de anúncio: {ad_account}")
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
        
        campanhas_processadas = processar_dados_campanhas(campaigns, insights, ad_account)
        log_message(f"Processadas {len(campanhas_processadas)} campanhas ativas.")
        
        todas_campanhas.extend(campanhas_processadas)
    
    log_message(f"Total de {len(todas_campanhas)} campanhas ativas encontradas.")
    salvar_campanhas_excel(todas_campanhas)
    
    try:
        resultado = realocar_orcamentos()
        return resultado
    except Exception as e:
        log_message(f"Erro durante o processo de realocação: {e}")
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
    realocar_orcamentos()