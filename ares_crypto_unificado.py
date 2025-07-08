# ==============================================================================
#      SISTEMA UNIFICADO ARES CRYPTO v1.0 (CÉREBRO + ROBÔ EXECUTOR)
# ==============================================================================
# Este script roda o Cérebro (Flask API) e o Robô Executor (Binance)
# ao mesmo tempo usando threads, para ser compatível com planos gratuitos do Render.

import time
import requests
import os
import threading
from binance.client import Client
from binance.exceptions import BinanceAPIException
import numpy as np
import pandas as pd
import pandas_ta as ta
from flask import Flask, request, jsonify
import logging

# ==============================================================================
# 1. CONFIGURAÇÕES GERAIS
# ==============================================================================

# --- Chaves da Binance ---
# Suas chaves foram inseridas aqui. Lembre-se de manter este arquivo seguro.
API_KEY    = "PoAPxsWFDDO8U0uCyOCS0FD7wrkjwTLScxk9piQWmgZ2Ry9RPwg7vluwKZfHYQZc"
API_SECRET = "p1pPB1hlVa1MPPUNxayqcSinlqgQbLIK4kopP6XZ4WWZUD0ppd4BxoW4JvVfMlGZ"

# --- Configurações do Cérebro ---
# URL para o Robô consultar o Cérebro (rodando na mesma máquina)
CEREBRO_INTERNAL_URL = "http://127.0.0.1:5001/predict/crypto"

API_KEYS_AV = [ 
    "9W8QUYEG89T78GYP", "51OICUVQT4MMJB4K", "EAUKTIO79NZ1HJW2", "SUDMKRZOWRXCRZYT",
    "1YUAECGWJ20K0BRS", "WNPDEZ9P81S5RBZB", "DDKH8ODKHCUTQ4GK", "275RKW6RCGQX8DMZ",
    "L49LSKDSBTZNB8RC", "OMNKFZTA9Y42TV1P", "6NE5I7TONTRJPYAA", "S48DAU5DDME2CJB7",
    "YCARDEFWPFW2GQGG", "RH28B34R7HX4TKJH", "J3DFDYDJXMW67GIC", "W4VU5PB3BJGJVHHC"
]
CRYPTO_TICKER_SENTIMENT = "BTC,ETH"
CRYPTO_TICKER_TREND     = "BTC-USD" 
LIMIARES_RISCO          = {"Conservador": 0.70, "Medio": 0.45, "Agressivo": 0.20}
VOL_BAIXA               = 0.80  
VOL_ALTA                = 2.50   

# --- Parâmetros do Robô Executor ---
SYMBOLS_TO_SCAN      = ['BTCBRL', 'ETHBRL', 'SOLBRL', 'LINKBRL', 'ADABRL']
TIMEFRAME            = Client.KLINE_INTERVAL_5MINUTE
RISK_PER_TRADE_BRL   = 20.00
INTERVALO_CONSULTA_CEREBRO = 180 

# Parâmetros de Indicadores e Gatilhos
ATR_PERIOD           = 14
SL_ATR_MULTIPLIER    = 2.5
TP_ATR_MULTIPLIER    = 3.5
EMA_FAST_PERIOD      = 9
EMA_SLOW_PERIOD      = 21
STOCH_K              = 5
STOCH_D              = 3
STOCH_SMOOTH         = 3
MOMENTUM_PERIOD      = 3
SQUEEZE_PERIOD       = 20

# --- Variáveis de Estado Globais ---
client = None
trade_state = {'in_position': False, 'symbol': None, 'side': None, 'entry_price': 0.0, 'oco_order_id': None, 'quantity': 0.0}

# ==============================================================================
# 2. LÓGICA DO CÉREBRO (Servidor Flask API)
# ==============================================================================

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app_state = {"key_index": 0}

def get_next_api_key():
    key = API_KEYS_AV[app_state["key_index"]]
    app_state["key_index"] = (app_state["key_index"] + 1) % len(API_KEYS_AV)
    return key

def get_news_sentiment(tickers):
    params = {"function": "NEWS_SENTIMENT", "topics": "blockchain", "tickers": tickers, "limit": "50"}
    try:
        base_url = "https://www.alphavantage.co/query"
        params['apikey'] = get_next_api_key()
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status(); data = response.json()
        if not data or 'feed' not in data: return 0.0
        total_score, count = 0.0, 0
        for item in data['feed']:
            for ts in item['ticker_sentiment']:
                if ts['ticker'] in tickers:
                    try:
                        total_score += float(ts['relevance_score']) * float(ts['sentiment_score'])
                        count += 1
                    except (ValueError, KeyError): continue
        return total_score / count if count > 0 else 0.0
    except Exception as e:
        print(f"[CÉREBRO-ERRO] Sentimento: {e}"); return 0.0

def get_mtf_bias(ticker, interval):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        range_param = "60d" if interval == "4h" else "7d"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_param}&interval={interval}"
        data = requests.get(url, headers=headers).json()
        closes = [p for p in data['chart']['result'][0]['indicators']['quote'][0].get('close', []) if p is not None]
        if len(closes) < 21: return 0.0
        df = pd.DataFrame({'close': closes})
        ema21 = df['close'].ewm(span=21, adjust=False).mean()
        return 1 if ema21.iloc[-1] > ema21.iloc[-2] else -1
    except Exception as e:
        print(f"[CÉREBRO-ERRO] MTF {interval}: {e}"); return 0.0

def get_technical_trend_score(ticker):
    try:
        score_15m = get_mtf_bias(ticker, '15m')
        score_60m = get_mtf_bias(ticker, '60m')
        score_4h = get_mtf_bias(ticker, '4h')
        final_score = (score_15m * 0.5) + (score_60m * 0.3) + (score_4h * 0.2)
        print(f"[CÉREBRO] Análise MTF: 15m({score_15m:.1f}) 60m({score_60m:.1f}) 4h({score_4h:.1f}) -> Final({final_score:.2f})")
        return final_score
    except Exception as e:
        print(f"[CÉREBRO-ERRO] Score Técnico: {e}"); return 0.0

@app.route('/predict/crypto', methods=['GET'])
def predict_crypto():
    modo_risco = request.args.get('modo_risco', default='Medio', type=str)
    volatilidade = request.args.get('volatilidade_local', default=1.5, type=float)
    
    sentiment_score = get_news_sentiment(CRYPTO_TICKER_SENTIMENT)
    trend_score = get_technical_trend_score(CRYPTO_TICKER_TREND)
    fluxo_score = (sentiment_score * 0.3) + (trend_score * 0.7)
    
    if volatilidade > VOL_ALTA: modo_risco, active_mode_str = 'Conservador', f"Auto(Vol ALTA)"
    elif volatilidade < VOL_BAIXA: modo_risco, active_mode_str = 'NEUTRO', f"Auto(Vol BAIXA)"
    else: modo_risco, active_mode_str = 'Medio', f"Auto(Vol NORMAL)"

    limite = LIMIARES_RISCO.get(modo_risco, 999)
    trade_bias = "NEUTRO"
    if fluxo_score >= limite: trade_bias = "COMPRADOR"
    elif fluxo_score <= -limite: trade_bias = "VENDEDOR"
        
    print(f"Análise Final: Viés: {trade_bias} | Modo: {active_mode_str} (Score: {fluxo_score:.4f})\n")
    return jsonify({"trade_bias": trade_bias})

# ==============================================================================
# 3. LÓGICA DO ROBÔ EXECUTOR (Funções de Trading)
# ==============================================================================
def connect_to_binance():
    global client
    if not API_KEY or not API_SECRET:
        print("[ROBÔ-ERRO] Chaves de API não configuradas. Encerrando.")
        return False
    try:
        client = Client(API_KEY, API_SECRET)
        client.get_account()
        print(">>> [ROBÔ] Conexão com a Binance estabelecida com sucesso.")
        return True
    except BinanceAPIException as e:
        print(f"[ROBÔ-ERRO] Falha ao conectar na Binance. Verifique suas chaves. Erro: {e}")
        return False

def get_current_data(symbol, timeframe, limit):
    klines = client.get_klines(symbol=symbol, interval=timeframe, limit=limit)
    df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
    return df

def check_for_entry():
    # Lógica de escaneamento e gatilhos...
    pass # Esta função será chamada pelo loop principal

def place_order(symbol, side):
    # Lógica para enviar a ordem e a ordem OCO
    pass # Esta função será chamada pelo check_for_entry

def manage_position():
    # Lógica para gerenciar a posição aberta, incluindo a saída por viés
    pass # Esta função será chamada pelo loop principal

# ==============================================================================
# 4. INICIALIZAÇÃO E THREADING (A Unificação)
# ==============================================================================

def start_cerebro():
    """Função para iniciar o servidor Flask do Cérebro."""
    print(">>> [CÉREBRO] Iniciando servidor Flask...")
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)

def start_robo_executor():
    """Função que inicia o loop de trading do robô."""
    print(">>> [ROBÔ] Iniciando executor...")
    if not connect_to_binance(): return
        
    while True:
        try:
            if trade_state['in_position']:
                manage_position() # AINDA PRECISAMOS IMPLEMENTAR ESSA LÓGICA
            else:
                check_for_entry() # AINDA PRECISAMOS IMPLEMENTAR ESSA LÓGICA
            
            print(f"\n[ROBÔ] Ciclo concluído. Aguardando {INTERVALO_CONSULTA} segundos...")
            time.sleep(INTERVALO_CONSULTA)
        except Exception as e:
            print(f"ERRO INESPERADO NO LOOP DO ROBÔ: {e}")
            time.sleep(60)

# --- PONTO DE PARTIDA DO SCRIPT ---
if __name__ == '__main__':
    # Cria as duas threads
    cerebro_thread = threading.Thread(target=start_cerebro)
    robo_thread = threading.Thread(target=start_robo_executor)

    # Inicia as threads para rodarem em paralelo
    cerebro_thread.start()
    time.sleep(5) # Pequena pausa para garantir que o servidor Flask suba antes do robô tentar conectar
    robo_thread.start()

    print("\n================================================")
    print("=     SISTEMA ARES CRYPTO UNIFICADO v1.0       =")
    print("=      Cérebro e Robô rodando em paralelo.     =")
    print("================================================")