import pandas as pd
from binance.client import Client
from binance.enums import *
import time
import keyler  # API ve telegram bilgileri burada
from datetime import datetime
from decimal import Decimal
import requests
import os

# Binance istemcisi
client = Client(keyler.api_key, keyler.api_secret)

# Telegram bilgileri
TELEGRAM_TOKEN = keyler.telegram_token
CHAT_ID = keyler.telegram_chat_id

# Ayarlar
SELL_THRESHOLD = 55
BUY_THRESHOLD = 35
DAILY_BUY_LIMIT = 50
EXCEL_FILE = "işlem_raporu.xlsx"
ALIM_HAKKI_FILE = "alim_hakki.xlsx"
CHECK_INTERVAL = 20

# Telegram bildirimi
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.get(url, params=params)
    except Exception as e:
        print(f"Telegram bildirimi gönderilemedi: {e}")

# Sunucu zamanını senkronize et
def sync_time():
    try:
        server_time = client.get_server_time()['serverTime']
        local_time = int(time.time() * 1000)
        client.timestamp_offset = server_time - local_time
    except Exception as e:
        print(f"Zaman senkronizasyon hatası: {e}")

# Excel kaydı
def write_to_excel(asset, quantity, price, total_value, action, remaining_value, buy_limit_remaining, alim_hakki):
    data = {
        "İşlem": [action],
        "Varlık": [asset],
        "Miktar": [quantity],
        "Fiyat (USDT)": [price],
        "Toplam Değer (USDT)": [total_value],
        "Kalan Bakiye (USDT)": [remaining_value],
        "Alım Hakkı": [alim_hakki],
        "Günlük Harcama (USDT)": [buy_limit_remaining],
        "Tarih-Saat": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    }
    df = pd.DataFrame(data)
    try:
        existing_df = pd.read_excel(EXCEL_FILE)
        df = pd.concat([existing_df, df], ignore_index=True)
    except FileNotFoundError:
        pass
    df.to_excel(EXCEL_FILE, index=False)

# Hakları kaydet
def save_alim_hakki(coin_list):
    df = pd.DataFrame(coin_list)
    df.to_excel(ALIM_HAKKI_FILE, index=False)

# Hakları yükle
def load_alim_hakki():
    if os.path.exists(ALIM_HAKKI_FILE):
        df = pd.read_excel(ALIM_HAKKI_FILE)
        coin_list = df.to_dict(orient='records')
        return coin_list
    return None

# İşlem miktarını adım büyüklüğüne göre ayarla
def adjust_quantity(qty, step_size):
    return float((Decimal(str(qty)) // Decimal(str(step_size))) * Decimal(str(step_size)))

# İşlem çiftinin limit bilgileri
def get_symbol_info(symbol):
    exchange_info = client.get_exchange_info()
    min_qty, step_size, min_notional = 0.0001, 0.0001, 10
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    min_qty = float(f.get('minQty', 0.0001))
                    step_size = float(f.get('stepSize', 0.0001))
                elif f['filterType'] == 'MIN_NOTIONAL':
                    min_notional = float(f.get('minNotional', 10))
            break
    return min_qty, step_size, min_notional

# USDT işlem çiftini bul
def find_usdt_pair(asset):
    try:
        symbol = f"{asset}USDT"
        client.get_symbol_ticker(symbol=symbol)
        return symbol
    except:
        return None

# İlk tarama veya Excel’den yükleme
def initial_scan():
    coin_list = load_alim_hakki()
    if coin_list:
        print(f"{len(coin_list)} coin alım hakları yüklendi.")
        return coin_list
    margin_account = client.get_margin_account()
    coin_list = []
    print("İlk tarama: Coinler belirleniyor...")
    for a in margin_account['userAssets']:
        symbol = find_usdt_pair(a['asset'])
        if symbol:
            coin_list.append({
                "asset": a['asset'],
                "symbol": symbol,
                "alim_hakki": 3,
                "satilan_sayisi": 0
            })
    print(f"{len(coin_list)} coin bulundu.")
    save_alim_hakki(coin_list)
    return coin_list

# Coin bakiyelerini güncelle
def update_coin_balances(coin_list):
    margin_account = client.get_margin_account()
    balances = {a['asset']: (float(a['free']), float(a['borrowed'])) for a in margin_account['userAssets']}
    updated_assets = []
    for c in coin_list:
        free, borrowed = balances.get(c['asset'], (0,0))
        net_balance = free - borrowed
        if net_balance <= 0:
            continue
        try:
            price = float(client.get_symbol_ticker(symbol=c['symbol'])['price'])
            value_usdt = net_balance * price
            updated_assets.append({
                **c,
                "net_balance": net_balance,
                "price": price,
                "value_usdt": value_usdt
            })
        except Exception as e:
            print(f"{c['asset']} fiyat alınamadı: {e}")
    return updated_assets

# Satış işlemleri
def sell_assets(asset_details, coin_list):
    for asset in asset_details:
        if asset["value_usdt"] > SELL_THRESHOLD:
            excess_value = asset["value_usdt"] - SELL_THRESHOLD
            sell_quantity = adjust_quantity(excess_value / asset["price"], get_symbol_info(asset["symbol"])[1])
            if sell_quantity * asset["price"] < get_symbol_info(asset["symbol"])[2]:
                continue
            try:
                client.create_margin_order(
                    symbol=asset["symbol"],
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=sell_quantity,
                    isIsolated=False
                )
                # Alım hakkını artır
                for c in coin_list:
                    if c["asset"] == asset["asset"]:
                        c["satilan_sayisi"] += 1
                        c["alim_hakki"] = min(3 + c["satilan_sayisi"], c["alim_hakki"] + 1)
                        break
                remaining_value = asset["net_balance"] * asset["price"] - sell_quantity * asset["price"]
                write_to_excel(asset['asset'], sell_quantity, asset['price'], sell_quantity * asset['price'],
                               "SATIŞ", remaining_value, DAILY_BUY_LIMIT, [c for c in coin_list if c["asset"]==asset["asset"]][0]["alim_hakki"])
                send_telegram(f"[SATIŞ] {asset['asset']} {sell_quantity:.6f} satıldı. Fiyat: {asset['price']:.2f} USDT\nKalan Bakiye: {remaining_value:.2f} USDT")
            except Exception as e:
                print(f"{asset['asset']} satışı başarısız: {e}")
    save_alim_hakki(coin_list)

# Alım işlemleri
def buy_assets(asset_details, coin_list, daily_spent):
    usdt_balance = next((a["net_balance"] for a in asset_details if a["asset"]=="USDT"), 0)
    for asset in asset_details:
        if asset["asset"]=="USDT":
            continue
        coin_info = next((c for c in coin_list if c["asset"]==asset["asset"]), None)
        if not coin_info or coin_info["alim_hakki"] <= 0:
            continue
        if asset["value_usdt"] < BUY_THRESHOLD and usdt_balance > 0:
            buy_value = min(BUY_THRESHOLD - asset["value_usdt"], DAILY_BUY_LIMIT - daily_spent, usdt_balance)
            if buy_value <= 0:
                send_telegram(f"🚨 Günlük alım limiti ({DAILY_BUY_LIMIT} USDT) doldu!")
                break
            buy_quantity = adjust_quantity(buy_value / asset["price"], get_symbol_info(asset["symbol"])[1])
            if buy_quantity * asset["price"] < get_symbol_info(asset["symbol"])[2]:
                continue
            try:
                client.create_margin_order(
                    symbol=asset["symbol"],
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=buy_quantity,
                    isIsolated=False
                )
                coin_info["alim_hakki"] -= 1
                daily_spent += buy_quantity * asset["price"]
                remaining_value = asset["net_balance"] * asset["price"] + buy_quantity * asset["price"]
                write_to_excel(asset['asset'], buy_quantity, asset['price'], buy_quantity * asset['price'],
                               "ALIM", remaining_value, DAILY_BUY_LIMIT - daily_spent, coin_info["alim_hakki"])
                send_telegram(f"[ALIM] {asset['asset']} {buy_quantity:.6f} alındı. Fiyat: {asset['price']:.2f} USDT\nAlım Hakkı: {coin_info['alim_hakki']}\nGünlük Harcama: {daily_spent:.2f}/{DAILY_BUY_LIMIT} USDT")
            except Exception as e:
                print(f"{asset['asset']} alımı başarısız: {e}")
    save_alim_hakki(coin_list)
    return daily_spent

def main():
    sync_time()
    coin_list = initial_scan()
    current_day = datetime.now().day
    daily_spent = 0

    while True:
        try:
            if datetime.now().day != current_day:
                current_day = datetime.now().day
                daily_spent = 0

            asset_details = update_coin_balances(coin_list)
            sell_assets(asset_details, coin_list)
            daily_spent = buy_assets(asset_details, coin_list, daily_spent)
        except Exception as e:
            print(f"Hata oluştu: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
