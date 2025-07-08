# -*- coding: utf-8 -*-
# Cérebro Ares - Módulo CRIPTO v2.0 (Produção)
from flask import Flask, request, jsonify
from datetime import datetime
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd

# --- Configuração do Servidor Flask ---
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- CONFIGURAÇÕES GERAIS ---
API_KEYS = [
    "9W8QUYEG89T78GYP", "51OICUVQT4MMJB4K", "EAUKTIO79NZ1HJW2", "SUDMKRZOWRXCRZYT",
    "1YUAECGWJ20K0BRS", "WNPDEZ9P81S5RBZB", "DDKH8ODKHCUTQ4GK", "275RKW6RCGQX8DMZ",
    "L49LSKDSBTZNB8RC", "OMNKFZTA9Y42TV1P", "6NE5I7TONTRJPYAA", "S48DAU5DDME2CJB7",
    "YCARDEFWPFW2GQGG", "RH28B34R7HX4TKJH", "J3DFDYDJXMW67GIC", "W4VU5PB3BJGJVHHC"
]
CRYPTO_TICKER_SENTIMENT = "BTC,ETH"
CRYPTO_TICKER_TREND = "BTC-USD" 
LIMIARES_RISCO = {"Conservador": 0.70, "Medio": 0.45, "Agressivo": 0.20}
VOL_BAIXA = 0.80  
VOL_ALTA = 2.50   

app_state = {"key_index": 0}

def get_next_api_key():
    key = API_KEYS[app_state["key_index"]]
    app_state["key_index"] = (app_state["key_index"] + 1) % len(API_KEYS)
    return key

# --- FATOR 1: ANÁLISE DE SENTIMENTO DE NOTÍCIAS ---
def get_news_sentiment(tickers):
    params = {"function": "NEWS_SENTIMENT", "topics": "blockchain", "tickers": tickers, "limit": "50"}
    try:
        base_url = "https://www.alphavantage.co/query"
        params['apikey'] = get_next_api_key()
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or 'feed' not in data: return 0.0
        total_score, count = 0.0, 0
        for item in data['feed']:
            for ticker_sentiment in item['ticker_sentiment']:
                if ticker_sentiment['ticker'] in tickers:
                    try:
                        total_score += float(ticker_sentiment['relevance_score']) * float(ticker_sentiment['sentiment_score'])
                        count += 1
                    except (ValueError, KeyError): continue
        return total_score / count if count > 0 else 0.0
    except Exception:
        return 0.0

# --- FATOR 2: ANÁLISE TÉCNICA MULTI-TIMEFRAME (MTF) ---
def get_mtf_bias(ticker, interval):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        range_param = "60d" if interval == "4h" else "7d"
        data = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_param}&interval={interval}", headers=headers).json()
        if not (data.get('chart', {}).get('result') and data['chart']['result'][0].get('indicators', {}).get('quote')): return 0.0
        closes = [p for p in data['chart']['result'][0]['indicators']['quote'][0].get('close', []) if p is not None]
        if len(closes) < 21: return 0.0
        df = pd.DataFrame({'close': closes})
        ema21 = df['close'].ewm(span=21, adjust=False).mean()
        ema_slope = 1 if ema21.iloc[-1] > ema21.iloc[-2] else -1
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi_level = 1 if rsi.iloc[-1] > 51 else -1 if rsi.iloc[-1] < 49 else 0
        return (ema_slope + rsi_level) / 2.0
    except Exception:
        return 0.0

def get_technical_trend_score(ticker):
    try:
        trend_score_15m = get_mtf_bias(ticker, '15m')
        trend_score_60m = get_mtf_bias(ticker, '60m')
        trend_score_4h = get_mtf_bias(ticker, '4h')
        final_trend_score = (trend_score_15m * 0.5) + (trend_score_60m * 0.3) + (trend_score_4h * 0.2)
        print(f"Análise MTF ({ticker}): 15m({trend_score_15m:.2f}) 60m({trend_score_60m:.2f}) 4h({trend_score_4h:.2f}) -> Final({final_trend_score:.2f})")
        return final_trend_score
    except Exception as e:
        print(f"Erro na análise técnica para {ticker}: {e}")
        return 0.0

# --- FUNÇÃO PRINCIPAL DE ANÁLISE ---
def analyze_market(asset_type, modo_operacao, modo_risco_manual, volatilidade_local):
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_sentiment = executor.submit(get_news_sentiment, CRYPTO_TICKER_SENTIMENT)
        future_analysis = executor.submit(get_technical_trend_score, CRYPTO_TICKER_TREND)
        sentiment_score = future_sentiment.result()
        trend_score = future_analysis.result()

    fluxo_score = (sentiment_score * 0.3) + (trend_score * 0.7)
    
    # --- FATOR 3: ADAPTAÇÃO À VOLATILIDADE ---
    modo_risco_final = modo_risco_manual
    active_mode_str = f"Manual - {modo_risco_manual}"
    if modo_operacao == 'Auto':
        if volatilidade_local > VOL_ALTA: modo_risco_final, active_mode_str = 'Conservador', f"Auto (Vol ALTA -> Conservador)"
        elif volatilidade_local < VOL_BAIXA: modo_risco_final, active_mode_str = 'NEUTRO', f"Auto (Vol BAIXA -> Neutro)"
        else: modo_risco_final, active_mode_str = 'Medio', f"Auto (Vol NORMAL -> Medio)"

    limite_sinal = LIMIARES_RISCO.get(modo_risco_final, 999)
    
    trade_bias = "NEUTRO"
    if fluxo_score >= limite_sinal: trade_bias = "COMPRADOR"
    elif fluxo_score <= -limite_sinal: trade_bias = "VENDEDOR"
        
    response = {
        "trade_bias": trade_bias,
        "active_mode": f"{active_mode_str} (Limite: {limite_sinal:.2f})",
        "fluxo_score_final": f"{fluxo_score:.4f}",
        "last_update": datetime.now().strftime("%H:%M:%S")
    }
    
    print(f"Análise Final {asset_type.upper()} | Viés: {trade_bias} | Modo Ativo: {active_mode_str} (Score: {fluxo_score:.4f})\n")
    return jsonify(response)

# --- ROTAS DA API ---
@app.route('/predict/crypto', methods=['GET'])
def predict_crypto():
    modo_op = request.args.get('modo_operacao', default='Auto', type=str)
    modo_risco = request.args.get('modo_risco', default='Agressivo', type=str)
    # A volatilidade será enviada pelo robô executor
    volatilidade = request.args.get('volatilidade_local', default=1.5, type=float)
    return analyze_market('crypto', modo_op, modo_risco, volatilidade)

if __name__ == '__main__':
    print("================================================")
    print("=         Cérebro Ares - Módulo CRIPTO         =")
    print("=                   v2.0                       =")
    print("= Aguardando conexões na rota /predict/crypto  =")
    print("================================================")
    app.run(host="0.0.0.0", port=5001, debug=False)