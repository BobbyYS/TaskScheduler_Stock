import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import io
from contextlib import redirect_stdout

# 導入你的三個腳本功能 (假設你已將原檔放在同層目錄)
# 注意：需將原檔中的執行部分 (if __name__ == "__main__":) 稍微修改或確保能被 import
import health
import chose
import drive

def run_and_capture(func, *args):
    f = io.StringIO()
    with redirect_stdout(f):
        func(*args)
    return f.getvalue()

def send_email(content):
    sender = os.environ['GMAIL_USER']
    password = os.environ['GMAIL_APP_PASSWORD']
    receiver = os.environ['RECEIVER_EMAIL']

    msg = MIMEMultipart()
    msg['Subject'] = "📈 每日台股策略與健檢報告"
    msg['From'] = sender
    msg['To'] = receiver

    # 將內容包裝在 <pre> 標籤中保持表格格式
    html_content = f"""
    <html>
      <body style="font-family: monospace;">
        <h2>📊 台股自動化分析報告</h2>
        <pre>{content}</pre>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_content, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(sender, password)
        server.send_message(msg)

if __name__ == "__main__":
    report = ""
    
    print("Executing Health Check...")
    report += "=== 🏥 庫存健檢報告 ===\n"
    # 傳入你在 health.py 定義的 portfolio
    report += run_and_capture(health.health_check, health.MY_PORTFOLIO) 
    
    print("Executing Chose Scan...")
    report += "\n=== 🚀 黃金買點掃描 ===\n"
    report += run_and_capture(chose.run_screening)
    
    print("Executing DRIVE Scan...")
    report += "\n=== 👑 DRIVE 終極模型 ===\n"
    report += run_and_capture(drive.run_drive_full_scan)

    print("Sending Email...")
    send_email(report)