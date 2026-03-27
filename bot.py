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
# 2. BỘ NÃO PHÂN TÍCH (BOSS ENGINE CORE)
# ==========================================
class UltimateBoss:
    def __init__(self, df, symbol):
        self.df = df
        self.symbol = symbol
        self._add_indicators()

    def _add_indicators(self):
        # Xu hướng & Nền giá
        self.df['ma20'] = ta.sma(self.df['close'], length=20)
        self.df['vma20'] = ta.sma(self.df['volume'], length=20)
        
        # Bollinger Squeeze (Độ nén)
        bb = ta.bbands(self.df['close'], length=20, std=2)
        self.df['bb_width'] = (bb['BBU_20_2.0'] - bb['BBL_20_2.0']) / bb['BBM_20_2.0']
        
        # MACD Gia tốc (Momentum Slope)
        macd = self.df.ta.macd()
        self.df['hist'] = macd['MACDh_12_26_9']
        self.df['hist_slope'] = self.df['hist'].diff()
        
        # MCDX Hybrid (Dòng tiền Cá mập)
        mfi = ta.mfi(self.df['high'], self.df['low'], self.df['close'], self.df['volume'], length=14)
        low_20, high_20 = self.df['low'].rolling(20).min(), self.df['high'].rolling(20).max()
        banker_raw = ((self.df['close'] - low_20) / (high_20 - low_20) * 100).rolling(3).mean()
        self.df['banker'] = (banker_raw * 0.4) + (mfi * 0.6)

    def analyze(self):
        last, prev = self.df.iloc[-1], self.df.iloc[-2]
        score, logs = 0, []

        # --- TẦNG 1: DÒNG TIỀN MỒI (MCDX) - Max 3.5đ ---
        if last['banker'] > 15:
            score += 2.0; logs.append(f"Tiền mồi ({round(last['banker'])}%)")
            if last['banker'] > prev['banker']: score += 1.5; logs.append("🔥 Tiền nạp thêm")

        # --- TẦNG 2: GIA TỐC HỒI PHỤC (MACD) - Max 2.5đ ---
        if last['hist_slope'] > 0:
            score += 1.5; logs.append("🚀 MACD hướng lên")
            if last['hist'] > 0: score += 1.0; logs.append("Xung lực mạnh")

        # --- TẦNG 3: ĐỘ NÉN SQUEEZE (BB) - Max 2.0đ ---
        if last['bb_width'] < 0.12: score += 2.0; logs.append("💎 Nén chặt (Squeeze)")
        elif last['close'] > last['ma20']: score += 1.0; logs.append("🏠 Trên MA20")

        # --- TẦNG 4: KHỐI LƯỢNG (Dự báo Vol trong phiên) ---
        now = datetime.now()
        # Tính tỷ lệ thời gian đã qua trong phiên (Loại trừ giờ nghỉ trưa)
        if 9 <= now.hour < 15:
            if now.hour < 12: mins = (now.hour - 9) * 60 + now.minute - 15
            else: mins = 135 + (now.hour - 13) * 60 + now.minute
            mins = max(mins, 1)
            projected_vol = (last['volume'] / mins) * 240
            vol_ratio = projected_vol / last['vma20'] if last['vma20'] > 0 else 0
        else:
            vol_ratio = last['volume'] / last['vma20'] if last['vma20'] > 0 else 0

        if vol_ratio > 1.3: score += 2.0; logs.append(f"📊 Nổ Vol (x{round(vol_ratio,1)})")
        elif vol_ratio > 0.9: score += 1.0; logs.append("Vol ổn định")

        # --- BỘ LỌC RỦI RO (Price Action) ---
        upper_wick = last['high'] - max(last['close'], last['open'])
        body = abs(last['close'] - last['open'])
        is_trap = upper_wick > (body * 0.6) and last['close'] < last['high']

        return {
            "symbol": self.symbol, "score": round(score, 1), "price": last['close'],
            "vol_ratio": round(vol_ratio, 1), "logs": " | ".join(logs), "is_trap": is_trap
        }

# ==========================================
# 3. BỘ LỌC TIN TỨC (SAFETY CHECK)
# ==========================================
def check_news(symbol):
    try:
        news = stock.stock_news(symbol=symbol)
        if news.empty: return "✅ Sạch", 0
        blacklist = ['bị bắt', 'vi phạm', 'đình chỉ', 'thanh tra', 'khởi tố', 'hủy niêm yết']
        for title in news['title'].head(3):
            if any(word in title.lower() for word in blacklist): return "❌ XẤU", -5
        return "✅ Sạch", 0
    except: return "➖ Không rõ", 0

# ==========================================
# 4. QUY TRÌNH VẬN HÀNH (MAIN WORKER)
# ==========================================
def main_worker():
    now = datetime.now()
    is_summary_time = (now.hour == 14 and now.minute >= 45) or (now.hour >= 15)
    
    all_results = []
    bot.send_message(CHAT_ID, f"🚀 **BOSS V10 BẮT ĐẦU QUÉT {len(WATCHLIST)} MÃ...**")

    for symbol in WATCHLIST:
        try:
            df = stock.stock_historical_data(symbol=symbol, source='VCI', 
                                           start_date=(now - timedelta(days=60)).strftime('%Y-%m-%d'),
                                           end_date=now.strftime('%Y-%m-%d'))
            if df.empty or len(df) < 20: continue
            
            boss = UltimateBoss(df, symbol)
            res = boss.analyze()
            
            news_status, news_penalty = check_news(symbol)
            res['score'] += news_penalty
            res['news'] = news_status
            all_results.append(res)

            # --- TRONG PHIÊN: BÁO KÈO ĐIỂM CAO (>= 7.5đ) ---
            if not is_summary_time and res['score'] >= 7.5:
                trap_icon = "⚠️" if res['is_trap'] else "✅"
                msg = (f"🔥 **TÍN HIỆU NGON: {symbol}**\n"
                       f"🏆 Điểm: `{res['score']}/10` | Giá: {res['price']}\n"
                       f"📊 Dự báo Vol: x{res['vol_ratio']} | {trap_icon} Lực cầu\n"
                       f"📰 Tin tức: {res['news']}\n"
                       f"📝 {res['logs']}")
                bot.send_message(CHAT_ID, msg)
            
            time.sleep(0.5) # Chống block API
        except: continue

    # --- CUỐI PHIÊN: VIẾT SỚ TỔNG KẾT ---
    if is_summary_time:
        all_results.sort(key=lambda x: x['score'], reverse=True)
        report = f"🏁 **SỚ TỔNG KẾT NGÀY {now.strftime('%d/%m')}**\n━━━━━━━━━━━━━━\n"
        for i, item in enumerate(all_results[:10]):
            icon = "⭐" if i < 3 else "🔹"
            report += f"{icon} **{item['symbol']}**: `{item['score']}đ` | Vol x{item['vol_ratio']}\n"
        
        report += "\n💡 *Lời khuyên: Tập trung soi kỹ Top 3 cho sáng mai!*"
        bot.send_message(CHAT_ID, report)

if __name__ == "__main__":
    main_worker()    
    
