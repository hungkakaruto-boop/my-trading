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

# ==========================================
# 2. HÀM LẤY DỮ LIỆU TỪ FIREANT
# ==========================================
def get_fireant_data(ticker, days=160):
    """Hàm thay thế vnstock để lấy dữ liệu từ API của FireAnt"""
    url = f"https://restv2.fireant.vn/symbols/{ticker}/historical-quotes"
    now_vn = datetime.now(vn_tz)
    
    params = {
        "startDate": (now_vn - timedelta(days=days)).strftime("%Y-%m-%d"),
        "endDate": now_vn.strftime("%Y-%m-%d"),
        "offset": 0,
        "limit": days # Lấy tương đương số ngày
    }
    
    try:
        # Nhịp nghỉ nhỏ để tránh bị FireAnt khóa IP vì Spam request
        time.sleep(0.5) 
        response = requests.get(url, params=params, headers=FIREANT_HEADERS, timeout=10)
        
        if response.status_code == 200:
            df = pd.DataFrame(response.json())
            if not df.empty:
                # FireAnt trả về dữ liệu mới nhất ở trên cùng, cần đảo ngược lại từ cũ -> mới
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values(by='date', ascending=True).reset_index(drop=True)
                
                # Đảm bảo tên cột khớp với logic cũ (chữ in thường)
                df.rename(columns=lambda x: x.lower(), inplace=True)
                
                # Nếu FireAnt trả về tên cột khác, ép kiểu về chuẩn:
                if 'priceclose' in df.columns: df.rename(columns={'priceclose': 'close'}, inplace=True)
                if 'pricelow' in df.columns: df.rename(columns={'pricelow': 'low'}, inplace=True)
                if 'dealvolume' in df.columns: df.rename(columns={'dealvolume': 'volume'}, inplace=True)
                    
                return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Lỗi lấy dữ liệu {ticker}: {e}")
        return pd.DataFrame()

# ==========================================
# 3. TÍNH TỶ LỆ VOLUME DỰ KIẾN
# ==========================================
def get_volume_projection_ratio():
    now = datetime.now(vn_tz)
    if now.hour < 9 or (now.hour == 9 and now.minute < 15): return 0.05
    if now.hour >= 15: return 1.0

    if now.hour < 12:
        elapsed = (now.hour - 9) * 60 + now.minute - 15
    else:
        elapsed = 135 + (now.hour - 13) * 60 + now.minute
    
    elapsed = max(10, min(elapsed, 225))
    return elapsed / 225

# ==========================================
# 4. LOGIC CHẤM ĐIỂM (GIỮ NGUYÊN BẢN GỐC)
# ==========================================
def calculate_signal_score(ticker, is_market_uptrend):
    try:
        # Thay thế vnstock bằng hàm lấy data của FireAnt
        df = get_fireant_data(ticker, days=160)
        
        if df.empty or len(df) < 50: return None

        df['MA20'] = ta.sma(df['close'], length=20)
        df['Low_20'] = df['low'].rolling(window=20).min()
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        avg_vol_20 = df['volume'].iloc[:-1].tail(20).mean()
        
        ratio = get_volume_projection_ratio()
        projected_vol = curr['volume'] / ratio
        vol_factor = projected_vol / avg_vol_20

        score = 0
        signal_type = ""

        is_spring_zone = curr['low'] <= df['Low_20'].iloc[-2] * 1.01
        if is_spring_zone and curr['close'] > prev['close']:
            score += 65
            if vol_factor < 1.1: 
                score += 20
                signal_type = "⚓ SPRING (CẠN CUNG)"
            else:
                score += 10
                signal_type = "🌪 SHAKEOUT (HẤP THỤ)"

        if curr['close'] > prev['close'] and vol_factor > 1.4:
            score += 60
            signal_type = "🔥 SOS (DÒNG TIỀN)"

        if curr['close'] > curr['MA20']: score += 10
        if not is_market_uptrend: score -= 20

        if score >= 65:
            chart_link = f"https://fireant.vn/dashboard/symbol/{ticker}"
            return {'ticker': ticker, 'score': score, 'msg': f"Mẫu hình: **{signal_type}**\n📊 [Xem Chart]({chart_link})"}
        return None
    except: return None

# ==========================================
# 5. QUY TRÌNH QUÉT
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
    watch_list = list(set(watch_list)) 

    now_str = datetime.now(vn_tz).strftime("%H:%M")
    
    status_msg = bot.send_message(CHAT_ID, f"⏳ **[{now_str}]** Đang khởi động quét {len(watch_list)} mã cổ phiếu tiềm năng...")

    # Kiểm tra VN-Index bằng FireAnt
    try:
        df_vn = get_fireant_data("VNINDEX", days=30)
        is_market_uptrend = df_vn.iloc[-1]['close'] > ta.sma(df_vn['close'], length=20).iloc[-1]
    except: 
        is_market_uptrend = True

    scored_list = []
    
    # GIẢM WORKERS XUỐNG 3 ĐỂ TRÁNH BỊ FIREANT CHẶN IP
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(calculate_signal_score, t, is_market_uptrend) for t in watch_list]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: scored_list.append(res)

    try: bot.delete_message(CHAT_ID, status_msg.message_id)
    except: pass

    if scored_list:
        scored_list.sort(key=lambda x: x['score'], reverse=True)
        final_msg = f"🚀 **TÍN HIỆU REAL-TIME ({now_str})**\nVN-Index: {'✅ Thuận lợi' if is_market_uptrend else '⚠️ Rủi ro'}\n"
        for item in scored_list:
            final_msg += f"\n💎 **{item['ticker']}** (Điểm: {item['score']})\n{item['msg']}\n"
        bot.send_message(CHAT_ID, final_msg, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        bot.send_message(CHAT_ID, f"✅ **[{now_str}]** Quét xong! Hiện chưa có mã nào bùng nổ hoặc rũ bỏ đạt chuẩn.")

if __name__ == "__main__":
    main_scanner()        
