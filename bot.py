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
# 2. BỘ NÃO PHÂN TÍCH CHUYÊN SÂU
# ==========================================
class UltimateBossEngine:
    def __init__(self, df, symbol):
        self.df = df
        self.symbol = symbol
        self._prepare_indicators()

    def _prepare_indicators(self):
        # Tầng 1: Xu hướng & Độ nén (Bollinger Squeeze)
        self.df['ma20'] = ta.sma(self.df['close'], length=20)
        self.df['vma20'] = ta.sma(self.df['volume'], length=20)
        bb = ta.bbands(self.df['close'], length=20, std=2)
        # Độ rộng dải Bollinger (Càng nhỏ càng nén chặt)
        self.df['bb_width'] = (bb['BBU_20_2.0'] - bb['BBL_20_2.0']) / bb['BBM_20_2.0']
        
        # Tầng 2: Động lượng (MACD Slope & RSI)
        macd = self.df.ta.macd()
        self.df['hist'] = macd['MACDh_12_26_9']
        self.df['hist_slope'] = self.df['hist'].diff() # Gia tốc hồi phục
        self.df['rsi'] = ta.rsi(self.df['close'], length=14)
        
        # Tầng 3: Dòng tiền Cá mập (MCDX Hybrid)
        mfi = ta.mfi(self.df['high'], self.df['low'], self.df['close'], self.df['volume'], length=14)
        low_20, high_20 = self.df['low'].rolling(20).min(), self.df['high'].rolling(20).max()
        banker_p = ((self.df['close'] - low_20) / (high_20 - low_20) * 100).rolling(3).mean()
        self.df['banker'] = (banker_p * 0.4) + (mfi * 0.6) # Kết hợp giá và dòng tiền

    def get_comprehensive_score(self):
        last, prev = self.df.iloc[-1], self.df.iloc[-2]
        score, logs = 0, []

        # --- A. Dòng tiền (Max 3.5đ) ---
        if last['banker'] > 15:
            score += 2.0; logs.append(f"Tiền mồi ({round(last['banker'])}%)")
            if last['banker'] > prev['banker']: score += 1.5; logs.append("🔥 Gia tốc tiền tăng")

        # --- B. Động lượng MACD (Max 2.5đ) ---
        if last['hist_slope'] > 0:
            score += 1.5; logs.append("🚀 MACD hướng lên")
            if last['hist'] > 0: score += 1.0; logs.append("Xung lực dương")

        # --- C. Độ nén & Nền giá (Max 2.0đ) ---
        if last['bb_width'] < 0.12: 
            score += 2.0; logs.append("💎 Nén chặt (Squeeze)")
        elif last['close'] > last['ma20']: 
            score += 1.0; logs.append("🏠 Trên MA20")

        # --- D. Khối lượng & Gia tốc Vol (Max 2.0đ) ---
        # Ước tính Vol cuối ngày nếu đang trong phiên
        now = datetime.now()
        if 9 <= now.hour < 15:
            minutes_passed = (now.hour - 9) * 60 + now.minute - 15
            minutes_passed = max(minutes_passed, 1)
            projected_vol = (last['volume'] / minutes_passed) * 240
            vol_ratio = projected_vol / last['vma20'] if last['vma20'] > 0 else 0
        else:
            vol_ratio = last['volume'] / last['vma20'] if last['vma20'] > 0 else 0

        if vol_ratio > 1.3: score += 2.0; logs.append(f"📊 Nổ Vol (x{round(vol_ratio,1)})")
        elif vol_ratio > 0.9: score += 1.0; logs.append("Vol ổn định")

        # --- E. Kiểm tra áp lực bán (Price Action) ---
        upper_wick = last['high'] - max(last['close'], last['open'])
        body_size = abs(last['close'] - last['open'])
        is_pressured = upper_wick > (body_size * 0.6) # Râu nến dài

        return {
            "score": round(score, 1),
            "logs": " | ".join(logs),
            "price": last['close'],
            "vol_ratio": round(vol_ratio, 2),
            "is_pressured": is_pressured
        }

# ==========================================
# 3. HÀM CHẠY TỔNG HỢP & BÁO CÁO
# ==========================================
def run_ultimate_boss():
    now = datetime.now()
    # Kiểm tra xem có phải lúc tổng kết cuối ngày không (Sau 14:45)
    is_summary_time = (now.hour == 14 and now.minute >= 45) or (now.hour >= 15)
    
    all_results = []
    bot.send_message(CHAT_ID, f"🔄 **BOSS BẮT ĐẦU QUÉT {len(WATCHLIST)} MÃ...**")

    for symbol in WATCHLIST:
        try:
            # Lấy dữ liệu Intraday từ VCI (độ trễ thấp)
            df = stock.stock_historical_data(symbol=symbol, source='VCI', 
                                           start_date=(now - timedelta(days=60)).strftime('%Y-%m-%d'),
                                           end_date=now.strftime('%Y-%m-%d'))
            if df.empty or len(df) < 20: continue
            
            engine = UltimateBossEngine(df, symbol)
            res = engine.get_comprehensive_score()
            res['symbol'] = symbol
            all_results.append(res)

            # CẢNH BÁO TRONG PHIÊN: Chỉ báo kèo từ 8 điểm trở lên
            if not is_summary_time and res['score'] >= 8.0:
                p_icon = "⚠️" if res['is_pressured'] else "✅"
                msg = (f"🚀 **PHÁT HIỆN ĐIỂM NỔ: {symbol}**\n"
                       f"🏆 Điểm: `{res['score']}/10` | Giá: {res['price']}\n"
                       f"📊 Dự báo Vol: x{res['vol_ratio']} | {p_icon} Lực cầu\n"
                       f"📝 {res['logs']}")
                bot.send_message(CHAT_ID, msg)
            
            time.sleep(0.5)
        except: continue

    # BÁO CÁO TỔNG KẾT CUỐI NGÀY
    if is_summary_time:
        all_results.sort(key=lambda x: x['score'], reverse=True)
        report = "🏁 **BÁO CÁO SỨC MẠNH DÒNG TIỀN**\n━━━━━━━━━━━━━━\n"
        for i, item in enumerate(all_results[:10]):
            icon = "⭐" if i < 3 else "🔹"
            report += f"{icon} **{item['symbol']}**: `{item['score']}đ` | x{item['vol_ratio']} Vol\n"
        
        report += "\n💡 *Lời khuyên: Top 3 đang có gia tốc tốt nhất, chú ý phiên mai!*"
        bot.send_message(CHAT_ID, report)

if __name__ == "__main__":
    run_ultimate_boss()                    
