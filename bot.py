import os
import time
import pandas_ta as ta
import pandas as pd
import telebot
from vnstock import *
import concurrent.futures

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
def get_volume_projection_ratio():
    now = datetime.now(vn_tz)
    if now.hour < 9 or (now.hour == 9 and now.minute < 15): return 0.05
    if now.hour >= 15: return 1.0
    if now.hour < 12:
        elapsed = (now.hour - 9) * 60 + now.minute - 15
    else:
        elapsed = 135 + (now.hour - 13) * 60 + now.minute
    return max(10, min(elapsed, 225)) / 225

def calculate_signal_score(ticker, is_market_uptrend):
    try:
        now_vn = datetime.now(vn_tz)
        df = stock_historical_data(ticker, (now_vn - timedelta(days=160)).strftime("%Y-%m-%d"), now_vn.strftime("%Y-%m-%d"), "1D", "stock")
        if df.empty or len(df) < 50: return None
        df['MA20'] = ta.sma(df['close'], length=20)
        df['Low_20'] = df['low'].rolling(window=20).min()
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        avg_vol_20 = df['volume'].iloc[:-1].tail(20).mean()
        ratio = get_volume_projection_ratio()
        vol_factor = (curr['volume'] / ratio) / avg_vol_20
        score = 0
        details = []
        signal_type = ""
        is_spring_zone = curr['low'] <= df['Low_20'].iloc[-2] * 1.005 
        if is_spring_zone and curr['close'] > prev['close']:
            if vol_factor < 1.0:
                score += 85
                signal_type = "⚓ SPRING (CẠN CUNG)"
                details.append("Rũ bỏ thủng đáy với Vol thấp -> Cực đẹp")
            else:
                score += 60
                signal_type = "🌪 SHAKEOUT (HẤP THỤ)"
                details.append(f"Rũ bỏ Vol lớn ({round(vol_factor,1)}x)")
        if curr['close'] > prev['close'] and vol_factor > 1.8 and curr['close'] > curr['MA20']:
            score += 70
            signal_type = "🔥 SOS (DÒNG TIỀN)"
            details.append(f"Tiền vào mạnh (Dự kiến {round(vol_factor,1)}x TB)")
        if not is_market_uptrend: score -= 20
        if score >= 75:
            chart_link = f"https://fireant.vn/dashboard/symbol/{ticker}"
            msg = f"Mẫu hình: **{signal_type}**\n- {chr(10).join(details)}\n📊 [Xem Chart]({chart_link})"
            return {'ticker': ticker, 'score': score, 'msg': msg}
        return None
    except: return None

# ==========================================
# 4. HÀM QUÉT CHÍNH (ĐÃ THÊM THÔNG BÁO TIN NHẮN)
# ==========================================
def main_scanner():
    watch_list = ["ACB","BID","CTG","FPT","GAS","GVR","HPG","MBB","MSN","MWG","POW","SSI","STB","TCB","VCB","VHM","VIC","VNM","VPB","VRE","VND","VCI","SHS","DIG","DXG","PDR","NVL","KBC","HSG","NKG","PC1","DGC","PVS","PVD","GEX","VGS","VCG","LCG","HHV","CTD","DCM","DPM","FRT","PNJ","GMD","HAH","DBC","HAG","VHC","ANV","IDI","ASM","MPC","CMX","TNG","MSH","GIL","VGT","STK","VGI","CTR","FOX","TTN","REE","GEG","NT2","QTP","HDG","BCG","TV2"]
    watch_list = list(set(watch_list))
    
    now_str = datetime.now(vn_tz).strftime("%H:%M")
    
    # --- THÔNG BÁO 1: BẮT ĐẦU LÀM VIỆC ---
    # Bot nhắn tin báo cho bạn biết nó bắt đầu quét 150 mã
    status_msg = bot.send_message(CHAT_ID, f"⏳ **[{now_str}]** Đang khởi động quét {len(watch_list)} mã cổ phiếu...")

    try:
        df_vn = stock_historical_data("VNINDEX", (datetime.now(vn_tz)-timedelta(days=30)).strftime("%Y-%m-%d"), datetime.now(vn_tz).strftime("%Y-%m-%d"), "1D", "index")
        is_market_uptrend = df_vn.iloc[-1]['close'] > ta.sma(df_vn['close'], length=20).iloc[-1]
    except: is_market_uptrend = True

    scored_list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(calculate_signal_score, t, is_market_uptrend) for t in watch_list]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: scored_list.append(res)

    # Xóa dòng "Đang khởi động..." để tránh rác màn hình chat
    try: bot.delete_message(CHAT_ID, status_msg.message_id)
    except: pass

    # --- THÔNG BÁO 2: KẾT QUẢ CUỐI CÙNG ---
    if scored_list:
        scored_list.sort(key=lambda x: x['score'], reverse=True)
        final_msg = f"🏆 **TÍN HIỆU THỊ TRƯỜNG ({now_str})**\nVN-Index: {'✅ OK' if is_market_uptrend else '⚠️ YẾU'}\n"
        for item in scored_list:
            final_msg += f"\n💎 **{item['ticker']}** (Điểm: {item['score']})\n{item['msg']}\n"
        bot.send_message(CHAT_ID, final_msg, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        # Nếu không tìm thấy mã nào cũng phải báo để bạn biết Bot không bị chết
        bot.send_message(CHAT_ID, f"✅ **[{now_str}]** Quét xong! Thị trường hiện chưa có tín hiệu Wyckoff đạt chuẩn.")

if __name__ == "__main__":
    main_scanner()
