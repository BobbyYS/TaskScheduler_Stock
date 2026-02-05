import os
import smtplib
import pandas as pd
import numpy as np
import yfinance as yf
import twstock
from tqdm import tqdm
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ 使用者設定區
# ==========================================
MY_PORTFOLIO = {
    '4939.TW': {'cost': 51.2, 'stop_loss_pct': 0.07},  # 亞電
    '3346.TW': {'cost': 50.8, 'stop_loss_pct': 0.07},  # 麗清
    '2492.TW': {'cost': 133.5, 'stop_loss_pct': 0.07} # 華新科
}

# 環境變數由 GitHub Secrets 提供
GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
RECEIVER_EMAIL = os.environ.get('RECEIVER_EMAIL')

class StockSystem:
    def __init__(self):
        self.bench_ticker = '0050.TW'
        # 篩選參數彙整
        self.min_price = 20
        self.min_volume_chose = 800000
        self.min_volume_drive = 1000000
        self.rs_period_chose = 20
        self.rs_period_drive = 60

    def get_benchmark_roc(self, period):
        """獲取大盤動能基準"""
        try:
            bench = yf.download(self.bench_ticker, period='1y', progress=False, auto_adjust=True)
            close = bench['Close'].iloc[:, 0] if isinstance(bench['Close'], pd.DataFrame) else bench['Close']
            return float(close.pct_change(period).iloc[-1])
        except: return 0

    def health_check_logic(self, ticker, data, df):
        """移植自 health.py 的健檢邏輯"""
        try:
            close = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
            curr = float(close.iloc[-1])
            cost = data['cost']
            init_risk_pct = data['stop_loss_pct']
            init_risk_amt = cost * init_risk_pct
            
            pnl_amt = curr - cost
            r_multiple = pnl_amt / init_risk_amt
            
            ma10 = float(close.rolling(10).mean().iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])
            
            action = "✅ 續抱"
            reason = []
            hard_stop = cost * (1 - init_risk_pct)
            
            # 邏輯判定
            if curr < hard_stop:
                action = "🛑 停損"
                reason.append(f"跌破初始停損 {round(hard_stop, 2)}")
            elif r_multiple >= 2:
                if curr < cost:
                    action = "🛑 保本賣出"
                    reason.append("獲利回吐觸及成本")
                else: reason.append(f"獲利 {round(r_multiple,1)}R，保本防守")
            
            is_super = (close.iloc[-35:] > close.rolling(10).mean().iloc[-35:]).all()
            check_ma = ma10 if is_super else ma20
            if curr < check_ma:
                action = "⚠️ 警戒/賣出"
                reason.append(f"跌破 {'10MA' if is_super else '20MA'}")

            return {
                "代號": ticker, "現價": round(curr, 2), "獲利(R)": f"{round(r_multiple, 1)}R",
                "建議動作": action, "診斷原因": " | ".join(reason)
            }
        except: return None

    def analyze_chose(self, ticker, name, df, bench_roc):
        """移植自 chose.py 的選股邏輯"""
        try:
            close = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
            high = df['High'].iloc[:, 0] if isinstance(df['High'], pd.DataFrame) else df['High']
            vol = df['Volume'].iloc[:, 0] if isinstance(df['Volume'], pd.DataFrame) else df['Volume']
            
            curr = float(close.iloc[-1])
            avg_vol = float(vol.rolling(20).mean().iloc[-1])
            
            if curr < self.min_price or avg_vol < self.min_volume_chose: return None
            
            ma50, ma200 = float(close.rolling(50).mean().iloc[-1]), float(close.rolling(200).mean().iloc[-1])
            if not (curr > ma50 > ma200): return None
            
            stock_roc = float(close.pct_change(self.rs_period_chose).iloc[-1])
            if stock_roc < bench_roc: return None
            
            # 型態辨識 (HTF/VCP)
            year_high = float(high.iloc[-250:].max())
            prev_20_high = float(high.iloc[-21:-1].max())
            is_breakout = (curr > prev_20_high) and (close.iloc[-2] < prev_20_high)
            
            if is_breakout and (year_high - curr)/year_high < 0.15:
                return {"代號": ticker, "名稱": name, "現價": round(curr, 2), "型態": "VCP/箱型突破", "RS": round((stock_roc-bench_roc)*100, 1)}
            return None
        except: return None

    def analyze_drive(self, info, df, bench_roc):
        """移植自 drive.py 的 DRIVE 邏輯"""
        try:
            close = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
            vol = df['Volume'].iloc[:, 0] if isinstance(df['Volume'], pd.DataFrame) else df['Volume']
            curr = float(close.iloc[-1])
            avg_vol = float(vol.rolling(20).mean().iloc[-1])
            
            if curr < self.min_price or avg_vol < self.min_volume_drive: return None
            
            stock_roc = float(close.pct_change(self.rs_period_drive).iloc[-1])
            rs_rating = (stock_roc - bench_roc) * 100
            if rs_rating < 5: return None
            
            # MVP 邏輯
            up_days = (close.iloc[-16:-1].diff() > 0).sum()
            is_mvp = up_days >= 9
            
            if is_mvp:
                return {"代號": info['ticker'], "名稱": info['name'], "產業": info['industry'], "評分": "🔥MVP大戶吸籌", "RS": round(rs_rating, 1)}
            return None
        except: return None

    def run(self):
        # 初始化數據
        print("📋 正在抓取市場清單...")
        codes = twstock.codes
        all_stocks = [{'ticker': c + ('.TW' if r.market == '上市' else '.TWO'), 'name': r.name, 'industry': r.group} 
                      for c, r in codes.items() if r.type == '股票']
        
        bench_roc_c = self.get_benchmark_roc(self.rs_period_chose)
        bench_roc_d = self.get_benchmark_roc(self.rs_period_drive)
        
        res_h, res_c, res_d = [], [], []

        print(f"🚀 開始分析 {len(all_stocks)} 檔股票...")
        for item in tqdm(all_stocks):
            ticker = item['ticker']
            try:
                # 每個代號只下載一次資料 (取1年確保MA200正確)
                df = yf.download(ticker, period='1y', progress=False, auto_adjust=True)
                if df.empty or len(df) < 200: continue

                # 1. 如果在清單內，執行健檢
                if ticker in MY_PORTFOLIO:
                    h = self.health_check_logic(ticker, MY_PORTFOLIO[ticker], df)
                    if h: res_h.append(h)
                
                # 2. 執行選股掃描
                c = self.analyze_chose(ticker, item['name'], df, bench_roc_c)
                if c: res_c.append(c)
                
                d = self.analyze_drive(item, df, bench_roc_d)
                if d: res_d.append(d)
            except: continue
        
        return res_h, res_c, res_d

# ==========================================
# 📧 郵件發送與 HTML 格式化
# ==========================================
def send_email(h, c, d):
    df_h, df_c, df_d = pd.DataFrame(h), pd.DataFrame(c), pd.DataFrame(d)
    
    # 計算綜合結果 (交集)
    set_c = set(df_c['代號']) if not df_c.empty else set()
    set_d = set(df_d['代號']) if not df_d.empty else set()
    inter_list = list(set_c & set_d)
    df_inter = pd.concat([df_c[df_c['代號'].isin(inter_list)], df_d[df_d['代號'].isin(inter_list)]]).drop_duplicates('代號')

    style = """
    <style>
        .title { background: #2c3e50; color: white; padding: 10px; margin-top: 20px; font-weight: bold; }
        .table { border-collapse: collapse; width: 100%; font-family: sans-serif; margin-bottom: 20px; }
        .table th, .table td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        .table th { background-color: #f8f9fa; }
        .highlight { background-color: #fff3cd; color: #856404; font-weight: bold; }
    </style>
    """
    
    html = f"<html><head>{style}</head><body>"
    html += "<h2>📈 每日台股策略報告</h2>"
    
    html += "<div class='title'>🏥 庫存健檢報告</div>"
    html += df_h.to_html(classes='table', index=False) if not df_h.empty else "<p>無庫存數據</p>"

    html += "<div class='title' style='background:#d9534f;'>🔥 綜合最強訊號 (DRIVE & CHOSE 雙重認證)</div>"
    html += df_inter.to_html(classes='table', index=False) if not df_inter.empty else "<p>今日無雙重認證訊號</p>"

    html += "<div class='title'>🚀 買入型態掃描 (CHOSE - VCP/高窄旗型)</div>"
    html += df_c.to_html(classes='table', index=False) if not df_c.empty else "<p>今日無訊號</p>"

    html += "<div class='title'>👑 終極大戶動能 (DRIVE - MVP/板塊)</div>"
    html += df_d.to_html(classes='table', index=False) if not df_d.empty else "<p>今日無訊號</p>"
    
    html += "</body></html>"

    msg = MIMEMultipart()
    msg['Subject'] = f"台股策略報告 - {pd.Timestamp.now().strftime('%Y-%m-%d')}"
    msg['From'] = GMAIL_USER
    msg['To'] = RECEIVER_EMAIL
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)

if __name__ == "__main__":
    system = StockSystem()
    h, c, d = system.run()
    send_email(h, c, d)
    print("Done!")