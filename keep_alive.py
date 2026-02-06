"""
Keep Alive Script for Heroku
Prevents dyno from sleeping
"""
from flask import Flask, render_template_string
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Telegram Reporting Bot</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
            padding: 50px;
            margin: 0;
            min-height: 100vh;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255,255,255,0.1);
            padding: 40px;
            border-radius: 20px;
            backdrop-filter: blur(10px);
        }
        h1 { font-size: 3em; margin-bottom: 20px; }
        .status { font-size: 1.5em; margin: 30px 0; }
        .features {
            text-align: left;
            margin: 30px 0;
            padding: 20px;
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
        }
        .features h3 { margin-top: 0; }
        .features ul { list-style: none; padding: 0; }
        .features li { padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.2); }
        .features li:last-child { border-bottom: none; }
        .check { color: #00ff88; margin-right: 10px; }
        .footer { margin-top: 40px; font-size: 0.9em; opacity: 0.8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Telegram Reporting Bot</h1>
        <div class="status">✅ Bot is Running</div>
        <div class="features">
            <h3>🚀 Features:</h3>
            <ul>
                <li><span class="check">✓</span> Multi-Account Reporting</li>
                <li><span class="check">✓</span> Live Progress Tracking</li>
                <li><span class="check">✓</span> Force Subscribe System</li>
                <li><span class="check">✓</span> Sudo User Management</li>
                <li><span class="check">✓</span> Secure ID Storage</li>
                <li><span class="check">✓</span> Real-time Status Panel</li>
            </ul>
        </div>
        <div class="footer">
            <p>Premium Multi-Account Reporting System</p>
            <p>Powered by TDLib</p>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/health')
def health():
    return {"status": "ok", "service": "reporting-bot"}

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    logger.info("Starting keep-alive server...")
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()
    logger.info("Keep-alive server started on port 8080")

if __name__ == "__main__":
    keep_alive()
