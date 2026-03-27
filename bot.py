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
# 2. BỘ LỌC TIN TỨC & AN TOÀN
# ==========================================
def check_news_safety(symbol):
    try:
        news_df = stock.stock_news(symbol=symbol)
        if news_df.empty: return "💎 Tin tức: Ổn định", 1
        blacklist = ['bị bắt', 'vi phạm', 'đình chỉ', 'thua lỗ', 'cắt margin', 'cảnh báo', 'hủy niêm yết', 'thanh tra', 'khởi tố']
        latest_titles = news_df['title'].head(3).tolist()
        for title in latest_titles:
            for word in blacklist:
                if word in title.lower(): return f"⚠️ CẢNH BÁO: {title[:40]}...", -3
        return "💎 Tin tức: Bình thường", 1
    except: return "🔍 Tin tức: Không có dữ liệu", 0

# ==========================================
# 3. LÕI CHẤM ĐIỂM VÀ PHÂN TÍCH (SMART MONEY)
# ==========================================
def analyze_ultimate(symbol):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
        df = stock.stock_historical_data(symbol=symbol, source='VCI', start_date=start_date, end_date=today)
        
        if df.empty or len(df) < 40: return None

        # Chỉ báo kỹ thuật
        df['ma20'] = ta.sma(df['close'], length=20)
        df['vma20'] = ta.sma(df['volume'], length=20)
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
        
        # MCDX Hybrid (Dòng tiền đỏ)
        low_20 = df['low'].rolling(20).min()
        high_20 = df['high'].rolling(20).max()
        df['banker_raw'] = ((df['close'] - low_20) / (high_20 - low_20) * 100).rolling(3).mean()
        df['banker_final'] = (df['banker_raw'] * 0.5) + (df['mfi'] * 0.5)
        
        # MACD Slope (Gia tốc)
        macd = df.ta.macd()
        df['hist'] = macd['MACDh_12_26_9']
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        p_prev = df.iloc[-3]
        
        rel_vol = last['volume'] / last['vma20']
        dist_ma20 = (last['close'] - last['ma20']) / last['ma20']
        
        # --- HỆ THỐNG CHẤM ĐIỂM (Scoring) ---
        score = 0
        details = []
        
        # 1. Tiền to (MCDX) - Max 3đ
        if last['banker_final'] > 25: 
            score += 2; details.append("Tiền to vào")
            if last['banker_final'] > prev['banker_final']: score += 1; details.append("Tiền nạp thêm")
        
        # 2. Động lượng (MACD Slope) - Max 2đ
        if last['hist'] > prev['hist'] > p_prev['hist']: score += 2; details.append("Đà hồi phục mạnh")
        
        # 3. Nỗ lực Volume - Max 2đ
        if rel_vol >= 1.5: score += 2; details.append("Vol nổ")
        elif rel_vol >= 1.1: score += 1; details.append("Vol mồi")
        
        # 4. Vị thế MA20 - Max 2đ
        if abs(dist_ma20) <= 0.02: score += 2; details.append("Sát nền")
        elif dist_ma20 > 0.08: score -= 2; details.append("Quá xa nền")

        # 5. Tin tức & Thanh khoản
        news_txt, news_score = check_news_safety(symbol)
        score += news_score
        if last['volume'] * last['close'] < 1000000000: score -= 2 # Thanh khoản < 1 tỷ

        # --- PHÂN LOẠI CHIẾN THUẬT ---
        signal_type = "Theo dõi"
        
        # A. SMART MONEY MỒI (Gom hàng)
        if (10 < last['banker_final'] < 30) and (last['hist'] > prev['hist']) and (rel_vol < 1.0):
            signal_type = "🔍 ĐANG GOM HÀNG (Mồi dần)"
        # B. BẮT CÁ HỒI
        elif (prev['rsi'] < 35) and (last['rsi'] > prev['rsi']):
            signal_type = "🌀 BẮT CÁ HỒI (Hồi đáy)"
        # C. BÙNG NỔ
        elif score >= 8 and rel_vol > 1.3:
            signal_type = "🚀 BÙNG NỔ (Dòng tiền vào)"
        
        return {
            "symbol": symbol, "score": score, "type": signal_type,
            "price": last['close'], "banker": round(last['banker_final'], 1),
            "vol": round(rel_vol, 2), "news": news_txt, "details": " | ".join(details)
        }
    except: return None

# ==========================================
# 4. VẬN HÀNH MAIN WORKER
# ==========================================
def main_worker():
    start_time = datetime.now().strftime('%H:%M:%S')
    status_msg = bot.send_message(CHAT_ID, f"🔄 **BOSS BẮT ĐẦU QUÉT {len(WATCHLIST)} MÃ**\n🕒 Lúc: {start_time}")
    
    found_count = 0
    total = len(WATCHLIST)
    
    for index, symbol in enumerate(WATCHLIST):
        # Cập nhật tiến độ mỗi 30 mã
        if (index + 1) % 30 == 0:
            bot.edit_message_text(f"📊 Boss đang quét: {index+1}/{total} mã...", CHAT_ID, status_msg.message_id)

        res = analyze_ultimate(symbol)
        
        # CHỈ BÁO NẾU ĐIỂM >= 7 HOẶC ĐANG GOM HÀNG
        if res and (res['score'] >= 7 or "GOM HÀNG" in res['type']):
            found_count += 1
            color = "🟢" if res['score'] >= 8 else "🟡"
            msg = (f"{color} **MÃ TIỀM NĂNG: {res['symbol']}**\n"
                   f"━━━━━━━━━━━━━━\n"
                   f"🏆 Điểm: **{res['score']}/10**\n"
                   f"🎯 Trạng thái: `{res['type']}`\n"
                   f"💵 Giá: **{res['price']}**\n"
                   f"🐳 Banker: `{res['banker']}%` | Vol: `x{res['vol']}`\n"
                   f"📝 Log: _{res['details']}_\n"
                   f"📰 {res['news']}\n"
                   f"🛡️ Hỗ trợ: {round(res['price'] * 0.93, 2)}")
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        
        time.sleep(0.6) # Tránh bị chặn API

    bot.send_message(CHAT_ID, f"🏁 **HOÀN THÀNH!** Tìm thấy {found_count} cơ hội.")

if __name__ == "__main__":
    main_worker()        
