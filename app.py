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
config.setdefault('fb_token', "")
config.setdefault('ad_accounts', [])
config.setdefault('whatsapp_group', "")
config.setdefault('admin_username', "admin")
config.setdefault('admin_password', "admin")
# Sincroniza chaves usadas pelos módulos
config['ACCESS_TOKEN'] = config.get('fb_token', "")
config['AD_ACCOUNTS'] = config.get('ad_accounts', [])
config['WHATSAPP_GROUP'] = config.get('whatsapp_group', "")

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
    return render_template('dashboard.html')

# Rota para configurações (GET e POST na mesma rota)
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        try:
            config['fb_token'] = request.form.get('fb_token', '')
            accounts_str = request.form.get('ad_accounts', '')
            config['ad_accounts'] = [acct.strip() for acct in accounts_str.split(',') if acct.strip()]
            config['whatsapp_group'] = request.form.get('whatsapp_group', '')
            # Sincroniza com as chaves usadas globalmente
            config['ACCESS_TOKEN'] = config['fb_token']
            config['AD_ACCOUNTS'] = config['ad_accounts']
            config['WHATSAPP_GROUP'] = config['whatsapp_group']
            with open('config.json', 'w') as f:
                json.dump(config, f, indent=2)
            return redirect(url_for('settings', saved='1'))
        except Exception as e:
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
    whatsapp_group = config.get('whatsapp_group', '')
    logs.clear()
    process_running = True
    logs.append(f"Iniciando operação: {operation}...")
    def run_task():
        global process_running
        try:
            if operation == 'escalar':
                escala_lucro.run(fb_token, ad_accounts, whatsapp_group, logs,
                                  data.get('date_range', 'today'),
                                  data.get('start_date'), data.get('end_date'),
                                  data.get('min_profit', 0), data.get('scale_value', 0))
            elif operation == 'reduzir':
                reduzir_orcamento.run(fb_token, ad_accounts, whatsapp_group, logs,
                                       data.get('date_range', 'today'),
                                       data.get('start_date'), data.get('end_date'),
                                       data.get('reduce_profit_limit', 0), data.get('reduce_pct', 0))
            elif operation == 'realocar':
                realocar_orcamento.run(fb_token, ad_accounts, whatsapp_group, logs,
                                       data.get('date_range', 'today'),
                                       data.get('start_date'), data.get('end_date'),
                                       data.get('low_profit', 0), data.get('high_profit', 0), data.get('realloc_pct', 0))
            else:
                logs.append("Operação desconhecida.")
            logs.append("Processo concluído.")
        except Exception as e:
            logs.append(f"Erro durante o processo: {e}")
        finally:
            process_running = False
    threading.Thread(target=run_task).start()
    return jsonify({"status": "started"})

# Rota para obter logs (AJAX)
@app.route('/logs')
def get_logs():
    return jsonify({"logs": logs, "running": process_running})

if __name__ == '__main__':
    app.run(debug=True)
