import os
import time
import pandas_ta as ta
import pandas as pd
import telebot
from vnstock import *

# 1. Lấy cấu hình từ GitHub Secrets
TOKEN = os.getenv('8625301702:AAHLOJgz_fIkfA6WpU7Sr60KjRIzc7nmHR4')
CHAT_ID = os.getenv('1736294695')

# 2. Ép kiểu CHAT_ID sang số nguyên để tránh lỗi "chat not found"
try:
    CHAT_ID = int('1736294695')
except:
    print("Loi: CHAT_ID khong hop le!")

bot = telebot.TeleBot('8625301702:AAHLOJgz_fIkfA6WpU7Sr60KjRIzc7nmHR4')

# 3. Gửi tin nhắn kiểm tra đầu tiên
try:
    bot.send_message(CHAT_ID, "🚀 Bot Scan Cổ Phiếu đã bắt đầu chạy...")
except Exception as e:
    print(f"Loi gui tin nhan Telegram: {e}")
# 2. Hàm chấm điểm Wyckoff
def calculate_signal_score(ticker):
    try:
        # Lấy dữ liệu
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        df = stock_historical_data(ticker, start_date, end_date, "1D")
        
        if df.empty or len(df) < 50: 
            return 0, ""

        # --- TÍNH TOÁN DỮ LIỆU CƠ BẢN (PHẢI NẰM Ở ĐÂY) ---
        avg_vol = df['volume'].tail(20).mean()
        if avg_vol < 500000: # Bộ lọc thanh khoản
            return 0, ""

        score = 0
        details = []
        
        df['MA20'] = ta.sma(df['close'], length=20)
        df['MA50'] = ta.sma(df['close'], length=50)
        df['RSI'] = ta.rsi(df['close'], length=14)
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # --- LOGIC CHẤM ĐIỂM ---
        body = abs(curr['close'] - curr['open'])
        lower_shadow = min(curr['close'], curr['open']) - curr['low']
        is_pinbar = lower_shadow > (body * 1.5)
        
        if curr['volume'] > avg_vol * 1.8 and curr['close'] > prev['close']:
            score += 40
            details.append(f"🔥 SOS: Dòng tiền mạnh ({round(curr['volume']/avg_vol, 1)}x)")
        elif is_pinbar and curr['volume'] > avg_vol:
            score += 30
            details.append("⚓ Spring: Nến rút chân hấp thụ")
        elif curr['volume'] > avg_vol:
            score += 15
            details.append("📈 Vol tích cực")

        if curr['close'] > curr['MA20'] > curr['MA50']:
            score += 30
            details.append("✅ Xu hướng: Uptrend")
        
        if 45 < curr['RSI'] < 65:
            score += 20
            details.append(f"💎 RSI: {round(curr['RSI'], 1)}")
            
        change = (curr['close'] - prev['close']) / prev['close'] * 100
        if change > 2:
            score += 10
            details.append(f"🚀 Giá tăng: {round(change, 1)}%")

        return score, "\n".join(details)

    except Exception as e:
        print(f"Lỗi tại mã {ticker}: {e}")
        return 0, ""

# 3. Quét danh mục (VN100 & Midcap tuyển chọn)
def main_scanner():
    watch_list = [
        "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", 
        "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB", 
        "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
        "VND", "VCI", "HCM", "SHS", "MBS", "FTS", "BSI", "CTS", "AGR", "VIX", "ORS",
        "DIG", "DXG", "PDR", "NVL", "NLG", "KDH", "KBC", "IDC", "SZC", "VGC", "CEO", "TCH", "HDG", "HDC",
        "HSG", "NKG", "VGS", "VCG", "LCG", "HHV", "CTD", "PC1", "DGC", "DCM", "DPM", "DGW", "FRT", "PNJ", 
        "PVS", "PVD", "PVT", "BSR", "GMD", "HAH", "DBC", "HAG", "VHC", "ANV", "TNG"
    ]
    
    scored_list = []
    print("Đang bắt đầu quét...")
    
    for ticker in watch_list:
        score, details = calculate_signal_score(ticker)
        if score >= 70: 
            scored_list.append({'ticker': ticker, 'score': score, 'details': details})
        time.sleep(0.6)

    scored_list.sort(key=lambda x: x['score'], reverse=True)

    if scored_list:
        message = "🏆 **XẾP HẠNG WYCKOFF T+10** 🏆\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for item in scored_list:
            rank = "🌟 SIÊU CỔ" if item['score'] >= 90 else "🎯 TIỀM NĂNG"
            message += f"{rank}: **{item['ticker']}**\n📊 Điểm: `{item['score']}/100`\n{item['details']}\n━━━━━━━━━━━━━━━━━━━━\n"
        bot.send_message(CHAT_ID, message, parse_mode="Markdown")

if __name__ == "__main__":
    main_scanner()
        
