from binance.client import Client
import threading
from binance import ThreadedWebsocketManager
import sys
import os
import time
import math
import requests
import pandas as pd
import numpy as np
from decimal import Decimal
from datetime import datetime, timezone
from dotenv import load_dotenv

# Settings for on screen debugging
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 0)  # usa la larghezza massima del terminale

#init section
if len(sys.argv) != 2:
    print("Usage: python3 trade_one_macd_close_true.py SYMBOL")
    sys.exit(1)
    
sym = sys.argv[1].upper()

load_dotenv() #loads Binance Api Keys and secrets from .env
api_key = os.getenv("api_key")
api_secret = os.getenv("api_secret")

client = Client(api_key, api_secret)

# Configure Binance API
BASE_URL = "https://api.binance.com/api/v3/"
url_t = "https://api.binance.com/api/v3/ticker/price"
SYMBOL = sym+"USDT"

#get decimal digits for price and quantity to match crypto format
info = client.get_symbol_info(SYMBOL)
tick_size = [f["tickSize"] for f in info["filters"] if f["filterType"] == "PRICE_FILTER"][0]
step_size = [f["stepSize"] for f in info["filters"] if f["filterType"] == "LOT_SIZE"][0]
precision_p = len(tick_size.rstrip('0').split('.')[-1])
precision_q = len(step_size.rstrip('0').split('.')[-1])  # Conta i decimali validi

def get_balances(): #Gets actual balances in your account
    usdt_balance = float(client.get_asset_balance(asset='USDT')['free'])
    crypto_balance = float(client.get_asset_balance(asset=sym)['free'])
    return usdt_balance, crypto_balance

def fetch_candles(df_candles, TIMEFRAME = "1h"): #Gets candles 
    
    url = f"{BASE_URL}klines?symbol={SYMBOL}&interval={TIMEFRAME}&limit={500 if df_candles is None else 2}"
    max_wait = 60  # massimo 60 secondi totali
    wait_per_try = 5  # 5 secondi tra un tentativo e l'altro
    elapsed = 0
    
    while True:
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            data = np.array(response.json(), dtype=object)
            break  # No errors
        except Exception as e:
            print(f"Errore: {e}")
            elapsed += wait_per_try
            
            if elapsed >= max_wait:
                print("Timeout. Give up.")
                exit()
                
            print(f"Retry in {wait_per_try} seconds... (Elapsed: {elapsed}s)")
            time.sleep(wait_per_try)

    # Estract data
    timestamps = data[:, 0].astype(np.int64)  # Timestamp in ms
    open_prices = data[:, 1].astype(np.float64)
    high_prices = data[:, 2].astype(np.float64)
    low_prices = data[:, 3].astype(np.float64)
    close_prices = data[:, 4].astype(np.float64)
    volumes = data[:, 5].astype(np.float64)

    # Creates DataFrame for new data
    new_df = pd.DataFrame({
        "timestamp": pd.to_datetime(timestamps, unit='ms'),
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volumes
    })

    # Removes most recent candle (still open)
    new_df = new_df.iloc[:-1]

    if df_candles is None:
        df_candles = new_df  # Init DataFrame
    else:
        latest_timestamp = df_candles.iloc[-1]["timestamp"]

        if new_df.iloc[-1]["timestamp"] > latest_timestamp:
            df_candles = pd.concat([df_candles, new_df], ignore_index=True)  # Aggiungi la nuova candela chiusa

    return df_candles

def adjust_quantity(quantity, step_size):
    # Moltiply quantity per 10^step_size to get precision
    multiplier = 10 ** step_size
    return math.floor(quantity * multiplier) / multiplier

def calculate_rsi(df, period=21):
    df = df.copy()
    close = df['close'].astype(np.float64)
    delta = close.diff().to_numpy(dtype=np.float64)

    up = np.where(delta > 0, delta, 0)
    down = np.where(delta < 0, -delta, 0)

    avg_up = np.full_like(close, fill_value=np.nan, dtype=np.float64)
    avg_down = np.full_like(close, fill_value=np.nan, dtype=np.float64)

    avg_up[period - 1] = np.mean(up[:period])
    avg_down[period - 1] = np.mean(down[:period])

    for i in range(period, len(close)):
        avg_up[i] = (avg_up[i - 1] * (period - 1) + up[i]) / period
        avg_down[i] = (avg_down[i - 1] * (period - 1) + down[i]) / period

    rs = avg_up / avg_down
    rsi = 100 - (100 / (1 + rs))

    df['RSI21'] = rsi
    
    return df

def regression_channel_with_std_dev(df, window=14, k=2):
    
    df = df.copy()

    lower_line = [None] * len(df)
    upper_line = [None] * len(df)
    slope = [None] * len(df)

    hl2 = ((df['high'] + df['low']) / 2).apply(lambda v: Decimal(str(v)))

    for i in range(window - 1, len(df)):
        x = list(range(window))
        y_window = hl2.iloc[i - window + 1:i + 1].tolist()
        y_float = [float(y) for y in y_window]  # per polyfit

        m, b = np.polyfit(x, y_float, 1)
        m_dec = Decimal(str(m))
        b_dec = Decimal(str(b))

        regression = [m_dec * Decimal(j) + b_dec for j in x]
        residuals = [y_window[j] - regression[j] for j in x]
        std_dev = Decimal(str(np.std([float(r) for r in residuals])))

        # Upper and lower band: ±2 std_dev
        upper_line[i] = regression[-1] + k * std_dev
        lower_line[i] = regression[-1] - k * std_dev
        slope[i] = m_dec

    df['Lower_Channel_Line'] = lower_line
    df['Higher_Channel_Line'] = upper_line
    df['Lower_Channel_Slope'] = slope

    return df

def regression_channel_validate_pattern(df):

    n = len(df)

    y_window = df['low'].to_numpy(dtype=np.float64)
    #y_window = df['hl2'].to_numpy(dtype=np.float64)
    x = np.arange(n, dtype=np.float64)

    # regression
    m, b = np.polyfit(x, y_window, 1)
    regression = m * x + b

    residuals = y_window - regression
    std_dev = np.std(residuals)

    # ===== k dynamic R² =====
    y_mean = np.mean(y_window)
    ss_tot = np.sum((y_window - y_mean) ** 2)
    ss_res = np.sum(residuals ** 2)

    r2 = 1.0 - (ss_res / ss_tot if ss_tot != 0 else 0.0)
    k_dyn = 2.0 * (1.5 - r2)
    print(f"k = {k_dyn}")
    # projection point n (calculates n+1)
    next_regression = m * n + b

    upper = next_regression + k_dyn * std_dev
    lower = next_regression - k_dyn * std_dev
    
    slope = m

    threshold = (np.max(y_window) - np.min(y_window)) / n * 0.1

    if slope > threshold:
        trend = "up"
    elif slope < -threshold:
        trend = "down"
    else:
        trend = "flat"

    return lower,trend 
    
def place_order(order_type, quantity, ctx):
    
    print(f"------------------Inserting {order_type} order. Wait...")
    try:
        stop_price = f"{ctx['stop_price']:.{precision_p}f}"
        if order_type == "BUY":
            limit_price = ctx['stop_price'] + ctx['stop_price'] * 0.002
        else:
            limit_price = ctx['stop_price'] - ctx['stop_price'] * 0.002 
        limit_price = f"{limit_price:.{precision_p}f}"
        print(stop_price)
        print(limit_price)
        
        order = client.create_order(
            symbol=SYMBOL,
            side=order_type,
            type="STOP_LOSS_LIMIT",
            timeInForce="GTC",
            quantity=quantity,
            price=limit_price,
            stopPrice=stop_price)

        while 'orderId' not in order:
            time.sleep(1)

        ctx['order_id'] = order['orderId']
        order = client.get_order(symbol=SYMBOL, orderId=ctx['order_id'])
        print(order)

        return ctx
    except Exception as e:
        print(f"Error placibg order: {e} - Stato: {ctx}")
        exit()

def price_now():
    #Gets actual price
    while True:
        try:
            r = requests.get(url_t, params={"symbol": SYMBOL}, timeout=5)
            r.raise_for_status()
            data = r.json()
            if "price" not in data:
                raise ValueError(data)
            return float(data["price"])
        except Exception as e:
            print(f"Errore RT Price: {e}")
            time.sleep(3)
            
def state_wait_green(df, params_daily, ctx):  
    
    #Defines start of pattern
    if ctx['pattern_start'] == 0:
        ctx['idx'] = len(df) - 4
        while ctx['idx'] < len(df):
            row = df.iloc[ctx['idx']]
            if (row['is_green']
                and row['RSI21'] < 56
                and row['close'] <= row['Higher_Channel_Line']
                and row['body_pct'] >= params_daily['first_body_min']):
                ctx['pattern_start'] = ctx['idx']
                break
            ctx['idx'] += 1

        if ctx['pattern_start'] == 0: #No pattern yet
            ctx['idx'] = 0
            return "CHECK_PATTERN",ctx
    elif  len(df) - ctx['pattern_start'] < 5:
        ctx['idx'] = ctx['pattern_start']
    else: #restart waiting a new pattern start
        ctx['idx'] = 0
        ctx['pattern_start'] = 0
        return "CHECK_PATTERN", ctx
    
    #counting red candles - max 1
    num_k = 2
    count_red = df.iloc[ctx['idx']:]['is_red'].sum()
    
    if count_red > 0: #check red candle body size
        mask = df['is_red'].to_numpy()
        pos = ctx['idx'] + mask[ctx['idx']:].argmax()
        
        if df.iloc[pos]['body_pct'] > 0.2:
            num_k = 3 #adds 1 nore candle to pattern
        else:
            num_k = 2
    
    if len(df) - ctx['idx'] > num_k: #Pattern 3 candele verdi o 4 se rossa presente
        #Counting hl2 downs

        drops = 0
        rises = 0
        segment = df.iloc[ctx['idx']:]
        hl2 = segment['hl2']

        for prev, curr in zip(hl2, hl2[1:]):
            if prev > curr:
                drops += 1
            else:
                rises += 1
                if rises == 2 and drops == 0:
                    ctx['waiting'] = 5
                    return "TRADING_ON",ctx

        if drops < 2: #Buy signal
            ctx['waiting'] = 5
            return "TRADING_ON",ctx
        else: #Too many downs - give up
            ctx['idx'] = 0
            ctx['pattern_start'] = 0
            return "CHECK_PATTERN", ctx
    
    #Pattern not yet completed
    return "CHECK_PATTERN", ctx
    
def trading_on(df, params_daily, ctx):

    latest_d = df.iloc[-1]
    lr,trend = regression_channel_validate_pattern(df.iloc[ctx['pattern_start']:])
    lr = lr - lr * 0.002 #buffering

    if trend == "down":
        ctx['base'] = latest_d['hl2']
    else:
        ctx['base'] = min(latest_d['hl2'], lr)
    
    print(ctx['base'])
    
    usdt_balance, crypto_balance = get_balances()
            
    #To Buy check pattern 3+1 candles +RSI
    #To Sell check breakdown lr channel lr o hl2                                    
    if ctx['last_signal'] != "BUY":
        
        if usdt_balance > 100:  # Evita operazioni troppo piccole
            
            price_t = price_now()
            
            if price_t < ctx['base']: #Annulla BUY order
                print("------------------Pattern violation - Trading cancelled")
                ctx['last_signal'] = None
                ctx['order_id'] = None
                ctx['idx'] = 0
                ctx['pattern_start'] = 0
                ctx['waiting'] = 86407
                now = datetime.now(timezone.utc)
                print(f"{now} - Current USDT Balance: {usdt_balance:.2f} - {sym} Balance: {crypto_balance:.8f}")
                return "CHECK_PATTERN",ctx

            max_high = df.iloc[ctx['pattern_start']:]['high'].max()
            ctx['stop_price'] = max_high * params_daily['entry_buffer_pct'] + max_high
            buy_price = ctx['stop_price'] * 0.0015 + ctx['stop_price']

            quantity = (usdt_balance / buy_price) * 0.98
            quantity = adjust_quantity(quantity, precision_q)

            ctx = place_order("BUY", quantity, ctx)
            ctx['last_signal'] = "BUY"
            time.sleep(3)
            usdt_balance, crypto_balance = get_balances()
           
            threading.Thread(target=monitor_price, args=(quantity,ctx), daemon=True).start()

        ctx['waiting'] = 86407 
        return "TRADING_ON",ctx
        
    elif ctx['last_signal'] == "BUY":     
        order_status = client.get_order(symbol=SYMBOL, orderId=ctx['order_id'])
        print(order_status)
        side = order_status['side']
        status = order_status['status']
        
        if side == "SELL" and status != "FILLED":
            print(f"------------------Order {tx['order_id']} non eseguito : Attaualizzazione")
            client.cancel_order(symbol=SYMBOL, orderId=ctx['order_id'])
                        
            print(f"------------------Waiting order cancellation {ctx['order_id']}")
            while status != "CANCELED":
                time.sleep(5)
                order_status = client.get_order(symbol=SYMBOL, orderId=ctx['order_id'])
                status = order_status['status']
                 
            print(f"------------------Order {ctx['order_id']} cancellation confirmed.")
        
            print("------------------Inserting new order SELL STOP LIMIT")
            ctx['stop_price'] = ctx['base']
            usdt_balance, crypto_balance = get_balances()
            crypto_balance = adjust_quantity(crypto_balance, precision_q)
            ctx = place_order("SELL", crypto_balance, ctx)
        elif status == "CANCELLED" or (status == "FILLED" and side == "SELL"): # Pattern violato o asset venduto. Reset.
            usdt_balance, crypto_balance = get_balances()
            ctx['last_signal'] = None
            ctx['order_id'] = None
            ctx['idx'] = 0
            ctx['pattern_start'] = 0
            ctx['waiting'] = 86407
            now = datetime.now(timezone.utc)
            print(f"------------------FSM Reset - Order {ctx['order_id']} Cancellation or sell")
            print(f"{now} - Current USDT Balance: {usdt_balance:.2f} - {sym} Balance: {crypto_balance:.8f}")
            return "CHECK_PATTERN",ctx

    time.sleep(5)
    usdt_balance, crypto_balance = get_balances()
    now = datetime.now(timezone.utc)
    print(f"\n{now} - Current USDT Balance: {usdt_balance:.2f} - {sym} Balance: {crypto_balance:.8f}")
    ctx['waiting'] = 86407
    return "TRADING_ON",ctx

def check_trade_signal():
    global precision_p, precision_q
    
    df = None    
    ctx = {'idx': 0, 
           'pattern_start': 0,
           'last_signal': None,
           'base': 0,
           'stop_price': 0,
           'order_id': None,
           'waiting': 86407
    }
    
    params_daily = {
        'first_body_min': 0.55,
        'entry_buffer_pct': 0.002
    }

    daily_handlers = {
        "CHECK_PATTERN": lambda df, params, ctx: state_wait_green(df, params, ctx),
        "TRADING_ON": lambda df, params, ctx: trading_on(df, params, ctx),
    }
    
    daily_state = "CHECK_PATTERN"

    while True:
        now = datetime.now(timezone.utc)

        try:
            if df is None or df.empty or now.hour == 0:
                df = fetch_candles(df,"1d")
                df['is_green'] = df['close'] > df['open']
                df['is_red'] = df['close'] < df['open']
                df['body_pct'] = (df['close'] - df['open']).abs() / df['open'] * 100
                df['hl2'] = (df['high'] + df['low']) / 2
                df = calculate_rsi(df, 21)
                df = regression_channel_with_std_dev(df, 5, 2)
                
                print(df[-10:])
                print(len(df))

            #FSM
            daily_state, ctx = daily_handlers[daily_state](df, params_daily, ctx)
                    
            now = datetime.now(timezone.utc)
                        
            if ctx["waiting"] == 5:
                waiting = ctx["waiting"]
            else:
                waiting = ctx["waiting"] - ((now.hour * 60 + now.minute) * 60 + now.second)

            print(f"{now} - Current State: {daily_state} - {sym} - PS: {ctx['pattern_start']} - W: {waiting}")
            time.sleep(waiting+5) # Aspetta il tempo impostato in ctx["waiting"] 
        except Exception as e:
            print(f"Error Checking price: {e} - Stato: {daily_state}")
            time.sleep(15)
       
def monitor_price(quantity, ctx):
    global precision_p, precision_q

    print(f"------------------Waiting order {ctx['order_id']} executed\n")
    status = None
    while status != 'FILLED':

        price_t = price_now()

        if price_t < ctx['base']: #Annulla BUY order
            print(f"------------------BUY order {ctx['order_id']} cancellation")
            client.cancel_order(symbol=SYMBOL, orderId=ctx['order_id'])

            while status != "CANCELED":
                time.sleep(5)
                order_status = client.get_order(symbol=SYMBOL, orderId=ctx['order_id'])
                status = order_status['status']
                
            ctx['last_signal'] = None
            print(f"------------------BUY order {ctx['order_id']} removed")
            return

        time.sleep(90)      
        try:
            order_status = client.get_order(symbol=SYMBOL, orderId=ctx['order_id'])
            status = order_status['status']
        except Exception as e:
            print(f"Error while waiting BUY execution: {e}")
            continue

    #Insert Sell order with STOP LIMIT base
    
    ctx['stop_price'] = ctx['base']
    
    usdt_balance, crypto_balance = get_balances()
    crypto_balance = adjust_quantity(crypto_balance, precision_q)
    ctx = place_order("SELL", crypto_balance, ctx)
    return

def main():
    check_trade_signal()

if __name__ == "__main__":
    main()
