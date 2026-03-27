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
WATCHLIST = ['VCB', 'BID', 'CTG', 'TCB', 'MBB', 'ACB', 'HDB', 'VPB', 'STB', 'LPB', 'TPB', 'VIB', 'MSB', 'OCB', 'SHB', 'SSB', 'NAB', 'BAB', 'BVB', 'SGB', 'SSI', 'VND', 'VCI', 'HCM', 'FTS', 'MBS', 'BSI', 'CTS', 'VIX', 'SHS', 'ORS', 'AGR', 'TVS', 'BVS', 'VDS', 'SBS', 'PSI', 'IVS', 'TCI', 'WSS', 'VHM', 'VIC', 'VRE', 'PDR', 'DIG', 'DXG', 'NLG', 'KDH', 'CEO', 'TCH', 'NVL', 'HDG', 'KBC', 'GVR', 'BCM', 'IDC', 'SZC', 'VGC', 'PHR', 'ITA', 'SJS', 'SZL', 'TIP', 'LHG', 'D2D', 'NTC', 'NTL', 'QCG', 'AGG', 'KHG', 'HPG', 'HSG', 'NKG', 'VGS', 'TVN', 'SMC', 'TLH', 'VCG', 'HHV', 'LCG', 'C4G', 'FCN', 'HT1', 'BCC', 'BMP', 'CTD', 'HBC', 'PC1', 'TV2', 'REE', 'GAS', 'POW', 'PVS', 'PVD', 'PVB', 'PVC', 'PLX', 'OIL', 'BSR', 'DGC', 'DCM', 'DPM', 'CSV', 'LAS', 'BFC', 'DDV', 'GEG', 'NT2', 'HDG', 'TTA', 'FPT', 'MWG', 'MSN', 'PNJ', 'FRT', 'DGW', 'PET', 'CTR', 'VNM', 'SAB', 'VGI', 'FOX', 'CMG', 'ELC', 'VEA', 'MCH', 'MML', 'MSR', 'BHN', 'HAB', 'VJC', 'HVN', 'ACV', 'GMD', 'HAH', 'VOS', 'VSC', 'MVN', 'SCS', 'TMS', 'VHC', 'ANV', 'IDI', 'FMC', 'ACL', 'MPC', 'CMX', 'TNG', 'MSH', 'GIL', 'DBC', 'HAG', 'HNG', 'BAF', 'PAN', 'LTG', 'VIF', 'DPR', 'TRC', 'DRI']

# ==========================================
# 2. BỘ LỌC TIN TỨC (QUÉT BLACKLIST)
# ==========================================
def check_news_safety(symbol):
    try:
        news_df = stock_news(symbol)
        if news_df.empty: return "💎 Tin tức: Ổn định"
        
        blacklist = ['bị bắt', 'vi phạm', 'đình chỉ', 'thua lỗ', 'cắt margin', 'cảnh báo', 'hủy niêm yết', 'thanh tra', 'khởi tố']
        latest_titles = news_df['title'].head(3).tolist()
        for title in latest_titles:
            for word in blacklist:
                if word in title.lower():
                    return f"⚠️ CẢNH BÁO: {title[:40]}..."
        return "💎 Tin tức: Bình thường"
    except: return "🔍 Tin tức: Không có dữ liệu"

# ==========================================
# 3. LOGIC SMART-MCDX (NHẬY CẢ XANH LẪN ĐỎ)
# ==========================================
def analyze_ultimate(symbol):
    try:
        df = stock_historical_data(symbol, "2024-01-01", datetime.now().strftime('%Y-%m-%d'), "1D")
        if df.empty or len(df) < 50: return None

        # Tính toán Banker mô phỏng chuẩn (Nhạy hơn RSI cũ)
        low_20 = df['low'].rolling(20).min()
        high_20 = df['high'].rolling(20).max()
        df['banker'] = ((df['close'] - low_20) / (high_20 - low_20) * 100).rolling(3).mean()

        df['rsi'] = ta.rsi(df['close'], length=13)
        df['vol_avg'] = df['volume'].rolling(window=20).mean()
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        rel_vol = last['volume'] / last['vol_avg']

        # 1. Lọc cổ phiếu rác (Thanh khoản thấp)
        if last['volume'] * last['close'] < 1000000: return None

        # 2. Chiến thuật "Bắt Cá Hồi" (Xanh vẫn mua - Hồi từ đáy)
        is_catching_fish = (prev['rsi'] < 35) and (last['rsi'] > prev['rsi']) and (last['close'] > last['open'])

        # 3. Chiến thuật "Bùng Nổ" (Đã có dòng tiền đỏ xác nhận)
        high_10 = df['high'].shift(1).rolling(10).max().iloc[-1]
        is_explosion = (last['banker'] > 25) and (last['close'] > high_10)

        # QUYẾT ĐỊNH
        if rel_vol > 1.2: # Volume tăng 20% so với trung bình
            if is_catching_fish:
                return {"type": "🌀 BẮT CÁ HỒI (Hồi từ đáy)", "price": last['close'], "banker": round(last['banker'], 1), "vol": round(rel_vol, 2)}
            if is_explosion:
                return {"type": "🚀 BÙNG NỔ (Dòng tiền vào)", "price": last['close'], "banker": round(last['banker'], 1), "vol": round(rel_vol, 2)}
    except: return None
    return None

# ==========================================
# 4. VẬN HÀNH & GỬI TIN (CHỐNG LẶP)
# ==========================================
def main_worker():
    start_time = datetime.now().strftime('%H:%M:%S')
    status_msg = bot.send_message(CHAT_ID, f"🔄 **BẮT ĐẦU QUÉT THỊ TRƯỜNG**\n🕒 Lúc: {start_time}")
    
    found_count = 0
    total = len(WATCHLIST)
    
    for index, symbol in enumerate(WATCHLIST):
        if (index + 1) % 20 == 0 or (index + 1) == total:
            try:
                percent = round((index + 1) / total * 100)
                bot.edit_message_text(f"📊 Đang quét: {index+1}/{total} mã ({percent}%)", CHAT_ID, status_msg.message_id)
            except: pass

        res = analyze_ultimate(symbol)
        if res:
            found_count += 1
            news_txt = check_news_safety(symbol)
            msg = (f"💎 **MÃ TIỀM NĂNG: {symbol}**\n"
                   f"━━━━━━━━━━━━━━\n"
                   f"🎯 Tín hiệu: `{res['type']}`\n"
                   f"💵 Giá mua: **{res['price']}**\n"
                   f"🐳 Banker (Đỏ): `{res['banker']}%`\n"
                   f"📊 Vol đột biến: x{res['vol']}\n"
                   f"📰 {news_txt}\n"
                   f"🛡️ Hỗ trợ (Cắt lỗ): {round(res['price'] * 0.93, 2)}")
            bot.send_message(CHAT_ID, msg)
        time.sleep(0.6)

    bot.send_message(CHAT_ID, f"🏁 **HOÀN THÀNH!** Tìm thấy {found_count} mã tiềm năng.")

if __name__ == "__main__":
    main_worker()
