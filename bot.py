import telebot
import pandas-ta as ta
import time
import os
from datetime import datetime, timedelta
from vnstock import *

# --- CONFIG ---
if TOKEN
   TOKEN = int('8625301702:AAHLOJgz_fIkfA6WpU7Sr60KjRIzc7nmHR4')
if CHAT_ID
   CHAT_ID = int('1736294695')
bot = telebot.TeleBot('8625301702:AAHLOJgz_fIkfA6WpU7Sr60KjRIzc7nmHR4')

# Danh sách 120 mã chọn lọc
WATCHLIST = [
    'ACB', 'BCM', 'BID', 'BVH', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG', 
    'MBB', 'MSN', 'MWG', 'PLX', 'POW', 'SAB', 'SHB', 'SSB', 'SSI', 'STB', 
    'TCB', 'TPB', 'VCB', 'VHM', 'VIB', 'VIC', 'VNM', 'VPB', 'VRE', 'VJC',
    'DGC', 'DXG', 'DIG', 'PDR', 'NLG', 'KDH', 'KBC', 'GEX', 'VND', 'VCI', 
    'HCM', 'HSG', 'NKG', 'PVD', 'PVT', 'PC1', 'DBC', 'ANV', 'VHC', 'TCH', 
    'HAG', 'HHV', 'LCG', 'FCN', 'VGC', 'DPM', 'DCM', 'FRT', 'CTR', 'DGW',
    'REE', 'SCS', 'EIB', 'MSB', 'LPB', 'OCB', 'PNJ', 'SAM', 'VIX', 'GMD',
    'PVS', 'SHS', 'IDC', 'CEO', 'NTP', 'MBS', 'VCS', 'DTD', 'TNG', 'L14',
    'VGI', 'ACV', 'VEA', 'MCH', 'BSR', 'CSI', 'VTP', 'FOX', 'LTG', 'QNS',
    'ABB', 'BVB', 'NAB', 'VAB', 'KLB', 'OIL', 'PVC', 'DDV', 'VGT', 'SSH'
]

def alpha_scanner(s):
    try:
        # Lấy dữ liệu đủ dài để tính MA200 và RS
        df = stock_historical_data(symbol=s, start_date='2024-01-01', resolution='1D', type='stock')
        if df is None or df.empty or len(df) < 150: return None

        # 1. Các đường trung bình quan trọng (Trend Filter)
        df['MA20'] = ta.sma(df['close'], length=20)
        df['MA50'] = ta.sma(df['close'], length=50)
        df['MA200'] = ta.sma(df['close'], length=200)
        
        # 2. Độ biến động (Bollinger Bands Squeeze)
        bb = ta.bbands(df['close'], length=20, std=2)
        df['Bwidth'] = (bb['BBU_20_2.0'] - bb['BBL_20_2.0']) / bb['BBM_20_2.0']
        
        # 3. Sức mạnh dòng tiền & RSI
        df['RSI'] = ta.rsi(df['close'], length=14)
        vol_avg = df['volume'].tail(20).mean()
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        # --- BỘ LỌC CHẤT LƯỢNG CAO (MINERVINI & VSA) ---
        # A. Xu hướng: Giá phải nằm trên MA50 và MA200 (Ưu tiên Uptrend)
        is_uptrend = curr['close'] > curr['MA50'] and curr['MA50'] > curr['MA200']
        
        # B. Độ nén: Bollinger Band Width thấp (đang tích lũy chặt)
        is_squeezed = curr['Bwidth'] < df['Bwidth'].tail(100).mean()
        
        # C. Điểm nổ: Vol gấp > 2.5 lần và giá vượt đỉnh 20 phiên
        high_20 = df['high'].tail(20).max()
        is_breakout = curr['close'] >= high_20 and curr['volume'] > vol_avg * 2.5
        
        # D. Lực nến: Đóng cửa gần cao nhất phiên
        candle_perf = (curr['close'] - curr['low']) / (curr['high'] - curr['low'] + 0.001)

        # XÁC NHẬN SIÊU TÍN HIỆU (SCORE)
        score = 0
        if is_uptrend: score += 30
        if is_breakout: score += 40
        if candle_perf > 0.9: score += 20
        if is_squeezed: score += 10

        if score >= 80:
            entry = curr['close']
            # Cắt lỗ theo ATR hoặc đáy gần nhất (7% tiêu chuẩn)
            sl = entry * 0.93 
            tp1 = entry * 1.15 # Kỳ vọng 15%
            tp2 = entry * 1.25 # Kỳ vọng 25%

            status = "💎 SIÊU CỔ PHIẾU (VCP)" if score == 100 else "🚀 ĐIỂM NỔ VOL"
            
            return (f"{status}: **{s}**\n"
                    f"⭐ Độ tin cậy: **{score}%**\n"
                    f"--- --- ---\n"
                    f"✅ **MUA: {entry:,.0f}**\n"
                    f"🛡 **CẮT LỖ: {sl:,.0f} (-7%)**\n"
                    f"🎯 **MỤC TIÊU: {tp1:,.0f} - {tp2:,.0f}**\n"
                    f"--- --- ---\n"
                    f"📊 Vol: {curr['volume']/vol_avg:.1f}x TB\n"
                    f"📈 RSI: {curr['RSI']:.1f}\n"
                    f"📉 Nền giá: {'Chặt chẽ' if is_squeezed else 'Đang lỏng'}")
        return None
    except:
        return None

if __name__ == "__main__":
    # Gửi báo cáo bắt đầu
    start_msg = bot.send_message(CHAT_ID, f"🔍 **[Hệ thống Quản trị Alpha]**\nĐang quét 120 mã theo tiêu chuẩn Minervini...")
    
    found = []
    for s in WATCHLIST:
        res = alpha_scanner(s)
        if res:
            found.append(s)
            bot.send_message(CHAT_ID, res, parse_mode='Markdown')
        time.sleep(0.5)

    # Tự động xóa tin nhắn bắt đầu để tránh rác Group sau khi xong
    try:
        bot.delete_message(CHAT_ID, start_msg.message_id)
    except:
        pass
