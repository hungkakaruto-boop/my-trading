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
# 2. TÍNH TỶ LỆ VOLUME DỰ KIẾN (GIÚP NHẬY BÉN BUỔI SÁNG)
# ==========================================
def get_volume_projection_ratio():
    now = datetime.now(vn_tz)
    # Tổng thời gian khớp lệnh liên tục tại VN là 225 phút
    # Sáng: 9:15 - 11:30 (135p), Chiều: 13:00 - 14:30 (90p)
    if now.hour < 9 or (now.hour == 9 and now.minute < 15): return 0.05
    if now.hour >= 15: return 1.0

    if now.hour < 12:
        elapsed = (now.hour - 9) * 60 + now.minute - 15
    else:
        elapsed = 135 + (now.hour - 13) * 60 + now.minute
    
    elapsed = max(10, min(elapsed, 225))
    return elapsed / 225

# ==========================================
# 3. LOGIC CHẤM ĐIỂM (ĐÃ NỚI LỎNG ĐỂ TĂNG CƠ HỘI)
# ==========================================
def calculate_signal_score(ticker, is_market_uptrend):
    try:
        now_vn = datetime.now(vn_tz)
        # Lấy dữ liệu 160 ngày để tính MA20 và đáy 20 phiên chuẩn xác
        df = stock_historical_data(ticker, (now_vn - timedelta(days=160)).strftime("%Y-%m-%d"), now_vn.strftime("%Y-%m-%d"), "1D", "stock")
        if df.empty or len(df) < 50: return None

        df['MA20'] = ta.sma(df['close'], length=20)
        df['Low_20'] = df['low'].rolling(window=20).min()
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        avg_vol_20 = df['volume'].iloc[:-1].tail(20).mean()
        
        # Volume Projection: Ước tính khối lượng cả ngày dựa trên thời điểm hiện tại
        ratio = get_volume_projection_ratio()
        projected_vol = curr['volume'] / ratio
        vol_factor = projected_vol / avg_vol_20

        score = 0
        details = []
        signal_type = ""

        # --- LOGIC SPRING / SHAKEOUT (Nới lỏng sai số 1%) ---
        is_spring_zone = curr['low'] <= df['Low_20'].iloc[-2] * 1.01
        if is_spring_zone and curr['close'] > prev['close']:
            score += 65
            if vol_factor < 1.1: 
                score += 20
                signal_type = "⚓ SPRING (CẠN CUNG)"
            else:
                score += 10
                signal_type = "🌪 SHAKEOUT (HẤP THỤ)"

        # --- LOGIC SOS / DÒNG TIỀN (Nới lỏng ngưỡng 1.4x) ---
        if curr['close'] > prev['close'] and vol_factor > 1.4:
            score += 60
            signal_type = "🔥 SOS (DÒNG TIỀN)"

        # Cộng điểm xu hướng
        if curr['close'] > curr['MA20']: score += 10
        if not is_market_uptrend: score -= 20

        # NGƯỠNG BÁO ĐỘNG: 65 điểm (Thay vì 75 như trước)
        if score >= 65:
            chart_link = f"https://fireant.vn/dashboard/symbol/{ticker}"
            return {'ticker': ticker, 'score': score, 'msg': f"Mẫu hình: **{signal_type}**\n📊 [Xem Chart]({chart_link})"}
        return None
    except: return None

# ==========================================
# 4. DANH SÁCH 150 MÃ MẠNH NHẤT & QUY TRÌNH QUÉT
# ==========================================
def main_scanner():
    watch_list = [
        "ACB","BID","CTG","FPT","GAS","GVR","HDB","HPG","MBB","MSN","MWG","PLX","POW","SAB","SHB","SSB","SSI","STB","TCB","TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VRE",
        "VND","VCI","HCM","SHS","MBS","FTS","BSI","CTS","AGR","VIX","ORS","TVB","TVS","BVS",
        "DIG","DXG","PDR","NVL","NLG","KDH","KBC","IDC","SZC","VGC","CEO","TCH","HQC","SCR","DXS","L14","HDG",
        "HSG","NKG","VGS","SMC","TLH",
        "VCG","LCG","HHV","CTD","PC1","C4G","FCN","HBC","REE","TV2",
        "DGC","DCM","DPM","CSV","LAS","BFC",
        "DGW","FRT","PNJ","PET","HAX",
        "PVS","PVD","PVT","BSR","CNG","OIL",
        "GMD","HAH","VSC","VOS",
        "DBC","HAG","BAF","VHC","ANV","IDI","ASM","MPC","CMX",
        "TNG","MSH","GIL","VGT","STK",
        "VGI","CTR","FOX","TTN","GEG","NT2","QTP","BCG"
    ]
    watch_list = list(set(watch_list)) # Lọc mã trùng

    now_str = datetime.now(vn_tz).strftime("%H:%M")
    
    # THÔNG BÁO BẮT ĐẦU (Gửi tin nhắn tiến độ)
    status_msg = bot.send_message(CHAT_ID, f"⏳ **[{now_str}]** Đang khởi động quét {len(watch_list)} mã cổ phiếu tiềm năng...")

    # Kiểm tra VN-Index
    try:
        df_vn = stock_historical_data("VNINDEX", (datetime.now(vn_tz)-timedelta(days=30)).strftime("%Y-%m-%d"), datetime.now(vn_tz).strftime("%Y-%m-%d"), "1D", "index")
        is_market_uptrend = df_vn.iloc[-1]['close'] > ta.sma(df_vn['close'], length=20).iloc[-1]
    except: is_market_uptrend = True

    scored_list = []
    # Quét đa luồng 15 workers cho tốc độ xé gió
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(calculate_signal_score, t, is_market_uptrend) for t in watch_list]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: scored_list.append(res)

    # XÓA TIN NHẮN TRẠNG THÁI TRƯỚC ĐÓ
    try: bot.delete_message(CHAT_ID, status_msg.message_id)
    except: pass

    # THÔNG BÁO KẾT QUẢ
    if scored_list:
        scored_list.sort(key=lambda x: x['score'], reverse=True)
        final_msg = f"🚀 **TÍN HIỆU REAL-TIME ({now_str})**\nVN-Index: {'✅ Thuận lợi' if is_market_uptrend else '⚠️ Rủi ro'}\n"
        for item in scored_list:
            final_msg += f"\n💎 **{item['ticker']}** (Điểm: {item['score']})\n{item['msg']}\n"
        bot.send_message(CHAT_ID, final_msg, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        # Luôn báo cáo để bạn biết bot vẫn đang làm việc tốt
        bot.send_message(CHAT_ID, f"✅ **[{now_str}]** Quét xong! Hiện chưa có mã nào bùng nổ hoặc rũ bỏ đạt chuẩn.")

if __name__ == "__main__":
    main_scanner()                
