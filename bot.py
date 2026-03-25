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

# 4. Hàm phân tích và chấm điểm
def calculate_signal_score(ticker):
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        
        df = stock_historical_data(ticker, start_date, end_date, "1D")
        if df.empty or len(df) < 50: return 0, ""

        # Tính trung bình Vol 20 phiên
        avg_vol = df['volume'].tail(20).mean()
        
        # BỘ LỌC BẢO VỆ: Bỏ qua các mã thanh khoản thấp (dưới 500k cổ/phiên)
        if avg_vol < 500000:
            return 0, ""

        score = 0
        details = []
        
        df['MA20'] = ta.sma(df['close'], length=20)
        df['MA50'] = ta.sma(df['close'], length=50)
        df['RSI'] = ta.rsi(df['close'], length=14)
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # Tiêu chí 1: Xu hướng (30 điểm)
        if curr['close'] > curr['MA20'] > curr['MA50']:
            score += 30
            details.append("✅ Uptrend (Giá > MA20 > MA50)")
        
        # Tiêu chí 2: Dòng tiền & SOS (30 điểm)
        if curr['volume'] > avg_vol * 1.5:
            score += 30
            details.append(f"🔥 Vol Đột biến ({round(curr['volume']/avg_vol, 1)}x)")
        elif curr['volume'] > avg_vol:
            score += 15
            details.append("📈 Vol Tích cực")

        # Tiêu chí 3: RSI Vùng an toàn (20 điểm)
        if 50 < curr['RSI'] < 65:
            score += 20
            details.append(f"💎 RSI Chân sóng ({round(curr['RSI'], 1)})")
            
        # Tiêu chí 4: Sức mạnh bứt nền (20 điểm)
        change = (curr['close'] - prev['close']) / prev['close'] * 100
        if change > 2.5:
            score += 20
            details.append(f"🚀 Nổ giá ({round(change, 1)}%)")

        return score, "\n".join(details)
    except Exception as e:
        return 0, ""

# 5. Quét toàn bộ VN100 + Top HNX/UPCOM
def main_scanner():
    # Danh mục Vàng: ~110 mã mạnh nhất toàn thị trường
    watch_list = [
        # VN30 (Bluechips)
        "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", 
        "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB", 
        "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
        # Chứng khoán (Độ nhạy cao)
        "VND", "VCI", "HCM", "SHS", "MBS", "FTS", "BSI", "CTS", "AGR", "VIX", "ORS",
        # Bất động sản & KCN (Thường xuyên có Spring/SOS)
        "DIG", "DXG", "PDR", "NVL", "NLG", "KDH", "KBC", "IDC", "SZC", "VGC", "CEO", "TCH", "HDG", "HDC",
        # Thép & Vật liệu xây dựng
        "HSG", "NKG", "VGS", "HT1", "BCC", "KSB",
        # Xây dựng, Đầu tư công & Điện
        "VCG", "LCG", "HHV", "CTD", "CII", "HUT", "FCN", "PC1", "GEG", "NT2",
        # Hóa chất & Phân bón
        "DGC", "DCM", "DPM", "CSV",
        # Bán lẻ & Công nghệ
        "DGW", "FRT", "PNJ", "PET", "CTR",
        # Dầu khí & Cảng biển
        "PVS", "PVD", "PVT", "BSR", "OIL", "GMD", "HAH", "VOS",
        # Nông nghiệp, Thủy sản, Dệt may
        "DBC", "HAG", "VHC", "ANV", "IDI", "TNG", "GIL"
    ]
    
    scored_list = []
    bot.send_message(CHAT_ID, f"⏳ Đang quét {len(watch_list)} mã VN100 & Midcap thanh khoản cao...")
    
    for ticker in watch_list:
        score, details = calculate_signal_score(ticker)
        if score >= 70: 
            scored_list.append({'ticker': ticker, 'score': score, 'details': details})
        time.sleep(0.6) # Nghỉ 0.6s để hệ thống không chặn IP

    scored_list.sort(key=lambda x: x['score'], reverse=True)

    if scored_list:
        message = "🏆 **BẢNG XẾP HẠNG WYCKOFF T+10** 🏆\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for item in scored_list:
            rank_label = "🌟 SIÊU CỔ" if item['score'] >= 90 else "🎯 TIỀM NĂNG"
            message += f"{rank_label}: **{item['ticker']}**\n"
            message += f"📊 Điểm: `{item['score']}/100`\n"
            message += f"{item['details']}\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n"
            
        bot.send_message(CHAT_ID, message, parse_mode="Markdown")
    else:
        bot.send_message(CHAT_ID, "⚠️ Cầm tiền quan sát! Không có mã nào đạt thanh khoản và tiêu chuẩn >= 70 điểm.")

if __name__ == "__main__":
    main_scanner() 
