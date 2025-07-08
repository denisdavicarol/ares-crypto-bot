# ==============================================================================
#      SISTEMA ARES CRYPTO UNIFICADO v3.2 - VERSÃO COMPLETA E FUNCIONAL
# ==============================================================================
# Este script único roda tanto o Cérebro de análise quanto o Robô Executor
# da Binance em paralelo, otimizado para rodar em serviços como o Render.com

import time
import requests
import os
import threading
from binance.client import Client
from binance.exceptions import BinanceAPIException
import numpy as np
import pandas as pd
import pandas_ta as ta

# --- 1. CONFIGURAÇÕES GERAIS ---
API_KEY = os.environ.get('API_KEY')
API_SECRET = os.environ.get('API_SECRET')
API_KEYS_AV = [
    "9W8QUYEG89T78GYP", "51OICUVQT4MMJB4K", "EAUKTIO79NZ1HJW2", "SUDMKRZOWRXCRZYT",
    "1YUAECGWJ20K0BRS", "WNPDEZ9P81S5RBZB", "DDKH8ODKHCUTQ4GK", "275RKW6RCGQX8DMZ"
]
CRYPTO_TICKER_SENTIMENT = "BTC,ETH"
CRYPTO_TICKER_TREND = "BTC-USD" 
SYMBOLS_TO_SCAN = ['BTCBRL', 'ETHBRL', 'SOLBRL', 'LINKBRL', 'ADABRL']
LIMIARES_RISCO = {"Conservador": 0.70, "Medio": 0.45, "Agressivo": 0.20}
VOL_BAIXA = 0.80  
VOL_ALTA = 2.50
INTERVALO_ANALISE_CEREBRO = 180 
INTERVALO_VERIFICACAO_ROBO = 20
RISK_PER_TRADE_BRL = 20.00
TIMEFRAME_ROBO = Client.KLINE_INTERVAL_5MINUTE
ATR_PERIOD = 14
SL_ATR_MULTIPLIER = 2.5
TP_ATR_MULTIPLIER = 3.5
EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
STOCH_K = 5
STOCH_D = 3
STOCH_SMOOTH = 3
MOMENTUM_PERIOD = 3
SQUEEZE_PERIOD = 20

# --- Variáveis de Estado Globais ---
client = None
trade_state = {'in_position': False, 'symbol': None, 'side': None, 'entry_price': 0.0, 'oco_order_id': None, 'quantity': 0.0}
cerebro_data = {'trade_bias': 'NEUTRO', 'active_mode': 'Inicializando...'}
app_state_av = {"key_index": 0}

# ==============================================================================
# 2. LÓGICA DO CÉREBRO (Funções de Análise)
# ==============================================================================
def get_next_api_key():
    key = API_KEYS_AV[app_state_av["key_index"]]
    app_state_av["key_index"] = (app_state_av["key_index"] + 1) % len(API_KEYS_AV)
    return key

def get_news_sentiment(tickers):
    params = {"function": "NEWS_SENTIMENT", "topics": "blockchain", "tickers": tickers, "limit": "50"}
    try:
        base_url = "https://www.alphavantage.co/query"
        params['apikey'] = get_next_api_key()
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not data or 'feed' not in data or not isinstance(data['feed'], list): return 0.0
        total_score, count = 0.0, 0
        for item in data['feed']:
            for ticker_sentiment in item.get('ticker_sentiment', []):
                if ticker_sentiment.get('ticker') in tickers:
                    try:
                        relevance = float(ticker_sentiment['relevance_score'])
                        sentiment = float(ticker_sentiment['sentiment_score'])
                        if relevance > 0.35:
                           total_score += relevance * sentiment
                           count += 1
                    except (ValueError, KeyError): continue
        return total_score / count if count > 0 else 0.0
    except Exception as e:
        print(f"[CÉREBRO] Erro ao buscar sentimento: {e}")
        return 0.0

def analyze_market_and_update_state():
    global cerebro_data
    print("[CÉREBRO] Iniciando ciclo de análise...")
    sentiment_score = get_news_sentiment(CRYPTO_TICKER_SENTIMENT)
    # A análise técnica agora é feita no robô para ser mais ágil
    fluxo_score = sentiment_score # Foco no sentimento para o viés macro
    
    # A lógica de modo automático de volatilidade também passa para o robô
    active_mode_str = "Médio" # Usando modo médio como padrão
    limite_sinal = LIMIARES_RISCO.get(active_mode_str, 0.45)
    
    trade_bias = "NEUTRO"
    if fluxo_score >= limite_sinal: trade_bias = "COMPRADOR"
    elif fluxo_score <= -limite_sinal: trade_bias = "VENDEDOR"
        
    cerebro_data['trade_bias'] = trade_bias
    cerebro_data['active_mode'] = f"Modo: {active_mode_str} (Sent. Score: {fluxo_score:.4f})"
    print(f"[CÉREBRO] Análise concluída. Novo viés: {trade_bias}")


# ==============================================================================
# 3. LÓGICA DO ROBÔ EXECUTOR (Funções de Trading)
# ==============================================================================
def connect_to_binance():
    global client
    print("[ROBÔ] Tentando conectar à Binance...")
    if not API_KEY or not API_SECRET:
        print("[ROBÔ] ERRO: Chaves de API não configuradas. Verifique as Variáveis de Ambiente no Render.")
        return False
    try:
        client = Client(API_KEY, API_SECRET)
        # Sincroniza o tempo com o servidor da Binance para evitar erros de timestamp
        server_time = client.get_server_time()
        print(f">>> [ROBÔ] Conexão com a Binance estabelecida com sucesso. Latência: {int(time.time()*1000) - server_time['serverTime']}ms")
        return True
    except Exception as e:
        print(f"ERRO DE API BINANCE: {e}")
        return False

def get_klines_as_df(symbol, interval, limit):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','a','b','c','d','e','f'])
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
    return df

def determinar_regime_local(df):
    try:
        df.ta.bbands(length=SQUEEZE_PERIOD, append=True)
        df.ta.kc(length=SQUEEZE_PERIOD, append=True)
        last = df.iloc[-1]
        if last[f'BBU_{SQUEEZE_PERIOD}_2.0'] < last[f'KCUe_{SQUEEZE_PERIOD}_2.0'] and last[f'BBL_{SQUEEZE_PERIOD}_2.0'] > last[f'KCLe_{SQUEEZE_PERIOD}_2.0']:
            return "SQUEEZE"
        else:
            return "TENDENCIA"
    except Exception: return "TENDENCIA"

def buscar_gatilhos_tendencia(df, symbol, trade_bias):
    try:
        df.ta.ema(length=EMA_FAST_PERIOD, append=True)
        df.ta.ema(length=EMA_SLOW_PERIOD, append=True)
        df.ta.stoch(k=STOCH_K, d=STOCH_D, smooth_k=STOCH_SMOOTH, append=True)
        
        last = df.iloc[-1]; prev = df.iloc[-2]
        current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])

        if trade_bias == "COMPRADOR":
            if prev[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] < 50 and last[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] > 50: return "Pullback"
            if last[f'EMA_{EMA_FAST_PERIOD}'] > last[f'EMA_{EMA_SLOW_PERIOD}'] and last['low'] < last[f'EMA_{EMA_FAST_PERIOD}'] and last['close'] > last[f'EMA_{EMA_FAST_PERIOD}']: return "Ignicao"
            if current_price > df['high'][-MOMENTUM_PERIOD-1:-1].max(): return "Momentum"
        elif trade_bias == "VENDEDOR":
            if prev[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] > 50 and last[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] < 50: return "Pullback"
            if last[f'EMA_{EMA_FAST_PERIOD}'] < last[f'EMA_{EMA_SLOW_PERIOD}'] and last['high'] > last[f'EMA_{EMA_FAST_PERIOD}'] and last['close'] < last[f'EMA_{EMA_FAST_PERIOD}']: return "Ignicao"
            if current_price < df['low'][-MOMENTUM_PERIOD-1:-1].min(): return "Momentum"
    except Exception as e:
        print(f"Erro nos gatilhos de tendência para {symbol}: {e}")
    return None

def buscar_gatilho_squeeze(df, symbol, trade_bias):
    try:
        high_range = df['high'][-SQUEEZE_PERIOD-1:-1].max()
        low_range = df['low'][-SQUEEZE_PERIOD-1:-1].min()
        current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])
        if trade_bias == "COMPRADOR" and current_price > high_range: return "Squeeze"
        if trade_bias == "VENDEDOR" and current_price < low_range: return "Squeeze"
    except Exception as e:
        print(f"Erro no gatilho de squeeze para {symbol}: {e}")
    return None

def check_for_entry():
    global trade_state
    if trade_state['in_position']: return
    
    trade_bias = cerebro_data.get('trade_bias', 'NEUTRO')
    if trade_bias == "NEUTRO":
        print("[ROBÔ] Viés NEUTRO. Nenhuma ação.")
        return
        
    print(f"[ROBÔ] Viés {trade_bias}. Escaneando {len(SYMBOLS_TO_SCAN)} pares...")
    for symbol in SYMBOLS_TO_SCAN:
        try:
            df = get_klines_as_df(symbol=symbol, interval=TIMEFRAME, limit=100)
            regime_local = determinar_regime_local(df)
            print(f"Analisando {symbol}... Regime: {regime_local}")
            
            gatilho = None
            if regime_local == "TENDENCIA": gatilho = buscar_gatilhos_tendencia(df, symbol, trade_bias)
            elif regime_local == "SQUEEZE": gatilho = buscar_gatilho_squeeze(df, symbol, trade_bias)
            
            if gatilho:
                print(f"OPORTUNIDADE ENCONTRADA! Gatilho de {gatilho} em {symbol}.")
                side = Client.SIDE_BUY if trade_bias == "COMPRADOR" else Client.SIDE_SELL
                place_order(symbol, side, df)
                return 
        except Exception as e:
            print(f"Erro ao analisar o par {symbol}: {e}")
            continue

def place_order(symbol, side, df):
    global trade_state
    try:
        df.ta.atr(length=ATR_PERIOD, append=True)
        atr = df.iloc[-1][f'ATRr_{ATR_PERIOD}']
        if atr == 0:
            print(f"ERRO: ATR para {symbol} é zero. Abortando trade.")
            return

        stop_loss_distance = atr * SL_ATR_MULTIPLIER
        quantity = RISK_PER_TRADE_BRL / stop_loss_distance
        
        info = client.get_symbol_info(symbol)
        step_size = float([f['stepSize'] for f in info['filters'] if f['filterType'] == 'LOT_SIZE'][0])
        quantity = round(quantity / step_size) * step_size

        print(f"Enviando ordem a mercado: {side} {quantity:.8f} {symbol}")
        order = client.create_order(symbol=symbol, side=side, type=Client.ORDER_TYPE_MARKET, quantity=quantity)
        
        entry_price = float(order['fills'][0]['price'])
        trade_state.update({'in_position': True, 'symbol': symbol, 'side': side, 'entry_price': entry_price, 'quantity': quantity})
        print(f"ORDEM EXECUTADA @ {entry_price}")
        place_oco_exit_orders(atr)

    except Exception as e:
        print(f"ERRO AO ENVIAR ORDEM DE ENTRADA: {e}")

def place_oco_exit_orders(atr):
    global trade_state
    symbol = trade_state['symbol']
    entry_price = trade_state['entry_price']
    
    if trade_state['side'] == Client.SIDE_BUY:
        stop_loss_price = entry_price - (atr * SL_ATR_MULTIPLIER)
        take_profit_price = entry_price + (atr * TP_ATR_MULTIPLIER)
        side_oco = Client.SIDE_SELL
    else: # SELL
        stop_loss_price = entry_price + (atr * SL_ATR_MULTIPLIER)
        take_profit_price = entry_price - (atr * TP_ATR_MULTIPLIER)
        side_oco = Client.SIDE_BUY
        
    info = client.get_symbol_info(symbol)
    tick_size = float([f['tickSize'] for f in info['filters'] if f['filterType'] == 'PRICE_FILTER'][0])
    stop_loss_price = round(stop_loss_price / tick_size) * tick_size
    take_profit_price = round(take_profit_price / tick_size) * tick_size

    trade_state['stop_loss_price'] = stop_loss_price
    
    try:
        print(f"Enviando ordem OCO para {symbol}: Alvo={take_profit_price:.4f}, Stop={stop_loss_price:.4f}")
        oco_order = client.create_oco_order(symbol=symbol, side=side_oco, quantity=trade_state['quantity'], price=f"{take_profit_price:.8f}", stopPrice=f"{stop_loss_price:.8f}", stopLimitPrice=f"{stop_loss_price:.8f}", stopLimitTimeInForce='GTC')
        trade_state['oco_order_id'] = oco_order['orderReports'][0]['orderListId']
        print(f"Ordem OCO (Alvo/Stop) posicionada com sucesso. OrderListId: {trade_state['oco_order_id']}")
    except Exception as e:
        print(f"ERRO AO ENVIAR ORDEM OCO. Tentando fechar a posição por segurança: {e}")
        close_position(trade_state['entry_price'])

def manage_position():
    global trade_state
    if not trade_state['in_position']: return
    
    symbol = trade_state['symbol']
    print(f"Gerenciando posição de {trade_state['side']} em {symbol}...")
    
    # Checa se a posição foi fechada pelo OCO
    try:
        orders = client.get_all_orders(symbol=symbol, orderListId=trade_state['oco_order_id'])
        # Se ambas as ordens (STOP_LOSS e LIMIT_MAKER) não estiverem mais ativas, a posição foi fechada.
        if all(o['status'] not in ['NEW', 'PARTIALLY_FILLED'] for o in orders):
            print(f"Posição em {symbol} fechada por Alvo ou Stop da ordem OCO.")
            # Aqui buscaríamos o preço de fechamento no histórico para o P/L, por simplicidade vamos apenas resetar.
            trade_state = {'in_position': False, 'symbol': None}
            return
    except Exception as e:
        print(f"Aviso: Não foi possível checar ordem OCO (pode já ter sido executada/cancelada): {e}")
        # Se não encontrarmos a ordem OCO, é provável que ela foi fechada/cancelada. Resetamos.
        trade_state = {'in_position': False, 'symbol': None}
        return

    # Lógica de Saída por Invalidação de Viés
    trade_bias = cerebro_data.get('trade_bias', 'NEUTRO')
    if (trade_state['side'] == Client.SIDE_BUY and trade_bias == "VENDEDOR") or \
       (trade_state['side'] == Client.SIDE_SELL and trade_bias == "COMPRADOR"):
        print(f"ALERTA ESTRATÉGICO: Viés reverteu. Fechando posição em {symbol}...")
        close_position(float(client.get_symbol_ticker(symbol=symbol)['price']))

def close_position(exit_price):
    global trade_state
    symbol = trade_state['symbol']
    try:
        if trade_state.get('oco_order_id'):
            print(f"Cancelando ordem OCO {trade_state['oco_order_id']} para {symbol}...")
            client.cancel_order(symbol=symbol, orderListId=trade_state['oco_order_id'])
    except BinanceAPIException as e:
        print(f"Aviso ao cancelar ordem OCO para {symbol}: {e}")

    try:
        side_to_close = Client.SIDE_SELL if trade_state['side'] == Client.SIDE_BUY else Client.SIDE_BUY
        order = client.create_order(symbol=symbol, side=side_to_close, type=Client.ORDER_TYPE_MARKET, quantity=trade_state['quantity'])
        print(f"POSIÇÃO ZERADA COM SUCESSO @ {order['fills'][0]['price']}!")
    except Exception as e:
        print(f"ERRO CRÍTICO AO TENTAR ZERAR A POSIÇÃO de {symbol}: {e}")
    finally:
        # Reset do estado
        trade_state = {'in_position': False, 'symbol': None}

# ==============================================================================
# 5. FUNÇÕES PRINCIPAIS E THREADING
# ==============================================================================

def run_cerebro_loop():
    print(">>> Thread do CÉREBRO iniciada.")
    while True:
        try:
            analyze_market_and_update_state(volatilidade_local=1.5) 
            time.sleep(INTERVALO_ANALISE_CEREBRO)
        except Exception as e:
            print(f"ERRO na thread do Cérebro: {e}")
            time.sleep(60)

def run_robo_executor_loop():
    print(">>> Thread do ROBÔ EXECUTOR iniciada.")
    if not connect_to_binance():
        print("[ROBÔ] Falha crítica de conexão. A thread será encerrada.")
        return
    
    while True:
        try:
            if trade_state['in_position']:
                manage_position()
            else:
                check_for_entry()
            time.sleep(INTERVALO_VERIFICACAO_ROBO)
        except Exception as e:
            print(f"ERRO no loop do robô: {e}")
            time.sleep(60)

if __name__ == '__main__':
    cerebro_thread = threading.Thread(target=run_cerebro_loop)
    robo_thread = threading.Thread(target=run_robo_executor_loop)
    
    print("\n================================================")
    print("=     SISTEMA ARES CRYPTO UNIFICADO v3.1       =")
    print("=      Cérebro e Robô rodando em paralelo.     =")
    print("================================================\n")

    cerebro_thread.start()
    time.sleep(5) 
    robo_thread.start()
