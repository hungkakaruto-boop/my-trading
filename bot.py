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
        print(f"Lỗi {symbol}: {e}")
# --- DANH SÁCH 150 MÃ CHI TIẾT ---
WATCHLIST = [
    'VCB', 'BID', 'CTG', 'TCB', 'MBB', 'ACB', 'HDB', 'VPB', 'STB', 'LPB', 'TPB', 'VIB', 'MSB', 'OCB', 'SHB', 'SSB', 'NAB', 'BAB', 'BVB', 'SGB',
    'SSI', 'VND', 'VCI', 'HCM', 'FTS', 'MBS', 'BSI', 'CTS', 'VIX', 'SHS', 'ORS', 'AGR', 'TVS', 'BVS', 'VDS', 'SBS', 'PSI', 'IVS', 'TCI', 'WSS',
    'VHM', 'VIC', 'VRE', 'PDR', 'DIG', 'DXG', 'NLG', 'KDH', 'CEO', 'TCH', 'NVL', 'HDG', 'KBC', 'GVR', 'BCM', 'IDC', 'SZC', 'VGC', 'PHR', 'ITA', 
    'SJS', 'SZL', 'TIP', 'LHG', 'D2D', 'NTC', 'NTL', 'QCG', 'AGG', 'KHG', 'HPG', 'HSG', 'NKG', 'VGS', 'TVN', 'SMC', 'TLH', 'VCG', 'HHV', 'LCG', 
    'C4G', 'FCN', 'HT1', 'BCC', 'BMP', 'CTD', 'HBC', 'PC1', 'TV2', 'REE', 'GAS', 'POW', 'PVS', 'PVD', 'PVB', 'PVC', 'PLX', 'OIL', 'BSR', 'DGC', 
    'DCM', 'DPM', 'CSV', 'LAS', 'BFC', 'DDV', 'GEG', 'NT2', 'HDG', 'TTA', 'FPT', 'MWG', 'MSN', 'PNJ', 'FRT', 'DGW', 'PET', 'CTR', 'VNM', 'SAB', 
    'VGI', 'FOX', 'CMG', 'ELC', 'VEA', 'MCH', 'MML', 'MSR', 'BHN', 'HAB', 'VJC', 'HVN', 'ACV', 'GMD', 'HAH', 'VOS', 'VSC', 'MVN', 'SCS', 'TMS', 
    'VHC', 'ANV', 'IDI', 'FMC', 'ACL', 'MPC', 'CMX', 'TNG', 'MSH', 'GIL', 'DBC', 'HAG', 'HNG', 'BAF', 'PAN', 'LTG', 'VIF', 'DPR', 'TRC', 'DRI'
]

# ==========================================
# 2. BỘ NÃO PHÂN TÍCH (ZERO-ERROR LOGIC)
# ==========================================
def analyze_ultimate(symbol):
    try:
        # Lấy dữ liệu 150 phiên để tính toán chỉ báo chuẩn
        df = stock_historical_data(symbol, "2024-01-01", datetime.now().strftime('%Y-%m-%d'), "1D")
        if df.empty or len(df) < 100: return None

        # --- CHỈ BÁO KỸ THUẬT ---
        df['hma21'] = ta.hma(df['close'], length=21)
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        # MCDX (Cá mập)
        df['rsi'] = ta.rsi(df['close'], length=13)
        df['banker'] = ((df['rsi'] - 30) * 2.5).clip(lower=0, upper=100)
        
        # Độ nén (BB Width) & ADX
        bb = ta.bbands(df['close'], length=20, std=2)
        df['bb_width'] = (bb['BBU_20_2.0'] - bb['BBL_20_2.0']) / bb['BBM_20_2.0']
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        df['adx'] = adx['ADX_14']

        # --- LOGIC TRIGGER ---
        last = df.iloc[-1]
        high_10 = df['high'].shift(1).rolling(window=10).max().iloc[-1]
        vol_avg = df['volume'].rolling(window=20).mean().iloc[-1]
        
        # Điều kiện Trend Kênh Trên (Quan trọng nhất)
        is_uptrend = (last['close'] > last['ema50']) and (last['ema50'] > last['ema200'])

        # TH1: PULLBACK (Chạm viền đỏ nảy lên)
        if is_uptrend and (last['low'] <= last['hma21']) and (last['close'] > last['hma21']) \
           and (last['close'] > last['open']) and (last['banker'] > 35):
            return {"type": "🔥 MUA PULLBACK (HỖ TRỢ)", "price": last['close'], "banker": round(last['banker'], 1)}

        # TH2: BREAKOUT (Nổ giá vượt nền)
        if is_uptrend and (last['close'] > high_10) and (last['bb_width'] < 0.15) \
           and (last['volume'] > vol_avg * 1.5) and (last['banker'] > 50):
            return {"type": "🚀 MUA BÙNG NỔ (BREAKOUT)", "price": last['close'], "banker": round(last['banker'], 1)}

    except: return None
    return None

# ==========================================
# 3. HÀM VẬN HÀNH & THÔNG BÁO TIẾN TRÌNH
# ==========================================
def main_worker():
    start_time = datetime.now()
    bot.send_message(CHAT_ID, f"🔄 **BẮT ĐẦU QUÉT THỊ TRƯỜNG**\n🕒 Lúc: {start_time.strftime('%H:%M:%S')}\n📊 Danh sách: 150 mã tinh hoa.")
    
    found_count = 0
    # Gửi một tin nhắn tiến trình để cập nhật liên tục (Tránh spam nhiều tin)
    progress_msg = bot.send_message(CHAT_ID, "⏳ Đang xử lý: 0/150 mã...")

    for index, symbol in enumerate(WATCHLIST):
        # Cập nhật trạng thái mỗi 25 mã để người dùng yên tâm
        if (index + 1) % 25 == 0:
            bot.edit_message_text(f"⏳ Đang xử lý: {index + 1}/150 mã...", CHAT_ID, progress_msg.message_id)

        result = analyze_ultimate(symbol)
        if result:
            found_count += 1
            msg = f"💎 **TÍN HIỆU: {symbol}**\n"
            msg += f"━━━━━━━━━━━━━━\n"
            msg += f"🏅 Chiến thuật: `{result['type']}`\n"
            msg += f"💵 Giá mua: **{result['price']}**\n"
            msg += f"🐳 Cá mập: `{result['banker']}%` đỏ\n"
            msg += f"🛡️ Cắt lỗ: Thủng HMA21\n"
            msg += f"━━━━━━━━━━━━━━\n"
            msg += f"✅ *Đã xác nhận hội tụ đủ yếu tố!*"
            bot.send_message(CHAT_ID, msg, parse_mode='Markdown')
        
        time.sleep(0.6) # Tránh bị sàn chặn

    end_time = datetime.now()
    duration = (end_time - start_time).seconds
    bot.send_message(CHAT_ID, f"🏁 **HOÀN THÀNH QUÉT MÃ**\n⏱️ Thời gian: {duration} giây.\n🔍 Tìm thấy: {found_count} cơ hội.\n☕ *Chúc bạn giao dịch thành công!*")

if __name__ == "__main__":
    main_worker()
