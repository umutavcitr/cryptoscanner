import time
import datetime
import requests
import pandas as pd
import talib
import os

# API URL'leri
BINANCE_URL = 'https://api.binance.com/api/v3/'
COINGECKO_URL = 'https://api.coingecko.com/api/v3/coins/markets'

# Telegram bilgileri
TELEGRAM_BOT_TOKEN = '7977987435:AAE_t5Ey6tXZbZKTDoidAb_V_FGwfqyGR7U'
TELEGRAM_CHAT_ID = '456872480'

# Hafıza dosyası
LAST_PAIRS_FILE = 'last_pairs.txt'

# Eski değen coinler
def load_last_pairs():
    if os.path.exists(LAST_PAIRS_FILE):
        with open(LAST_PAIRS_FILE, 'r') as file:
            return set(file.read().splitlines())
    return set()

def save_last_pairs(pairs):
    with open(LAST_PAIRS_FILE, 'w') as file:
        for pair in pairs:
            file.write(pair + '\n')

last_touched_pairs = load_last_pairs()

# Telegram mesaj gönderme
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    params = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message
    }
    try:
        requests.post(url, params=params)
    except Exception as e:
        print(f"Telegram mesaj gönderilemedi: {e}")

# CoinGecko’dan en büyük 100 coin’i çek
def get_top_100_coins():
    params = {
        'vs_currency': 'usd',
        'order': 'market_cap_desc',
        'per_page': 100,
        'page': 1
    }
    response = requests.get(COINGECKO_URL, params=params)
    data = response.json()
    return [coin['symbol'].upper() for coin in data]

# Binance’teki USDT paritelerini çek
def get_usdt_pairs(top_coins):
    response = requests.get(BINANCE_URL + 'exchangeInfo')
    data = response.json()
    usdt_pairs = []
    for symbol in data['symbols']:
        if symbol['quoteAsset'] == 'USDT' and symbol['status'] == 'TRADING':
            base = symbol['baseAsset']
            if base in top_coins:
                usdt_pairs.append(symbol['symbol'])
    return usdt_pairs

# Tarihsel veriyi çek (timestamp güncellemesiyle)
def get_historical_data(symbol, interval='1h', limit=100):
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    response = requests.get(BINANCE_URL + 'klines', params=params)
    data = response.json()

    ohlcv = []
    for row in data:
        timestamp = datetime.datetime.fromtimestamp(row[0] / 1000, tz=datetime.timezone.utc)
        ohlcv.append([timestamp, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])

    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df.set_index('timestamp', inplace=True)
    return df

# EMA ve MACD hesapla
def calculate_indicators(df):
    df['ema50'] = talib.EMA(df['close'], timeperiod=50)
    macd, macdsignal, _ = talib.MACD(df['close'], fastperiod=12, slowperiod=26, signalperiod=9)
    df['macd'] = macd
    df['macdsignal'] = macdsignal
    upper, middle, lower = talib.BBANDS(df['close'], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    df['upper_band'] = upper
    df['middle_band'] = middle
    df['lower_band'] = lower
    return df

# Günlük grafikte trend kontrolü
def check_trend(df):
    close = df['close'].iloc[-1]
    ema50 = df['ema50'].iloc[-1]
    macd_val = df['macd'].iloc[-1]
    macdsignal_val = df['macdsignal'].iloc[-1]

    if close > ema50 and macd_val > macdsignal_val:
        return 'Yükselen', '🟢'
    elif close < ema50 and macd_val < macdsignal_val:
        return 'Düşen', '🔴'
    else:
        return 'Düz', '🟡'

# Saatlik grafikte Bollinger kontrolü ve orta banda uzaklık hesaplama
def check_bollinger(df):
    touches = []
    close = df['close'].iloc[-1]
    upper = df['upper_band'].iloc[-1]
    lower = df['lower_band'].iloc[-1]
    middle = df['middle_band'].iloc[-1]
    distance_percent = abs(close - middle) / middle * 100

    if close <= lower:
        touches.append(('Alt banda değdi 🔴', distance_percent))
    if close >= upper:
        touches.append(('Üst banda değdi 🟢', distance_percent))

    return touches

# Coinleri tarama fonksiyonu
def scan_coins():
    global last_touched_pairs
    print("\nCoinGecko’dan marketcap'i en yüksek ilk 100 coin çekildi... \nBinance'de USDT paritesi olanlar ayıklanıyor \nTaramaya başlandı...  ")
    top_coins = get_top_100_coins()
    usdt_pairs = get_usdt_pairs(top_coins)
    current_touched = set()
    newly_touched = []

    for symbol in usdt_pairs:
        print(f"Taranıyor: {symbol}")
        try:
            df_1h = get_historical_data(symbol, interval='1h')
            df_1d = get_historical_data(symbol, interval='1d')
        except Exception as e:
            print(f"Veri alınamadı: {symbol}, Hata: {e}")
            continue

        df_1h = calculate_indicators(df_1h)
        df_1d = calculate_indicators(df_1d)

        trend, trend_icon = check_trend(df_1d)
        bollinger_touches = check_bollinger(df_1h)

        if bollinger_touches:
            current_touched.add(symbol)
            if symbol not in last_touched_pairs:
                for band_text, distance in bollinger_touches:
                    message = f"{symbol} - {trend_icon} {trend} - {band_text} - Orta banda uzaklık: %{distance:.2f}"
                    newly_touched.append(message)

    # Yeni değenler varsa yazdır ve Telegram’a gönder
    if newly_touched:
        output = "\n".join(newly_touched)
        print(output)
        send_telegram_message(output)
    else:
        print("Yeni bantlara değen coin yok.")

    # Hafızayı güncelle
    last_touched_pairs = current_touched
    save_last_pairs(last_touched_pairs)

    next_time = next_scan_time()
    print(f"\n⏳ Bir sonraki tarama: {next_time.strftime('%H:%M:%S')}\n")

# Bir sonraki tarama zamanı
def next_scan_time():
    now = datetime.datetime.now()
    next_hour = now.replace(minute=0, second=20, microsecond=0) + datetime.timedelta(hours=1)
    return next_hour

# Ana döngü
def start_scanner():
    print("Scanner başlatıldı...")
    while True:
        scan_coins()
        sleep_time = (next_scan_time() - datetime.datetime.now()).total_seconds()
        if sleep_time > 0:
            time.sleep(sleep_time)

# Programı çalıştır
if __name__ == "__main__":
    start_scanner()