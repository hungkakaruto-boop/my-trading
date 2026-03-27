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
# --- 1. HÀM CHẤM ĐIỂM CHI TIẾT (Logic lõi) ---
def calculate_score(row, prev_row, rel_vol, dist_ma20, news_safety):
    score = 0
    details = []

    # A. Dòng tiền Banker (MCDX) - Max 3đ
    if row['banker_final'] > 25:
        score += 2
        details.append("🐳 Tiền to vào (+2)")
        if row['banker_final'] > prev_row['banker_final']:
            score += 1
            details.append("📈 Gia tốc tiền tăng (+1)")

    # B. Động lượng (MACD/RSI) - Max 2đ
    if row['hist'] > prev_row['hist']: # Đang hướng lên
        score += 1
        details.append("🚀 Động lượng hồi phục (+1)")
    if row['rsi'] > 50:
        score += 1
        details.append("💪 Phe mua chiếm ưu thế (+1)")

    # C. Nỗ lực Khối lượng (Volume) - Max 2đ
    if rel_vol >= 1.5:
        score += 2
        details.append("📊 Vol nổ mạnh (+2)")
    elif rel_vol >= 1.2:
        score += 1
        details.append("📊 Vol mồi (+1)")

    # D. Vị thế nền giá (MA20) - Max 2đ
    if abs(dist_ma20) <= 0.02: # Sát nền
        score += 2
        details.append("🏠 Ngay nền an toàn (+2)")
    elif dist_ma20 <= 0.05: # Hơi xa nền
        score += 1
        details.append("🛤️ Chớm bay khỏi nền (+1)")
    elif dist_ma20 > 0.08: # Quá xa (Đu đỉnh)
        score -= 2
        details.append("⚠️ Quá xa nền (-2)")

    # E. Khiên bảo vệ (Tin tức) - Max 1đ
    if "Bình thường" in news_safety:
        score += 1
        details.append("🛡️ Tin sạch (+1)")
    elif "CẢNH BÁO" in news_safety:
        score -= 3
        details.append("❌ Tin xấu nặng (-3)")

    return score, " | ".join(details)

# --- 2. HÀM PHÂN TÍCH VÀ GỬI TIN ---
def boss_scoring_scanner(symbol):
    try:
        # Lấy dữ liệu
        today = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
        df = stock.stock_historical_data(symbol=symbol, source='VCI', start_date=start_date, end_date=today)
        
        if df.empty or len(df) < 30: return

        # Chỉ báo
        df['ma20'] = ta.sma(df['close'], length=20)
        df['vma20'] = ta.sma(df['volume'], length=20)
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
        
        # Banker Hybrid
        low_20 = df['low'].rolling(20).min()
        high_20 = df['high'].rolling(20).max()
        df['banker_raw'] = ((df['close'] - low_20) / (high_20 - low_20) * 100).rolling(3).mean()
        df['banker_final'] = (df['banker_raw'] * 0.5) + (df['mfi'] * 0.5)
        
        # MACD
        macd = df.ta.macd()
        df['hist'] = macd['MACDh_12_26_9']
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        rel_vol = last['volume'] / last['vma20']
        dist_ma20 = (last['close'] - last['ma20']) / last['ma20']

        # Check tin tức trước khi chấm điểm
        news_status = "💎 Tin tức: Bình thường" # Giả sử hàm check_news_safety đã có ở trên
        
        # CHẤM ĐIỂM
        total_score, score_details = calculate_score(last, prev, rel_vol, dist_ma20, news_status)

        # LỌC: CHỈ GỬI TIN NẾU >= 7 ĐIỂM
        if total_score >= 7:
            status_icon = "🔥 CỰC THƠM" if total_score >= 9 else "✅ MUA ĐƯỢC"
            msg = (f"{status_icon} | **{symbol}**\n"
                   f"━━━━━━━━━━━━━━\n"
                   f"🏆 Tổng điểm: **{total_score}/10**\n"
                   f"💵 Giá hiện tại: **{last['close']}**\n"
                   f"📝 Chi tiết: _{score_details}_\n"
                   f"🛡️ Cắt lỗ: {round(last['close']*0.93, 2)}")
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

    except Exception as e:
        print(f"Lỗi {symbol}: {e}")

# (Hàm main_worker quét 150 mã giữ nguyên như bản trước)
WATCHLIST = ['VCB', 'BID', 'CTG', 'TCB', 'MBB', 'ACB', 'HDB', 'VPB', 'STB', 'LPB', 'TPB', 'VIB', 'MSB', 'OCB', 'SHB', 'SSB', 'NAB', 'BAB', 'BVB', 'SGB', 'SSI', 'VND', 'VCI', 'HCM', 'FTS', 'MBS', 'BSI', 'CTS', 'VIX', 'SHS', 'ORS', 'AGR', 'TVS', 'BVS', 'VDS', 'SBS', 'PSI', 'IVS', 'TCI', 'WSS', 'VHM', 'VIC', 'VRE', 'PDR', 'DIG', 'DXG', 'NLG', 'KDH', 'CEO', 'TCH', 'NVL', 'HDG', 'KBC', 'GVR', 'BCM', 'IDC', 'SZC', 'VGC', 'PHR', 'ITA', 'SJS', 'SZL', 'TIP', 'LHG', 'D2D', 'NTC', 'NTL', 'QCG', 'AGG', 'KHG', 'HPG', 'HSG', 'NKG', 'VGS', 'TVN', 'SMC', 'TLH', 'VCG', 'HHV', 'LCG', 'C4G', 'FCN', 'HT1', 'BCC', 'BMP', 'CTD', 'HBC', 'PC1', 'TV2', 'REE', 'GAS', 'POW', 'PVS', 'PVD', 'PVB', 'PVC', 'PLX', 'OIL', 'BSR', 'DGC', 'DCM', 'DPM', 'CSV', 'LAS', 'BFC', 'DDV', 'GEG', 'NT2', 'HDG', 'TTA', 'FPT', 'MWG', 'MSN', 'PNJ', 'FRT', 'DGW', 'PET', 'CTR', 'VNM', 'SAB', 'VGI', 'FOX', 'CMG', 'ELC', 'VEA', 'MCH', 'MML', 'MSR', 'BHN', 'HAB', 'VJC', 'HVN', 'ACV', 'GMD', 'HAH', 'VOS', 'VSC', 'MVN', 'SCS', 'TMS', 'VHC', 'ANV', 'IDI', 'FMC', 'ACL', 'MPC', 'CMX', 'TNG', 'MSH', 'GIL', 'DBC', 'HAG', 'HNG', 'BAF', 'PAN', 'LTG', 'VIF', 'DPR', 'TRC', 'DRI']

# ==========================================
# 2. BỘ LỌC TIN TỨC (News Safety)
# ==========================================
def check_news_safety(symbol):
    try:
        # Giả sử hàm lấy tin tức từ vnstock
        news_df = stock.stock_news(symbol=symbol)
        if news_df.empty: return "💎 Tin tức: Ổn định"
        
        blacklist = ['bị bắt', 'vi phạm', 'đình chỉ', 'thua lỗ', 'cắt margin', 'cảnh báo', 'hủy niêm yết', 'thanh tra', 'khởi tố', 'nợ thuế']
        latest_titles = news_df['title'].head(3).tolist()
        for title in latest_titles:
            for word in blacklist:
                if word in title.lower():
                    return f"⚠️ CẢNH BÁO: {title[:45]}..."
        return "💎 Tin tức: Bình thường"
    except: return "🔍 Tin tức: Không có dữ liệu"

# ==========================================
# 3. LÕI PHÂN TÍCH ULTIMATE (KẾT HỢP CŨ & MỚI)
# ==========================================
def analyze_ultimate_boss(symbol):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
        df = stock.stock_historical_data(symbol=symbol, source='VCI', start_date=start_date, end_date=today)
        
        if df.empty or len(df) < 35: return None

        # --- A. Chỉ báo cơ bản ---
        df['ma20'] = ta.sma(df['close'], length=20)
        df['vma20'] = ta.sma(df['volume'], length=20)
        df['rsi'] = ta.rsi(df['close'], length=13)
        df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
        
        # --- B. Banker Hybrid (Công thức cải tiến của bạn + tôi) ---
        low_20 = df['low'].rolling(20).min()
        high_20 = df['high'].rolling(20).max()
        df['banker_raw'] = ((df['close'] - low_20) / (high_20 - low_20) * 100).rolling(3).mean()
        # Mix với MFI để xác nhận tiền thật
        df['banker_final'] = (df['banker_raw'] * 0.5) + (df['mfi'] * 0.5)
        
        # --- C. MACD Gia tốc ---
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        df['hist'] = macd['MACDh_12_26_9']
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        rel_vol = last['volume'] / last['vma20']
        dist_ma20 = (last['close'] - last['ma20']) / last['ma20']

        # --- D. BỘ LỌC CHIẾN THUẬT ---
        
        # 1. Thanh khoản tối thiểu (> 1 tỷ VNĐ)
        if last['volume'] * last['close'] < 1000000000: return None

        # 2. Chiến thuật 1: BẮT CÁ HỒI (Hồi từ đáy RSI)
        is_catching_fish = (prev['rsi'] < 35) and (last['rsi'] > prev['rsi']) and (last['close'] > last['open']) and (rel_vol > 1.1)

        # 3. Chiến thuật 2: BÙNG NỔ (Xác nhận nổ)
        high_10 = df['high'].shift(1).rolling(10).max().iloc[-1]
        is_explosion = (last['banker_final'] > 30) and (last['close'] > high_10) and (rel_vol > 1.3)

        # 4. Chiến thuật 3: SĂN SỚM (MACD + MCDX Slope)
        is_early = (last['hist'] < 0) and (last['hist'] > prev['hist']) and (df['hist'].iloc[-3] < prev['hist']) and (dist_ma20 < 0.03)

        # PHÂN LOẠI TÍN HIỆU
        if is_catching_fish:
            return {"type": "🌀 BẮT CÁ HỒI (Hồi đáy)", "price": last['close'], "banker": round(last['banker_final'], 1), "vol": round(rel_vol, 2), "dist": round(dist_ma20*100, 2)}
        if is_explosion:
            return {"type": "🚀 BÙNG NỔ (Breakout)", "price": last['close'], "banker": round(last['banker_final'], 1), "vol": round(rel_vol, 2), "dist": round(dist_ma20*100, 2)}
        if is_early:
            return {"type": "🟢 SĂN SỚM (Tiền mồi)", "price": last['close'], "banker": round(last['banker_final'], 1), "vol": round(rel_vol, 2), "dist": round(dist_ma20*100, 2)}
            
    except Exception as e: return None
    return None

# ==========================================
# 4. VẬN HÀNH CHÍNH
# ==========================================
def main_worker():
    start_time = datetime.now().strftime('%H:%M:%S')
    # Thông báo bắt đầu quét
    status_msg = bot.send_message(CHAT_ID, f"🔄 **BOSS ĐANG QUÉT {len(WATCHLIST)} MÃ**\n🕒 Lúc: {start_time}")
    
    found_count = 0
    total = len(WATCHLIST)
    
    for index, symbol in enumerate(WATCHLIST):
        # Cập nhật tiến độ mỗi 25 mã
        if (index + 1) % 25 == 0:
            percent = round((index + 1) / total * 100)
            try: bot.edit_message_text(f"📊 Tiến độ Boss: {index+1}/{total} mã ({percent}%)", CHAT_ID, status_msg.message_id)
            except: pass

        res = analyze_ultimate_boss(symbol)
        if res:
            found_count += 1
            news_txt = check_news_safety(symbol)
            msg = (f"💎 **MÃ TIỀM NĂNG: {symbol}**\n"
                   f"━━━━━━━━━━━━━━\n"
                   f"🎯 Tín hiệu: `{res['type']}`\n"
                   f"💵 Giá: **{res['price']}**\n"
                   f"🐳 Banker (Hybrid): `{res['banker']}%`\n"
                   f"📊 Vol đột biến: x{res['vol']}\n"
                   f"📏 Cách MA20: {res['dist']}% \n"
                   f"📰 {news_txt}\n"
                   f"🛡️ Cắt lỗ (Gợi ý): {round(res['price'] * 0.94, 2)}")
            bot.send_message(CHAT_ID, msg)
        
        time.sleep(0.5) # Tránh bị ban do request nhanh

    bot.send_message(CHAT_ID, f"🏁 **BOSS ĐÃ QUÉT XONG!**\n✅ Tìm thấy {found_count} mã thỏa mãn.")

if __name__ == "__main__":
    main_worker()        
