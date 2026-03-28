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

# 1. Cấu hình cứng để chống lỗi Token (Dán thẳng, không dùng os.getenv)
TOKEN = '8625301702:AAHLOJgz_fIkfA6WpU7Sr60KjRIzc7nmHR4'
CHAT_ID = '1736294695'
# 2. Ép kiểu CHAT_ID sang số nguyên để tránh lỗi "chat not found"
try:
    CHAT_ID = int('1736294695')
except:
    print("Loi: CHAT_ID khong hop le!")

bot = telebot.TeleBot('8625301702:AAHLOJgz_fIkfA6WpU7Sr60KjRIzc7nmHR4')
bot = telebot.TeleBot(TOKEN)
vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

# 3. Gửi tin nhắn kiểm tra đầu tiên
try:
    bot.send_message(CHAT_ID, "🚀 Bot Scan Cổ Phiếu V10.1 (vnstock3 Data) đã bắt đầu chạy...")
except Exception as e:
    print(f"Lỗi gửi tin nhắn Telegram: {e}")
    
# FULL DANH SÁCH 160 MÃ KHÔNG CẮT BỚT
WATCHLIST = [
    'SSI', 'VND', 'VCI', 'HCM', 'FTS', 'MBS', 'BSI', 'CTS', 'VIX', 'SHS', 'ORS', 'AGR', 'TVS', 'BVS', 'VDS', 'SBS', # Chứng khoán
    'HPG', 'HSG', 'NKG', 'VGS', 'TVN', 'SMC', 'TLH', # Thép
    'VHM', 'VIC', 'VRE', 'PDR', 'DIG', 'DXG', 'NLG', 'KDH', 'CEO', 'TCH', 'NVL', 'HDG', 'KBC', 'GVR', 'BCM', 'IDC', 'SZC', 'VGC', 'PHR', 'ITA', 'SJS', 'SZL', 'TIP', 'LHG', 'D2D', 'NTC', 'NTL', 'QCG', 'AGG', 'KHG', # BĐS & KCN
    'VCG', 'HHV', 'LCG', 'C4G', 'FCN', 'HT1', 'BCC', 'BMP', 'CTD', 'HBC', # Đầu tư công & Xây dựng
    'PC1', 'TV2', 'REE', 'GAS', 'POW', 'PVS', 'PVD', 'PVB', 'PVC', 'PLX', 'OIL', 'BSR', # Năng lượng & Dầu khí
    'DGC', 'DCM', 'DPM', 'CSV', 'LAS', 'BFC', 'DDV', # Hóa chất & Phân bón
    'VCB', 'BID', 'CTG', 'TCB', 'MBB', 'ACB', 'HDB', 'VPB', 'STB', 'LPB', 'TPB', 'VIB', 'MSB', 'OCB', 'SHB', 'SSB', 'NAB', 'BAB', 'BVB', 'SGB', # Ngân hàng
    'FPT', 'MWG', 'MSN', 'PNJ', 'FRT', 'DGW', 'PET', 'CTR', 'VNM', 'SAB', 'VGI', 'FOX', 'CMG', 'ELC', 'VEA', 'MCH', 'MML', 'MSR', 'BHN', 'HAB', # Trụ & Bán lẻ & Công nghệ
    'VJC', 'HVN', 'ACV', 'GMD', 'HAH', 'VOS', 'VSC', 'MVN', 'SCS', 'TMS', # Hàng không & Cảng biển
    'VHC', 'ANV', 'IDI', 'FMC', 'ACL', 'MPC', 'CMX', # Thủy sản
    'TNG', 'MSH', 'GIL', # Dệt may
    'DBC', 'HAG', 'HNG', 'BAF', 'PAN', 'LTG', 'VIF', 'DPR', 'TRC', 'DRI', 'GEG', 'NT2', 'TTA' # Nông nghiệp & Cao su & Điện
]

# ==========================================
# 2. BỘ NÃO PHÂN TÍCH (BOSS ENGINE CORE)
# ==========================================
class UltimateBoss:
    def __init__(self, df, symbol):
        self.df = df
        self.symbol = symbol
        self.success = False
        try:
            self._add_indicators()
            self.success = True
        except Exception as e:
            print(f"Lỗi tính toán chỉ báo mã {symbol}: {e}")

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
        
        # MCDX Hybrid (Dòng tiền Cá mập) - Thêm fillna để tránh lỗi NaN
        mfi = ta.mfi(self.df['high'], self.df['low'], self.df['close'], self.df['volume'], length=14)
        low_20 = self.df['low'].rolling(20).min()
        high_20 = self.df['high'].rolling(20).max()
        
        # Ngăn lỗi chia cho 0 nếu high_20 == low_20
        diff = high_20 - low_20
        diff = diff.replace(0, 0.0001)
        
        banker_raw = ((self.df['close'] - low_20) / diff * 100).rolling(3).mean()
        self.df['banker'] = (banker_raw * 0.4) + (mfi.fillna(0) * 0.6)
        
        # Xóa các dòng NaN để không lỗi index
        self.df.dropna(subset=['ma20', 'vma20', 'bb_width', 'hist', 'banker'], inplace=True)

    def analyze(self):
        if not self.success or len(self.df) < 3:
            return None

        last = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        score = 0
        logs = []

        # --- TẦNG 1: DÒNG TIỀN MỒI ---
        if last['banker'] > 15:
            score += 2.0
            logs.append(f"Tiền mồi ({round(last['banker'])}%)")
            if last['banker'] > prev['banker']: 
                score += 1.5
                logs.append("Tiền nạp thêm")

        # --- TẦNG 2: GIA TỐC MACD ---
        if last['hist_slope'] > 0:
            score += 1.5
            logs.append("MACD hướng lên")
            if last['hist'] > 0: 
                score += 1.0
                logs.append("Xung lực mạnh")

        # --- TẦNG 3: ĐỘ NÉN SQUEEZE ---
        if last['bb_width'] < 0.12: 
            score += 2.0
            logs.append("Nén chặt")
        elif last['close'] > last['ma20']: 
            score += 1.0
            logs.append("Trên MA20")

        # --- TẦNG 4: KHỐI LƯỢNG ---
        now = datetime.now()
        vol_ratio = 0
        if last['vma20'] > 0:
            if 9 <= now.hour < 15:
                # Tính số phút đã trôi qua
                if now.hour < 12: 
                    mins = (now.hour - 9) * 60 + now.minute - 15
                else: 
                    mins = 135 + (now.hour - 13) * 60 + now.minute
                mins = max(mins, 1)
                projected_vol = (last['volume'] / mins) * 240
                vol_ratio = projected_vol / last['vma20']
            else:
                vol_ratio = last['volume'] / last['vma20']

        if vol_ratio > 1.3: 
            score += 2.0
            logs.append(f"Nổ Vol (x{round(vol_ratio,1)})")
        elif vol_ratio > 0.9: 
            score += 1.0
            logs.append("Vol ổn định")

        # --- BỘ LỌC RỦI RO ---
        upper_wick = last['high'] - max(last['close'], last['open'])
        body = abs(last['close'] - last['open'])
        is_trap = (upper_wick > (body * 0.6)) and (last['close'] < last['high'])

        return {
            "symbol": self.symbol, 
            "score": round(score, 1), 
            "price": last['close'],
            "vol_ratio": round(vol_ratio, 1), 
            "logs": " | ".join(logs), 
            "is_trap": is_trap
        }

# ==========================================
# 3. QUY TRÌNH VẬN HÀNH CHÍNH
# ==========================================
def send_telegram_msg(msg):
    """Hàm gửi tin nhắn an toàn, chống lỗi parse Markdown"""
    try:
        # Không dùng parse_mode="Markdown" để tránh bị lỗi vỡ font làm sập Bot
        bot.send_message(CHAT_ID, msg)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

def main_worker():
    now = datetime.now()
    is_summary_time = (now.hour == 14 and now.minute >= 45) or (now.hour >= 15) or (now.hour < 8) # Bao gồm cả buổi tối
    
    all_results = []
    total_symbols = len(WATCHLIST)
    
    send_telegram_msg(f"🚀 BOSS V10.1 BẮT ĐẦU QUÉT {total_symbols} MÃ...")
    
    start_date = (now - timedelta(days=90)).strftime('%Y-%m-%d')
    end_date = now.strftime('%Y-%m-%d')

    for i, symbol in enumerate(WATCHLIST):
        # In tiến độ ra console (nếu chạy trên GitHub Actions sẽ dễ debug)
        print(f"Đang quét {i+1}/{total_symbols}: {symbol}...")
        
        df = pd.DataFrame()
        # Tách riêng block try-except cho Data Fetching
        df = None
        try:
            # DÙNG NGUỒN KBS ĐỂ LÁCH TƯỜNG LỬA TRÊN GITHUB ACTIONS
            stock_obj = Vnstock().stock(symbol=symbol, source='KBS') 
            df = stock_obj.quote.history(start=start_date, end=end_date, interval='1D')
            
            # Bắt lỗi thêm trường hợp API sống nhưng trả về data rỗng
            if df is None or df.empty:
                print(f"⚠️ {symbol}: API KBS trả về dữ liệu trống.")
                continue
                
        except Exception as e:
            print(f"❌ Lỗi API tại mã {symbol} (Có thể do mạng): {e}")
            continue

        if df.empty or len(df) < 30:
            print(f"Dữ liệu {symbol} quá ngắn hoặc trống.")
            continue
            
        # Tính toán và phân tích
        boss = UltimateBoss(df, symbol)
        res = boss.analyze()
        
        if res is not None:
            all_results.append(res)
            
            # BÁO TRONG PHIÊN (Chỉ báo nếu điểm >= 7.5 và đang trong giờ giao dịch)
            if not is_summary_time and res['score'] >= 7.5:
                trap = "CẨN THẬN RÂU NẾN!" if res['is_trap'] else "Lực cầu Tốt"
                msg = (f"🔥 TÍN HIỆU NGON: {symbol}\n"
                       f"- Điểm: {res['score']}/10\n"
                       f"- Giá: {res['price']}\n"
                       f"- Vol dự báo: x{res['vol_ratio']} | {trap}\n"
                       f"- Dấu hiệu: {res['logs']}")
                send_telegram_msg(msg)
        
        time.sleep(1.2) # Nghỉ nửa giây tránh Rate Limit

    # BÁO CÁO TỔNG KẾT
    if is_summary_time:
        if len(all_results) == 0:
            send_telegram_msg("⚠️ Lỗi: Không quét được dữ liệu của bất kỳ mã nào! Hãy kiểm tra lại API vnstock.")
            return

        all_results.sort(key=lambda x: x['score'], reverse=True)
        
        report = f"🏁 SỚ TỔNG KẾT NGÀY {now.strftime('%d/%m')}\n"
        report += "━━━━━━━━━━━━━━\n"
        
        for i, item in enumerate(all_results[:10]):
            icon = "⭐" if i < 3 else "🔹"
            report += f"{icon} {item['symbol']}: {item['score']}đ | Vol x{item['vol_ratio']}\n"
        
        report += "\n💡 Lời khuyên: Tập trung soi kỹ Top 3 cho sáng mai!"
        send_telegram_msg(report)
    else:
        send_telegram_msg(f"✅ Đã quét xong {total_symbols} mã. Tìm thấy {len([x for x in all_results if x['score'] >= 7.5])} cơ hội.")

if __name__ == "__main__":
    main_worker()
        
