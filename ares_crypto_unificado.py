# ==============================================================================
#      SISTEMA ARES CRYPTO UNIFICADO v4.2 - MODO DE DIAGNÓSTICO DE REDE
# ==============================================================================
import time
import requests
import os
import threading
from binance.client import Client
from binance.exceptions import BinanceAPIException
import numpy as np
import pandas as pd
import pandas_ta as ta
from flask import Flask, jsonify
import logging

# --- 1. CONFIGURAÇÕES ---
API_KEY = os.environ.get('API_KEY')
API_SECRET = os.environ.get('API_SECRET')
# ... (outras configurações permanecem as mesmas)

# --- Variáveis Globais ---
client = None
trade_state = {'in_position': False}
cerebro_data = {'trade_bias': 'NEUTRO'}

# ==============================================================================
# 2. LÓGICA DO ROBÔ (FUNÇÃO DE CONEXÃO COM DIAGNÓSTICO)
# ==============================================================================
def connect_to_binance():
    global client
    print("[ROBÔ - DIAGNÓSTICO] Passo 1: Iniciando função connect_to_binance.")
    
    if not API_KEY or not API_SECRET:
        print("[ROBÔ - DIAGNÓSTICO] ERRO FATAL: Chaves de API não encontradas no ambiente.")
        return False
        
    print("[ROBÔ - DIAGNÓSTICO] Passo 2: Chaves encontradas. Preparando para criar o objeto 'Client'.")
    
    try:
        # Tentativa de conexão com timeout
        client = Client(api_key=API_KEY, api_secret=API_SECRET, tld='com', requests_params={'timeout': 20})
        print("[ROBÔ - DIAGNÓSTICO] Passo 3: Objeto 'Client' criado com sucesso.")
        
        # Teste de autenticação
        print("[ROBÔ - DIAGNÓSTICO] Passo 4: Tentando executar get_account_status() para testar a autenticação...")
        client.get_account_status()
        print(">>> [ROBÔ] Conexão com a Binance 100% estabelecida e autenticada.")
        return True
        
    except requests.exceptions.Timeout:
        print("[ROBÔ - DIAGNÓSTICO] ERRO DE REDE: Timeout! A conexão com a Binance expirou (20s). O Firewall do Render pode estar bloqueando a saída.")
        return False
    except BinanceAPIException as e:
        print(f"[ROBÔ - DIAGNÓSTICO] ERRO DE API BINANCE durante a conexão: {e}")
        return False
    except Exception as e:
        print(f"[ROBÔ - DIAGNÓSTICO] ERRO INESPERADO durante a conexão: {e}")
        return False

# ==============================================================================
# 3. LOOPS PRINCIPAIS E THREADING (Simplificados para o teste)
# ==============================================================================

def run_robo_executor_loop():
    print(">>> Thread do ROBÔ EXECUTOR iniciada.")
    # Apenas tenta conectar uma vez para o diagnóstico.
    connect_to_binance()
    print(">>> Fim do teste de conexão da thread do robô.")
    # Em um cenário real, o loop continuaria aqui.
    # while True: ...

# --- PONTO DE PARTIDA DO SCRIPT ---
if __name__ == '__main__':
    # Para este teste, vamos rodar apenas a conexão do robô para focar no problema.
    print("\n================================================")
    print("=     SISTEMA ARES CRYPTO - MODO DIAGNÓSTICO     =")
    print("=      Testando apenas a conexão com a Binance.    =")
    print("================================================\n")
    
    run_robo_executor_loop()
