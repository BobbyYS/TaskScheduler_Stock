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
    '2492.TW': {'cost': 133.5, 'stop_loss_pct': 0.07}, # 華新科
    '2317.TW': {'cost': 227.2, 'stop_loss_pct': 0.07}  # 鴻海
}

# 環境變數 (GitHub Secrets)
GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
RECEIVER_EMAIL = os.environ.get('RECEIVER_EMAIL')

class StockSystem:
    def __init__(self):
        self.bench_ticker = '0050.TW'
        self.min_price = 5
        self.min_volume_chose = 800000
        self.min_volume_drive = 1000000
        self.rs_period_chose = 20
        self.rs_period_drive = 60

    def get_benchmark_roc(self, period):
        try:
            bench = yf.download(self.bench_ticker, period='1y', progress=False, auto_adjust=True)
            close = bench['Close'].iloc[:, 0] if isinstance(bench['Close'], pd.DataFrame) else bench['Close']
            return float(close.pct_change(period).iloc[-1])
        except: return 0

    def health_check_logic(self, ticker, name, data, df):
        """完全移植考特賣出法則"""
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
            
            action, reason = "✅ 續抱", []
            hard_stop = cost * (1 - init_risk_pct)
            
            if curr < hard_stop:
                action = "🛑 清倉賣出(停損)"
                reason.append(f"跌破初始停損 {round(hard_stop, 2)}")
            elif r_multiple >= 2:
                if curr < cost: action = "🛑 清倉賣出(保本)"; reason.append("獲利回吐觸及成本")
                else: reason.append(f"達2R({round(r_multiple,1)}R)啟動保本")
            
            is_super = (close.iloc[-35:] > close.rolling(10).mean().iloc[-35:]).all()
            check_ma = ma10 if is_super else ma20
            if curr < check_ma:
                action = "⚠️ 警戒/賣出"
                reason.append(f"跌破{'10MA' if is_super else '20MA'}")
            
            return {"代號": ticker, "名稱": name, "現價": round(curr, 2), "獲利(R)": f"{round(r_multiple, 1)}R", "建議動作": action, "防守價": round(max(hard_stop, check_ma), 2), "原因": " | ".join(reason)}
        except: return None

    def analyze_chose(self, ticker, name, df, bench_roc):
        """全量移植買入型態判斷"""
        try:
            close = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
            high = df['High'].iloc[:, 0] if isinstance(df['High'], pd.DataFrame) else df['High']
            vol = df['Volume'].iloc[:, 0] if isinstance(df['Volume'], pd.DataFrame) else df['Volume']
            open_p = df['Open'].iloc[:, 0] if isinstance(df['Open'], pd.DataFrame) else df['Open']
            
            curr, avg_vol = float(close.iloc[-1]), float(vol.rolling(20).mean().iloc[-1])
            if curr < self.min_price or avg_vol < self.min_volume_chose: return None
            
            ma50, ma200 = float(close.rolling(50).mean().iloc[-1]), float(close.rolling(200).mean().iloc[-1])
            if not (curr > ma50 > ma200): return None
            
            stock_roc = float(close.pct_change(self.rs_period_chose).iloc[-1])
            rs_rating = (stock_roc - bench_roc) * 100
            if rs_rating < 0: return None
            
            year_high = float(high.iloc[-250:].max())
            prev_20_high = float(high.iloc[-21:-1].max())
            is_breakout = (curr > prev_20_high) and (close.iloc[-2] < prev_20_high)
            
            setup, reason = "", ""
            # 高窄旗型
            rally = (high.iloc[-60:].max() - close.iloc[-60:].min())/close.iloc[-60:].min()
            if rally > 0.8 and (year_high-curr)/year_high < 0.25 and is_breakout:
                setup, reason = "🚀 高窄旗型", "飆漲動能突破"
            # 買進跳空
            elif (open_p.iloc[-1] - close.iloc[-2])/close.iloc[-2] > 0.08:
                setup, reason = "🕳️ 買進跳空", "強力消息缺口"
            # VCP 突破
            elif is_breakout and (year_high - curr)/year_high < 0.15:
                setup, reason = "📦 VCP突破", "整理區帶量突破"

            if setup:
                return {"代號": ticker, "名稱": name, "現價": round(curr, 2), "型態": setup, "RS": round(rs_rating, 1), "建議買價": round(prev_20_high, 2), "買入原因": reason}
            return None
        except: return None

    def analyze_drive(self, item, df, bench_roc):
        """全量移植 DRIVE 深度評分"""
        try:
            close = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
            high = df['High'].iloc[:, 0] if isinstance(df['High'], pd.DataFrame) else df['High']
            low = df['Low'].iloc[:, 0] if isinstance(df['Low'], pd.DataFrame) else df['Low']
            vol = df['Volume'].iloc[:, 0] if isinstance(df['Volume'], pd.DataFrame) else df['Volume']
            
            curr, avg_vol = float(close.iloc[-1]), float(vol.rolling(20).mean().iloc[-1])
            if curr < self.min_price or avg_vol < self.min_volume_drive: return None
            
            ma50, ma200 = float(close.rolling(50).mean().iloc[-1]), float(close.rolling(200).mean().iloc[-1])
            year_high, year_low = float(high.iloc[-250:].max()), float(low.iloc[-250:].min())
            if not (curr > ma50 > ma200 and (year_high - curr)/year_high < 0.25): return None

            stock_roc = float(close.pct_change(self.rs_period_drive).iloc[-1])
            rs_rating = (stock_roc - bench_roc) * 100
            if rs_rating < 5: return None

            # MVP 邏輯：15天內收紅>=9天 + 成交量比前段放大
            up_days = (close.iloc[-16:-1].diff() > 0).sum()
            vol_ratio = vol.iloc[-16:-1].mean() / vol.iloc[-31:-16].mean()
            is_mvp = up_days >= 9 and vol_ratio >= 1.2
            
            score, comments = 0, []
            prev_20_high = float(close.iloc[-21:-1].max())
            if curr > prev_20_high and vol.iloc[-1] > avg_vol * 1.3:
                score += 50; comments.append("樞紐突破")
            if is_mvp: score += 30; comments.append("🔥MVP吸籌")
            if rs_rating > 30: score += 20; comments.append("超強RS")

            if score >= 30:
                return {"代號": item['ticker'], "名稱": item['name'], "產業": item['industry'], "評分": score, "RS": round(rs_rating, 1), "吸籌特徵": " + ".join(comments)}
            return None
        except: return None

    def run(self):
        codes = twstock.codes
        all_stocks = [{'ticker': c+('.TW' if r.market=='上市' else '.TWO'), 'name': r.name, 'industry': r.group} for c,r in codes.items() if r.type=='股票']
        bench_c, bench_d = self.get_benchmark_roc(20), self.get_benchmark_roc(60)
        res_h, res_c, res_d = [], [], []
        print(f"🚀 全力掃描 {len(all_stocks)} 檔標的...")
        for item in tqdm(all_stocks):
            try:
                df = yf.download(item['ticker'], period='1y', progress=False, auto_adjust=True)
                if df.empty or len(df) < 200: continue
                if item['ticker'] in MY_PORTFOLIO:
                    h = self.health_check_logic(item['ticker'], item['name'], MY_PORTFOLIO[item['ticker']], df)
                    if h: res_h.append(h)
                c = self.analyze_chose(item['ticker'], item['name'], df, bench_c)
                if c: res_c.append(c)
                d = self.analyze_drive(item, df, bench_d)
                if d: res_d.append(d)
            except: continue
        return res_h, res_c, res_d


# ==========================================
# 📊 策略回測引擎 (100% 同步進出場邏輯)
# ==========================================
def backtest_3y_strategy(ticker, bench_roc_series):
    try:
        # 抓取 4 年數據確保計算 MA200 無誤
        df = yf.download(ticker, period='4y', progress=False, auto_adjust=True)
        if df.empty or len(df) < 300: return 0, 0
        
        c_series = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
        h_series = df['High'].iloc[:, 0] if isinstance(df['High'], pd.DataFrame) else df['High']
        l_series = df['Low'].iloc[:, 0] if isinstance(df['Low'], pd.DataFrame) else df['Low']
        o_series = df['Open'].iloc[:, 0] if isinstance(df['Open'], pd.DataFrame) else df['Open']
        v_series = df['Volume'].iloc[:, 0] if isinstance(df['Volume'], pd.DataFrame) else df['Volume']

        ma10 = c_series.rolling(10).mean()
        ma20 = c_series.rolling(20).mean()
        ma50 = c_series.rolling(50).mean()
        ma200 = c_series.rolling(200).mean()
        avg_vol_20 = v_series.rolling(20).mean()
        
        trades = []
        in_pos = False
        entry_p = 0
        init_stop_pct = 0.07 

        # 模擬過去 3 年的每日交易
        start_idx = len(df) - 750
        for i in range(start_idx, len(df)):
            curr_c = float(c_series.iloc[i])
            dt = df.index[i]
            
            if not in_pos:
                # --- 進場：analyze_chose 邏輯 ---
                if curr_c < 20 or avg_vol_20.iloc[i] < 800000: continue
                if not (curr_c > ma50.iloc[i] > ma200.iloc[i]): continue
                
                s_roc = float(c_series.iloc[i] / c_series.iloc[i-20] - 1)
                if (s_roc - bench_roc_series.get(dt, 0)) < 0: continue
                
                y_high = float(h_series.iloc[i-250:i].max())
                p20_high = float(h_series.iloc[i-21:i].max())
                is_break = (curr_c > p20_high) and (c_series.iloc[i-1] < p20_high)
                
                rally = (h_series.iloc[i-60:i].max() - c_series.iloc[i-60:i].min()) / c_series.iloc[i-60:i].min()
                is_flag = rally > 0.8 and (y_high - curr_c)/y_high < 0.25 and is_break
                is_gap = (o_series.iloc[i] - c_series.iloc[i-1])/c_series.iloc[i-1] > 0.08
                is_vcp = is_break and (y_high - curr_c)/y_high < 0.15
                
                if is_flag or is_gap or is_vcp:
                    entry_p = curr_c
                    in_pos = True
            
            elif in_pos:
                # --- 出場：health_check_logic 邏輯 ---
                r_mult = (curr_c - entry_p) / (entry_p * init_stop_pct)
                is_super = (c_series.iloc[i-34:i+1] > ma10.iloc[i-34:i+1]).all()
                check_ma = ma10.iloc[i] if is_super else ma20.iloc[i]
                
                exit_now = False
                if curr_c < entry_p * (1 - init_stop_pct): exit_now = True
                elif r_mult >= 2 and curr_c < entry_p: exit_now = True
                elif curr_c < check_ma: exit_now = True
                
                if exit_now:
                    trades.append((curr_c - entry_p) / entry_p)
                    in_pos = False
        
        if not trades: return 0, 0
        wr = len([t for t in trades if t > 0]) / len(trades) * 100
        tr = (np.prod([1 + t for t in trades]) - 1) * 100
        return round(wr, 1), round(tr, 1)
    except: return 0, 0
        
# ==========================================
# 📧 郵件發送與 AI 深度診斷文字引擎
# ==========================================
def generate_ai_diagnostic(row_c, row_d, df, bench_series):
    """
    根據量化數據產出 AI 深度點評文字
    包含：原始診斷、精確停損、3年同步回測、績優生標記
    """
    try:
        # 確保數據不為空且列名正確
        close = df['Close'].iloc[:, 0] if isinstance(df['Close'], pd.DataFrame) else df['Close']
        
        # 1. 計算各類停損價格 (修正變數名稱)
        buy_price = row_c['建議買價']
        init_stop = round(buy_price * 0.93, 2)  # 初始停損設為 -7%
        ma10 = round(float(close.rolling(10).mean().iloc[-1]), 2)
        ma20 = round(float(close.rolling(20).mean().iloc[-1]), 2)
        
        # 2. 執行 3 年同步回測
        win_rate, cumulative_ret = backtest_3y_strategy(row_c['代號'], bench_series)
        
        # 3. 標記與防護邏輯
        star_tag = "<b style='color:#f1c40f;'>🌟 歷史績優生</b>" if win_rate >= 60 and cumulative_ret > 50 else ""
        is_super = (close.iloc[-35:] > close.rolling(10).mean().iloc[-35:]).all()
        
        defense_ma_name = "10MA" if is_super else "20MA"
        defense_ma_val = ma10 if is_super else ma20

        # 4. 組合 HTML 文字
        diagnostic = (
            f"<b>【{row_c['名稱']} ({row_c['代號'].split('.')[0]})】</b> {star_tag}<br>"
            f"➡️ <b>診斷結論：</b> 該股觸發了 <b>{row_c['型態']}</b>，顯示出極強的買入契機。其 DRIVE 綜合評分高達 <b>{row_d['評分']} 分</b>，"
            f"RS 強度達 <b>{row_d['RS']}</b>，不僅強於大盤，更是 {row_d['產業']} 板塊中的領頭羊。<br>"
            f"📊 <b>策略回測 (3Y)：</b> 勝率 <b style='color:#27ae60;'>{win_rate}%</b> | 總報酬 <b style='color:#27ae60;'>{cumulative_ret}%</b><br>"
            f"✅ <b>技術特徵：</b> 具備 <b>{row_d['吸籌特徵']}</b>，大戶吸籌跡象明顯。<br>"
            f"📍 <b>佈局建議：</b> 建議在 <b>{buy_price}</b> 附近分批佈局。<br>"
            f"🛡️ <b>風險控管 (停損預估)：</b><br>"
            f"• 初始防禦 (觸發即撤)：<b>{init_stop}</b><br>"
            f"• 強勢持有線 (10MA)：<b>{ma10}</b><br>"
            f"• 最後防線 (20MA)：<b>{ma20}</b><br>"
            f"💡 <b>當前防守重點：</b> 建議盯住 <b>{defense_ma_name} ({defense_ma_val})</b><br><br>"
            f"<hr style='border:0.5px dashed #ddd;'>"
        )
        return diagnostic
    except Exception as e:
        # 這裡打印錯誤，可以在 GitHub Actions 的 Log 中看到具體原因
        print(f"Error analyzing {row_c['名稱']}: {e}")
        return f"【{row_c['名稱']}】數據解析異常，跳過診斷。<br>"

def send_email(h, c, d):
    df_h, df_c, df_d = pd.DataFrame(h), pd.DataFrame(c), pd.DataFrame(d)

    # --- 準備大盤數據字典用於回測 ---
    print("正在準備回測大盤數據...")
    bench_df = yf.download('0050.TW', period='4y', progress=False, auto_adjust=True)
    bench_close = bench_df['Close'].iloc[:, 0] if isinstance(bench_df['Close'], pd.DataFrame) else bench_df['Close']
    bench_series = bench_close.pct_change(20).to_dict()

    # 產業分析與雙重認證個股
    top_ind = df_d['產業'].value_counts().head(3).index.tolist() if not df_d.empty else []
    ai_section = ""
    if not df_c.empty and not df_d.empty:
        inter_ids = list(set(df_c['代號']) & set(df_d['代號']))
        for tid in inter_ids:
            row_c = df_c[df_c['代號'] == tid].iloc[0]
            row_d = df_d[df_d['代號'] == tid].iloc[0]

            # 抓取較長的時間段以滿足回測需求 (3年回測需要4年數據以供MA計算)
            df_temp = yf.download(tid, period='4y', progress=False, auto_adjust=True)
            # 傳入正確的參數
            ai_section += generate_ai_diagnostic(row_c, row_d, df_temp, bench_series)

    style = """
    <style>
        body { font-family: sans-serif; line-height: 1.6; color: #333; }
        .title { background: #2c3e50; color: white; padding: 12px; margin-top: 25px; font-weight: bold; border-radius: 5px; }
        .ai-box { background: #fffcf0; border: 1px solid #f1c40f; border-left: 6px solid #f1c40f; padding: 15px; margin: 15px 0; font-size: 14px; color: #7f8c8d; }
        .table { border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 20px; }
        .table th, .table td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        .table th { background-color: #f8f9fa; }
    </style>
    """
    
    html = f"<html><head>{style}</head><body>"
    html += f"<h2>📈 台股動能投資策略報告 ({pd.Timestamp.now().strftime('%Y-%m-%d')})</h2>"
    html += f"<p>💰 本日主流板塊：{', '.join(top_ind)}</p>"
    
    html += "<div class='title'>1. 🏥 庫存健檢 (考特賣出法則)</div>"
    html += df_h.to_html(classes='table', index=False) if not df_h.empty else "<p>無庫存資料</p>"

    html += "<div class='title' style='background:#8e44ad;'>4. 💎 雙重認證個股深度分析 (AI 診斷)</div>"
    if ai_section:
        html += f"<div class='ai-box'>{ai_section}</div>"
    else:
        html += "<div class='ai-box'>今日無雙重認證標的，大盤可能處於盤整期，請謹慎持倉。</div>"

    html += "<div class='title'>2. 🚀 買入型態掃描 (CHOSE)</div>"
    html += df_c.to_html(classes='table', index=False) if not df_c.empty else "<p>今日無符合標的</p>"

    html += "<div class='title'>3. 👑 大戶動能評分 (DRIVE)</div>"
    html += df_d.to_html(classes='table', index=False) if not df_d.empty else "<p>今日無高動能標的</p>"
    
    html += "</body></html>"

    msg = MIMEMultipart(); msg['Subject'] = f"台股策略報告 - {pd.Timestamp.now().strftime('%Y-%m-%d')}"
    msg['From'], msg['To'] = GMAIL_USER, RECEIVER_EMAIL
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.send_message(msg)

if __name__ == "__main__":
    system = StockSystem()
    h, c, d = system.run()

    send_email(h, c, d); print("Done!")



