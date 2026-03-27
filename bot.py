import os
import time
import pytz
import pandas as pd
import pandas_ta as ta
import telebot
from vnstock import *
import datetime
from datetime import datetime, timedelta
import concurrent.futures

# ĐỊNH NGHĨA BIẾN vn_tz TRƯỚC KHI SỬ DỤNG
vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
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
# Headers giả lập trình duyệt để tránh FireAnt block
FIREANT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://fireant.vn/",
    "Origin": "https://fireant.vn"
}

try:
    bot.send_message(CHAT_ID, "🚀 Bot Scan Cổ Phiếu (FireAnt Data) đã bắt đầu chạy...")
except Exception as e:
    print(f"Lỗi gửi tin nhắn Telegram: {e}")
def get_150_watchlist():
    """Tự động lấy 150 mã mạnh nhất thị trường (VN100 + HNX30 + Penny thanh khoản)"""
    try:
        vn100 = vnindex_constituent_compositions(index='VN100')['ticker'].tolist()
        hnx30 = hnx30_constituent_compositions()['ticker'].tolist()
        # Thêm các mã bạn quan tâm đặc biệt
        fav = ['PC1', 'GEX', 'PDR', 'POW', 'SSI', 'VND', 'DIG', 'NLG', 'MVN', 'ACV']
        full_list = list(set(vn100 + hnx30 + fav))
        return full_list[:150]
    except:
        # Nếu lỗi API, dùng list cứng dự phòng
        return ['SSI', 'VND', 'TCB', 'HDB', 'HPG', 'HSG', 'NKG', 'PDR', 'DIG', 'DXG', 'VHM', 'VIC', 'MSN', 'FPT', 'MWG']

# ==========================================
# 2. BỘ NÃO PHÂN TÍCH (LOGIC "THẦN THÁNH")
# ==========================================
def analyze_god_mode(symbol):
    try:
        # Lấy dữ liệu 100 phiên gần nhất
        df = stock_historical_data(symbol, "2024-01-01", datetime.now().strftime('%Y-%m-%d'), "1D")
        if len(df) < 50: return None

        # --- CHỈ BÁO KỸ THUẬT ---
        # 1. Giảm độ trễ cực thấp với Hull Moving Average
        df['hma21'] = ta.hma(df['close'], length=21)
        df['ema50'] = ta.ema(df['close'], length=50)
        
        # 2. Chỉ báo MCDX (Dòng tiền Cá mập - Cột đỏ)
        df['rsi'] = ta.rsi(df['close'], length=13)
        df['banker'] = ((df['rsi'] - 30) * 2.5).clip(lower=0, upper=100)

        # 3. Lọc nhiễu ADX (Chỉ đánh khi có trend rõ ràng)
        adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
        df['adx'] = adx_df['ADX_14']
        
        # 4. Đo lường Volume
        df['vol_avg'] = df['volume'].rolling(window=20).mean()
        
        # --- LOGIC QUYẾT ĐỊNH ---
        last = df.iloc[-1]
        high_10 = df['high'].shift(1).rolling(window=10).max().iloc[-1]
        
        is_uptrend = (last['close'] > last['hma21']) and (last['hma21'] > last['ema50'])
        
        # KỊCH BẢN 1: MUA PULLBACK (Chạm hỗ trợ nảy lên - Giống MSN)
        if is_uptrend and (last['low'] <= last['hma21']) and (last['close'] > last['hma21']) and (last['banker'] > 35):
            return {"symbol": symbol, "type": "🔥 ĐIỂM MUA HỖ TRỢ (PULLBACK)", "price": last['close'], "banker": round(last['banker'], 1)}

        # KỊCH BẢN 2: MUA BÙNG NỔ (Nổ Vol, Cá mập đẩy - Giống MVN)
        if (last['close'] > high_10) and (last['banker'] > 55) and (last['volume'] > last['vol_avg'] * 1.3) and (last['adx'] > 25):
            return {"symbol": symbol, "type": "🚀 ĐIỂM MUA BÙNG NỔ (BREAKOUT)", "price": last['close'], "banker": round(last['banker'], 1)}

    except Exception as e:
        print(f"Lỗi {symbol}: {e}")
    return None

# ==========================================
# 3. ĐỊNH DẠNG TIN NHẮN & VẬN HÀNH
# ==========================================
def send_telegram(data):
    msg = f"🔔 **TÍN HIỆU CHIẾN THUẬT: {data['symbol']}**\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"📍 Trạng thái: **{data['type']}**\n"
    msg += f"💰 Giá vào: **{data['price']}**\n"
    msg += f"🐳 Cá mập (MCDX): `{data['banker']}%` đỏ\n"
    msg += f"🛡️ Cắt lỗ: Thủng đường HMA21\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"⚡ *Hành động: Múc quyết liệt, không kỳ kèo giá!*"
    bot.send_message(CHAT_ID, msg, parse_mode='Markdown')

def run_bot():
    print(f"🌟 Bắt đầu truy quét 150 mã mạnh nhất thị trường...")
    watchlist = get_150_watchlist()
    for symbol in watchlist:
        result = analyze_god_mode(symbol)
        if result:
            send_telegram(result)
            print(f"✅ Đã bắn tín hiệu cho {symbol}")
        time.sleep(0.5) # Tránh bị spam API

if __name__ == "__main__":
    run_bot()
        
