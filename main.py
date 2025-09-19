import pandas as pd
from binance.client import Client
from binance.enums import *
import time
import keyler
from datetime import datetime
from decimal import Decimal
import requests
import os
import random

# Binance istemcisi
client = Client(keyler.api_key, keyler.api_secret)

# Telegram bilgileri
TELEGRAM_TOKEN = keyler.telegram_token
CHAT_ID = keyler.telegram_chat_id

# Ayarlar
SELL_THRESHOLD = 55
BUY_THRESHOLD = 35
BUY_MIN = 6
BUY_MAX = 10
EXCEL_FILE = "işlem_raporu.xlsx"
ALIM_HAKKI_FILE = "alim_hakki.xlsx"
CHECK_INTERVAL = 20
SUMMARY_INTERVAL = 60  # terminal özet aralığı (saniye)

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
def write_to_excel(asset, quantity, price, total_value, action, remaining_value, alim_hakki):
    data = {
        "İşlem": [action],
        "Varlık": [asset],
        "Miktar": [quantity],
        "Fiyat (USDT)": [price],
        "Toplam Değer (USDT)": [total_value],
        "Kalan Bakiye (USDT)": [remaining_value],
        "Alım Hakkı": [alim_hakki],
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
        return df.to_dict(orient='records')
    return None

# Adım büyüklüğüne göre miktar ayarla
def adjust_quantity(qty, step_size):
    return float((Decimal(str(qty)) // Decimal(str(step_size))) * Decimal(str(step_size)))

# İşlem çiftinin limit bilgileri
def get_symbol_info(symbol):
    exchange_info = client.get_exchange_info()
    min_qty, step_size, min_notional = 0.0001, 0.0001, 5  # minNotional Binance ~5 USDT
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    min_qty = float(f.get('minQty', 0.0001))
                    step_size = float(f.get('stepSize', 0.0001))
                elif f['filterType'] == 'MIN_NOTIONAL':
                    min_notional = float(f.get('minNotional', 5))
            break
    return min_qty, step_size, min_notional

# USDT işlem çiftini bul
def find_usdt_pair(asset):
    if asset == "MEME":
        return None
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
        if a['asset'] == "MEME":
            continue

        free_balance = float(a['free'])
        borrowed = float(a['borrowed'])
        net_balance = free_balance - borrowed
        if net_balance <= 0:
            continue

        symbol = find_usdt_pair(a['asset'])
        if not symbol:
            continue

        try:
            price = float(client.get_symbol_ticker(symbol=symbol)['price'])
            value_usdt = net_balance * price
            if value_usdt < 10:
                continue

            coin_list.append({
                "asset": a['asset'],
                "symbol": symbol,
                "alim_hakki": 3,
                "satilan_sayisi": 0
            })
        except:
            continue

    print(f"{len(coin_list)} coin bulundu ve işleme alınabilir.")
    save_alim_hakki(coin_list)
    return coin_list

# Coin bakiyelerini güncelle
def update_coin_balances(coin_list):
    margin_account = client.get_margin_account()
    balances = {a['asset']: float(a['free']) for a in margin_account['userAssets']}
    updated_assets = []
    for c in coin_list:
        free = balances.get(c['asset'], 0)
        net_balance = free
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
    # USDT ekle
    usdt_free = balances.get("USDT", 0)
    updated_assets.append({"asset":"USDT","symbol":"USDT","net_balance":usdt_free,"price":1,"value_usdt":usdt_free})
    return updated_assets

# Satış işlemleri (fazlalık kadar)
def sell_assets(asset_details, coin_list):
    sold = False
    for asset in asset_details:
        if asset["asset"]=="USDT":
            continue
        if asset["value_usdt"] > SELL_THRESHOLD:
            excess_value = asset["value_usdt"] - SELL_THRESHOLD
            min_qty, step_size, min_notional = get_symbol_info(asset["symbol"])
            sell_quantity = adjust_quantity(excess_value / asset["price"], step_size)

            if sell_quantity * asset["price"] < min_notional:
                print(f"{asset['asset']} satışı minimum tutarı karşılamıyor: {sell_quantity*asset['price']:.2f} USDT")
                continue

            try:
                client.create_margin_order(
                    symbol=asset["symbol"],
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=sell_quantity,
                    isIsolated=False
                )
                for c in coin_list:
                    if c["asset"] == asset["asset"]:
                        c["satilan_sayisi"] += 1
                        c["alim_hakki"] = min(3 + c["satilan_sayisi"], c["alim_hakki"] + 1)
                        break
                remaining_value = asset["net_balance"] * asset["price"] - sell_quantity * asset["price"]
                write_to_excel(asset['asset'], sell_quantity, asset['price'], sell_quantity * asset["price"],
                               "SATIŞ", remaining_value, [c for c in coin_list if c["asset"]==asset["asset"]][0]["alim_hakki"])
                print(f"[SATIŞ] {asset['asset']} {sell_quantity:.6f} satıldı. Kalan bakiye: {remaining_value:.2f} USDT")
                send_telegram(f"[SATIŞ] {asset['asset']} {sell_quantity:.6f} satıldı. Kalan bakiye: {remaining_value:.2f} USDT")
                sold = True
            except Exception as e:
                print(f"{asset['asset']} satışı başarısız: {e}")
    save_alim_hakki(coin_list)
    return sold

# Alım işlemleri (6-10 USDT arası)
def buy_assets(asset_details, coin_list):
    bought = False
    usdt_balance = next((a["net_balance"] for a in asset_details if a["asset"]=="USDT"), 0)

    for asset in asset_details:
        if asset["asset"] == "USDT":
            continue

        coin_info = next((c for c in coin_list if c["asset"] == asset["asset"]), None)
        if not coin_info or coin_info["alim_hakki"] <= 0:
            continue

        if asset["value_usdt"] < BUY_THRESHOLD and usdt_balance > 0:
            buy_value = min(random.uniform(BUY_MIN, BUY_MAX), usdt_balance)
            step_size = get_symbol_info(asset["symbol"])[1]
            buy_quantity = max(adjust_quantity(buy_value / asset["price"], step_size), 0.000001)

            try:
                client.create_margin_order(
                    symbol=asset["symbol"],
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=buy_quantity,
                    isIsolated=False
                )
                coin_info["alim_hakki"] -= 1
                remaining_value = asset["value_usdt"] + buy_quantity * asset["price"]
                write_to_excel(asset['asset'], buy_quantity, asset['price'], buy_quantity * asset["price"],
                               "ALIM", remaining_value, coin_info["alim_hakki"])
                print(f"[ALIM] {asset['asset']} {buy_quantity:.6f} alındı ({buy_quantity * asset['price']:.2f} USDT). Alım hakkı: {coin_info['alim_hakki']}")
                send_telegram(f"[ALIM] {asset['asset']} {buy_quantity:.6f} alındı ({buy_quantity * asset['price']:.2f} USDT). Alım hakkı: {coin_info['alim_hakki']}")
                bought = True
                usdt_balance -= buy_quantity * asset["price"]
            except Exception as e:
                print(f"{asset['asset']} alımı başarısız: {e}")

    save_alim_hakki(coin_list)
    return bought

# Ana döngü
def main():
    sync_time()
    coin_list = initial_scan()
    last_summary = time.time()
    loop_count = 0

    while True:
        loop_count += 1
        try:
            asset_details = update_coin_balances(coin_list)
            usdt_balance = next((a["net_balance"] for a in asset_details if a["asset"]=="USDT"), 0)
            print(f"\n--- Döngü {loop_count} --- Kullanılabilir USDT: {usdt_balance:.2f} ---")

            sold = sell_assets(asset_details, coin_list)
            bought = buy_assets(asset_details, coin_list)

            if (sold or bought) and time.time() - last_summary > SUMMARY_INTERVAL:
                print(f"\n--- Özet ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")
                for asset in asset_details:
                    print(f"{asset['asset']}: Bakiye={asset['net_balance']:.6f}, Değer={asset['value_usdt']:.2f} USDT")
                last_summary = time.time()

        except Exception as e:
            print(f"Hata oluştu: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
