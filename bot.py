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
# 2. TÍNH TỶ LỆ VOLUME DỰ KIẾN (GIÚP NHẬY BÉN BUỔI SÁNG)
# ==========================================
def get_volume_projection_ratio():
    now = datetime.now(vn_tz)
    # Giờ khớp lệnh: Sáng 9:15-11:30 (135p), Chiều 13:00-14:30 (90p). Tổng 225p.
    if now.hour < 9 or (now.hour == 9 and now.minute < 15): return 0.05
    if now.hour >= 15: return 1.0

    if now.hour < 12:
        elapsed = (now.hour - 9) * 60 + now.minute - 15
    else:
        elapsed = 135 + (now.hour - 13) * 60 + now.minute
    
    elapsed = max(10, min(elapsed, 225))
    return elapsed / 225

# ==========================================
# 3. LOGIC WYCKOFF & VSA (PHÂN TÍCH CHUYÊN SÂU)
# ==========================================
def calculate_signal_score(ticker, is_market_uptrend):
    try:
        now_vn = datetime.now(vn_tz)
        df = stock_historical_data(ticker, (now_vn - timedelta(days=160)).strftime("%Y-%m-%d"), now_vn.strftime("%Y-%m-%d"), "1D", "stock")
        if df.empty or len(df) < 50: return None

        # Tính Indicators
        df['MA20'] = ta.sma(df['close'], length=20)
        df['Low_20'] = df['low'].rolling(window=20).min()
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        avg_vol_20 = df['volume'].iloc[:-1].tail(20).mean()
        
        # Volume Projection (Ước tính Vol cả ngày)
        ratio = get_volume_projection_ratio()
        projected_vol = curr['volume'] / ratio
        vol_factor = projected_vol / avg_vol_20

        score = 0
        details = []
        signal_type = ""
        
        # --- LOGIC 1: SPRING / SHAKEOUT (RŨ BỎ CUỐI) ---
        # Giá chạm hoặc thủng đáy 20 phiên nhưng rút chân tăng lại
        is_spring_zone = curr['low'] <= df['Low_20'].iloc[-2] * 1.005 
        if is_spring_zone and curr['close'] > prev['close']:
            if vol_factor < 1.0: # Cạn cung (Spring chuẩn Wyckoff)
                score += 85
                signal_type = "⚓ SPRING (CẠN CUNG)"
                details.append("Rũ bỏ thủng đáy với Vol thấp -> Cực đẹp, dễ nổ")
            else:
                score += 60
                signal_type = "🌪 SHAKEOUT (HẤP THỤ)"
                details.append(f"Rũ bỏ Vol lớn ({round(vol_factor,1)}x) -> Cần đợi nhịp Test")

        # --- LOGIC 2: SOS (DÒNG TIỀN ĐẨY GIÁ) ---
        if curr['close'] > prev['close'] and vol_factor > 1.8 and curr['close'] > curr['MA20']:
            score += 70
            signal_type = "🔥 SOS (DÒNG TIỀN)"
            details.append(f"Dòng tiền vào cực mạnh (Dự kiến {round(vol_factor,1)}x TB)")

        # --- HIỆU CHỈNH ĐIỂM THEO THỊ TRƯỜNG & MA ---
        if not is_market_uptrend: score -= 20
        if curr['close'] > curr['MA20']: score += 10

        if score >= 75:
            chart_link = f"https://fireant.vn/dashboard/symbol/{ticker}"
            msg = f"Mẫu hình: **{signal_type}**\n- {chr(10).join(details)}\n📊 [Xem Chart]({chart_link})"
            return {'ticker': ticker, 'score': score, 'msg': msg}
        return None
    except: return None

# ==========================================
# 4. DANH SÁCH 150 MÃ MẠNH NHẤT (TUYỂN CHỌN)
# ==========================================
def main_scanner():
    watch_list = [
        "ACB","BID","CTG","FPT","GAS","GVR","HDB","HPG","MBB","MSN","MWG","PLX","POW","SAB","SHB","SSB","SSI","STB","TCB","TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VRE",
        "VND","VCI","HCM","SHS","MBS","FTS","BSI","CTS","AGR","VIX","ORS","TVB","TVS","BVS",
        "DIG","DXG","PDR","NVL","NLG","KDH","KBC","IDC","SZC","VGC","CEO","TCH","HQC","SCR","DXS","L14","HDG","D2D",
        "HSG","NKG","VGS","SMC","TLH",
        "VCG","LCG","HHV","CTD","PC1","C4G","FCN","HBC","CIAS","REE","TV2",
        "DGC","DCM","DPM","CSV","LAS","BFC",
        "DGW","FRT","PNJ","PET","HAX",
        "PVS","PVD","PVT","BSR","GAS","PLX","CNG","OIL",
        "GMD","HAH","VSC","VOS","PVT",
        "DBC","HAG","BAF","VHC","ANV","IDI","ASM","MPC","CMX",
        "TNG","MSH","GIL","VGT","STK",
        "VGI","CTR","FOX","TTN",
        "REE","GEG","NT2","QTP","HDG","BCG","TV2"
    ]
    watch_list = list(set(watch_list)) # Xóa mã trùng

    # Kiểm tra VN-Index
    try:
        df_vn = stock_historical_data("VNINDEX", (datetime.now(vn_tz)-timedelta(days=30)).strftime("%Y-%m-%d"), datetime.now(vn_tz).strftime("%Y-%m-%d"), "1D", "index")
        is_market_uptrend = df_vn.iloc[-1]['close'] > ta.sma(df_vn['close'], length=20).iloc[-1]
    except: is_market_uptrend = True

    scored_list = []
    # Đa luồng xử lý 150 mã trong ~10 giây
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(calculate_signal_score, t, is_market_uptrend) for t in watch_list]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: scored_list.append(res)

    if scored_list:
        scored_list.sort(key=lambda x: x['score'], reverse=True)
        now_str = datetime.now(vn_tz).strftime("%H:%M")
        msg = f"🚀 **WYCKOFF REAL-TIME ({now_str})**\nVN-Index: {'✅ OK' if is_market_uptrend else '⚠️ YẾU'}\n"
        for item in scored_list:
            msg += f"\n💎 **{item['ticker']}** (Điểm: {item['score']})\n{item['msg']}\n"
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)

if __name__ == "__main__":
    main_scanner()
