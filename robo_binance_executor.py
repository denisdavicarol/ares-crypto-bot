# Robô Scanner de Portfólio para Binance - Ares Crypto v2.2 (Produção)
# VERSÃO 2.2: Versão estável sem dependência de notificações Telegram

import time
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException
import numpy as np
import pandas as pd
import pandas_ta as ta

# --- 1. CONFIGURAÇÕES ---
API_KEY = "PoAPxsWFDDO8U0uCyOCS0FD7wrkjwTLScxk9piQWmgZ2Ry9RPwg7vluwKZfHYQZc"
API_SECRET = "p1pPB1hlVa1MPPUNxayqcSinlqgQbLIK4kopP6XZ4WWZUD0ppd4BxoW4JvVfMlGZ"
CEREBRO_URL = "http://127.0.0.1:5001/predict/crypto"

SYMBOLS_TO_SCAN = ['BTCBRL', 'ETHBRL', 'SOLBRL', 'LINKBRL', 'ADABRL']
TIMEFRAME = Client.KLINE_INTERVAL_5MINUTE
RISK_PER_TRADE_BRL = 20.00
INTERVALO_SEGUNDOS = 180 

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

# --- 2. ESTADO E CONEXÃO ---
client = None
trade_state = {'in_position': False, 'symbol': None, 'side': None, 'entry_price': 0.0, 'oco_order_id': None, 'quantity': 0.0}
last_cerebro_bias = "NEUTRO"
last_cerebro_call = 0

def connect_to_binance():
    global client
    try:
        client = Client(API_KEY, API_SECRET)
        client.get_account()
        print(">>> Conexão com a Binance estabelecida com sucesso.")
        return True
    except BinanceAPIException as e:
        print(f"ERRO DE API BINANCE: Falha ao conectar. Verifique suas chaves. Erro: {e}")
        return False

# --- 3. FUNÇÕES DE LÓGICA DE TRADING ---

def get_cerebro_bias():
    try:
        klines = client.get_klines(symbol='BTCBRL', interval=Client.KLINE_INTERVAL_1MINUTE, limit=ATR_PERIOD)
        closes = [float(k[4]) for k in klines]
        df = pd.DataFrame(closes, columns=['close'])
        df.ta.atr(length=ATR_PERIOD, append=True)
        atr_value = df.iloc[-1][f'ATRr_{ATR_PERIOD}']
        volatilidade_local = (atr_value / closes[-1]) * 100
        
        url = f"{CEREBRO_URL}?modo_operacao=Auto&volatilidade_local={volatilidade_local}"
        response = requests.get(url, timeout=15).json()
        print(f"Cérebro respondeu. Viés: {response.get('trade_bias')} | Modo: {response.get('active_mode')}")
        return response.get('trade_bias')
    except Exception as e:
        print(f"ERRO ao consultar o Cérebro: {e}")
        return "NEUTRO"

def determinar_regime_local(df):
    try:
        df.ta.bbands(length=SQUEEZE_PERIOD, append=True)
        df.ta.kc(length=SQUEEZE_PERIOD, append=True)
        last = df.iloc[-1]
        if last[f'BBU_{SQUEEZE_PERIOD}_2.0'] < last[f'KCUe_{SQUEEZE_PERIOD}_2.0'] and last[f'BBL_{SQUEEZE_PERIOD}_2.0'] > last[f'KCLe_{SQUEEZE_PERIOD}_2.0']:
            return "SQUEEZE"
        else:
            return "TENDENCIA"
    except Exception as e:
        print(f"Erro ao determinar regime: {e}")
        return "TENDENCIA"

def buscar_gatilhos_tendencia(df, symbol, trade_bias):
    try:
        df.ta.ema(length=EMA_FAST_PERIOD, append=True)
        df.ta.ema(length=EMA_SLOW_PERIOD, append=True)
        df.ta.stoch(k=STOCH_K, d=STOCH_D, smooth_k=STOCH_SMOOTH, append=True)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])

        stoch_k_cross_up = prev[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] < prev[f'STOCHd_{STOCH_D}_{STOCH_D}_{STOCH_SMOOTH}'] and last[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] > last[f'STOCHd_{STOCH_D}_{STOCH_D}_{STOCH_SMOOTH}']
        if trade_bias == "COMPRADOR" and stoch_k_cross_up and last[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] < 50:
            print(f"GATILHO DE COMPRA (PULLBACK) em {symbol}.")
            return Client.SIDE_BUY

        stoch_k_cross_down = prev[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] > prev[f'STOCHd_{STOCH_D}_{STOCH_D}_{STOCH_SMOOTH}'] and last[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] < last[f'STOCHd_{STOCH_D}_{STOCH_D}_{STOCH_SMOOTH}']
        if trade_bias == "VENDEDOR" and stoch_k_cross_down and last[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] > 50:
            print(f"GATILHO DE VENDA (PULLBACK) em {symbol}.")
            return Client.SIDE_SELL
            
        if trade_bias == "COMPRADOR" and last[f'EMA_{EMA_FAST_PERIOD}'] > last[f'EMA_{EMA_SLOW_PERIOD}'] and last['low'] < last[f'EMA_{EMA_FAST_PERIOD}'] and last['close'] > last[f'EMA_{EMA_FAST_PERIOD}']:
             print(f"GATILHO DE COMPRA (IGNIÇÃO) em {symbol}.")
             return Client.SIDE_BUY

        if trade_bias == "VENDEDOR" and last[f'EMA_{EMA_FAST_PERIOD}'] < last[f'EMA_{EMA_SLOW_PERIOD}'] and last['high'] > last[f'EMA_{EMA_FAST_PERIOD}'] and last['close'] < last[f'EMA_{EMA_FAST_PERIOD}']:
             print(f"GATILHO DE VENDA (IGNIÇÃO) em {symbol}.")
             return Client.SIDE_SELL

        highest_high = df['high'][-MOMENTUM_PERIOD-1:-1].max()
        if trade_bias == "COMPRADOR" and current_price > highest_high:
            print(f"GATILHO DE COMPRA (MOMENTUM) em {symbol}.")
            return Client.SIDE_BUY
        
        lowest_low = df['low'][-MOMENTUM_PERIOD-1:-1].min()
        if trade_bias == "VENDEDOR" and current_price < lowest_low:
            print(f"GATILHO DE VENDA (MOMENTUM) em {symbol}.")
            return Client.SIDE_SELL

    except Exception as e:
        print(f"Erro nos gatilhos de tendência para {symbol}: {e}")
    return None

def buscar_gatilho_squeeze(df, symbol, trade_bias):
    try:
        high_range = df['high'][-SQUEEZE_PERIOD-1:-1].max()
        low_range = df['low'][-SQUEEZE_PERIOD-1:-1].min()
        current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])
        
        if trade_bias == "COMPRADOR" and current_price > high_range:
            print(f"GATILHO DE COMPRA (SQUEEZE) em {symbol}.")
            return Client.SIDE_BUY
        if trade_bias == "VENDEDOR" and current_price < low_range:
            print(f"GATILHO DE VENDA (SQUEEZE) em {symbol}.")
            return Client.SIDE_SELL
    except Exception as e:
        print(f"Erro no gatilho de squeeze para {symbol}: {e}")
    return None

def check_for_entry():
    global last_cerebro_call, trade_state
    
    if time.time() - last_cerebro_call < INTERVALO_SEGUNDOS: return
    
    last_cerebro_call = time.time()
    trade_bias = get_cerebro_bias()
    
    if trade_bias == "NEUTRO": return

    for symbol in SYMBOLS_TO_SCAN:
        try:
            klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=100)
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
            
            regime_local = determinar_regime_local(df)
            print(f"Analisando {symbol}... Regime: {regime_local}")
            
            side_to_trade = None
            if regime_local == "TENDENCIA": side_to_trade = buscar_gatilhos_tendencia(df, symbol, trade_bias)
            elif regime_local == "SQUEEZE": side_to_trade = buscar_gatilho_squeeze(df, symbol, trade_bias)
            
            if side_to_trade:
                place_order(symbol, side_to_trade)
                return 
        except Exception as e:
            print(f"Erro ao analisar o par {symbol}: {e}")
            continue

def place_order(symbol, side):
    global trade_state
    try:
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=ATR_PERIOD)
        df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','a','b','c','d','e','f'])
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].apply(pd.to_numeric)
        df.ta.atr(length=ATR_PERIOD, append=True)
        atr = df.iloc[-1][f'ATRr_{ATR_PERIOD}']

        stop_loss_distance = atr * SL_ATR_MULTIPLIER
        quantity = RISK_PER_TRADE_BRL / stop_loss_distance
        
        info = client.get_symbol_info(symbol)
        step_size = float([f['stepSize'] for f in info['filters'] if f['filterType'] == 'LOT_SIZE'][0])
        quantity = round(quantity / step_size) * step_size

        print(f"Enviando ordem a mercado: {side} {quantity:.8f} {symbol}")
        order = client.create_order(symbol=symbol, side=side, type=Client.ORDER_TYPE_MARKET, quantity=quantity)
        
        trade_state.update({
            'in_position': True, 'symbol': symbol, 'side': side,
            'entry_price': float(order['fills'][0]['price']), 'quantity': quantity
        })
        print(f"ORDEM EXECUTADA @ {trade_state['entry_price']}")
        place_oco_exit_orders()
    except Exception as e:
        print(f"ERRO AO ENVIAR ORDEM DE ENTRADA: {e}")

def place_oco_exit_orders():
    # A lógica para colocar as ordens de stop e alvo
    pass # Implementar a lógica completa aqui

def manage_position():
    # A lógica para gerenciar a posição aberta
    pass # Implementar a lógica completa aqui

# --- PROGRAMA PRINCIPAL ---
if __name__ == '__main__':
    if connect_to_binance():
        print("\n=======================================================")
        print("=     ROBÔ SCANNER ARES - v2.2 (Sem Notificações)     =")
        print(f"=        Escaneando {len(SYMBOLS_TO_SCAN)} pares...                     =")
        print("=======================================================")
        
        while True:
            try:
                if trade_state['in_position']:
                    manage_position()
                else:
                    check_for_entry()
                
                print(f"\nAguardando {INTERVALO_SEGUNDOS} segundos para o próximo ciclo...")
                time.sleep(INTERVALO_SEGUNDOS)
            except Exception as e:
                print(f"ERRO INESPERADO NO LOOP PRINCIPAL: {e}")
                time.sleep(60)