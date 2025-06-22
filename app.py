import json
import threading
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

import escala_lucro
import realocar_orcamento
import reduzir_orcamento

app = Flask(__name__)
app.secret_key = 'mysecretkey'  # Chave de segurança para a sessão

# Carrega configuração do arquivo config.json (ou cria com valores padrão)
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    config = {}

# Configurações padrão
config.setdefault('fb_token', "")
config.setdefault('ad_accounts', [])
config.setdefault('abo_accounts', [])  # Nova configuração para contas ABO
config.setdefault('whatsapp_group', "")
config.setdefault('admin_username', "admin")
config.setdefault('admin_password', "admin")
config.setdefault('scale_value', 5000)
config.setdefault('min_profit', 1)
config.setdefault('min_budget', 100)
config.setdefault('max_budget', 10000)

# Sincroniza chaves usadas pelos módulos
config['ACCESS_TOKEN'] = config.get('fb_token', "")
config['AD_ACCOUNTS'] = config.get('ad_accounts', [])
config['ABO_ACCOUNTS'] = config.get('abo_accounts', [])  # Sincronizar contas ABO
config['WHATSAPP_GROUP'] = config.get('whatsapp_group', "")
config['VALOR_TOTAL_ESCALA'] = config.get('scale_value', 5000)
config['LIMITE_LUCRO'] = config.get('min_profit', 1)
config['MINIMO_ORCAMENTO'] = config.get('min_budget', 100)
config['MAXIMO_ORCAMENTO'] = config.get('max_budget', 10000)

# Variáveis globais para logs e estado do processo
logs = []
process_running = False

# Protege rotas (exceto login e arquivos estáticos)
@app.before_request
def require_login():
    allowed_endpoints = ['login', 'static']
    if not session.get('logged_in') and request.endpoint not in allowed_endpoints:
        return redirect(url_for('login'))

# Rota de login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == config.get('admin_username') and password == config.get('admin_password'):
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = "Credenciais inválidas. Tente novamente."
    return render_template('login.html', error=error)

# Rota de logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Rota principal (dashboard)
@app.route('/')
def index():
    return render_template('dashboard.html', config=config)

# Rota para configurações (GET e POST na mesma rota)
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        try:
            # Configurações básicas
            config['fb_token'] = request.form.get('fb_token', '')
            
            # Processar contas de anúncio
            accounts_str = request.form.get('ad_accounts', '')
            config['ad_accounts'] = [acct.strip() for acct in accounts_str.split(',') if acct.strip()]
            
            # Processar contas ABO
            abo_accounts_str = request.form.get('abo_accounts', '')
            config['abo_accounts'] = [acct.strip() for acct in abo_accounts_str.split(',') if acct.strip()]
            
            # Outras configurações
            config['whatsapp_group'] = request.form.get('whatsapp_group', '')
            
            # Parâmetros de escalonamento
            config['scale_value'] = float(request.form.get('scale_value', 5000))
            config['min_profit'] = float(request.form.get('min_profit', 1))
            config['min_budget'] = float(request.form.get('min_budget', 100))
            config['max_budget'] = float(request.form.get('max_budget', 10000))
            
            # Sincroniza com as chaves usadas globalmente
            config['ACCESS_TOKEN'] = config['fb_token']
            config['AD_ACCOUNTS'] = config['ad_accounts']
            config['ABO_ACCOUNTS'] = config['abo_accounts']
            config['WHATSAPP_GROUP'] = config['whatsapp_group']
            config['VALOR_TOTAL_ESCALA'] = config['scale_value']
            config['LIMITE_LUCRO'] = config['min_profit']
            config['MINIMO_ORCAMENTO'] = config['min_budget']
            config['MAXIMO_ORCAMENTO'] = config['max_budget']
            
            # Salvar no arquivo
            with open('config.json', 'w') as f:
                json.dump(config, f, indent=2)
            
            return redirect(url_for('settings', saved='1'))
        except Exception as e:
            print(f"Erro ao salvar configurações: {e}")
            return redirect(url_for('settings', error='1'))
    
    saved = request.args.get('saved')
    error = request.args.get('error')
    return render_template('settings.html', config=config, saved=saved, error=error)

# Rota para iniciar o processo (via AJAX)
@app.route('/start', methods=['POST'])
def start_process():
    global process_running
    
    if process_running:
        return jsonify({"error": "Já existe um processo em execução."})
    
    data = request.get_json()
    if not data or 'operation' not in data:
        return jsonify({"error": "Operação não informada."})
    
    operation = data['operation']
    fb_token = config.get('fb_token')
    ad_accounts = config.get('ad_accounts', [])
    abo_accounts = config.get('abo_accounts', [])  # Obter contas ABO
    whatsapp_group = config.get('whatsapp_group', '')
    
    logs.clear()
    process_running = True
    logs.append(f"Iniciando operação: {operation}...")
    
    # Verificar configurações
    if not fb_token:
        logs.append("ERRO: Token do Facebook não configurado.")
        process_running = False
        return jsonify({"error": "Token do Facebook não configurado."})
    
    if not ad_accounts:
        logs.append("ERRO: Nenhuma conta de anúncio configurada.")
        process_running = False
        return jsonify({"error": "Nenhuma conta de anúncio configurada."})
    
    def run_task():
        global process_running
        try:
            if operation == 'escalar':
                # Usar valores do formulário ou valores padrão da configuração
                scale_value = data.get('scale_value', config.get('scale_value', 5000))
                min_profit = data.get('min_profit', config.get('min_profit', 1))
                
                logs.append(f"Contas de anúncio: {', '.join(ad_accounts)}")
                logs.append(f"Contas ABO: {', '.join(abo_accounts) if abo_accounts else 'Nenhuma'}")
                logs.append(f"Valor total para escalar: R$ {scale_value}")
                logs.append(f"Lucro mínimo: R$ {min_profit}")
                
                # Chamar com suporte a ABO
                escala_lucro.run(
                    fb_token, 
                    ad_accounts, 
                    whatsapp_group, 
                    logs,
                    data.get('date_range', 'today'),
                    data.get('start_date'), 
                    data.get('end_date'),
                    min_profit, 
                    scale_value,
                    abo_accounts  # Passar contas ABO
                )
                
            elif operation == 'reduzir':
                reduzir_orcamento.run(
                    fb_token, 
                    ad_accounts, 
                    whatsapp_group, 
                    logs,
                    data.get('date_range', 'today'),
                    data.get('start_date'), 
                    data.get('end_date'),
                    data.get('reduce_profit_limit', 0), 
                    data.get('reduce_pct', 0),
                    abo_accounts  # Passar contas ABO se o módulo suportar
                )
                
            elif operation == 'realocar':
                realocar_orcamento.run(
                    fb_token, 
                    ad_accounts, 
                    whatsapp_group, 
                    logs,
                    data.get('date_range', 'today'),
                    data.get('start_date'), 
                    data.get('end_date'),
                    data.get('low_profit', 0), 
                    data.get('high_profit', 0), 
                    data.get('realloc_pct', 0),
                    abo_accounts  # Passar contas ABO se o módulo suportar
                )
            else:
                logs.append("Operação desconhecida.")
            
            logs.append("Processo concluído.")
            
        except Exception as e:
            logs.append(f"Erro durante o processo: {e}")
            import traceback
            logs.append(traceback.format_exc())
        finally:
            process_running = False
    
    threading.Thread(target=run_task).start()
    return jsonify({"status": "started"})

# Rota para obter logs (AJAX)
@app.route('/logs')
def get_logs():
    return jsonify({"logs": logs, "running": process_running})

# Rota para obter status das contas
@app.route('/account_status')
def account_status():
    """Retorna informações sobre as contas configuradas"""
    return jsonify({
        "total_accounts": len(config.get('ad_accounts', [])),
        "cbo_accounts": len(set(config.get('ad_accounts', [])) - set(config.get('abo_accounts', []))),
        "abo_accounts": len(config.get('abo_accounts', [])),
        "accounts": config.get('ad_accounts', []),
        "abo_list": config.get('abo_accounts', [])
    })

if __name__ == '__main__':
    app.run(debug=True)