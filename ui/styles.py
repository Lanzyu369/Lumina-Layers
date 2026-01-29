"""
Lumina Studio - UI Styles
界面样式定义
"""

CUSTOM_CSS = """
/* Global Theme */
.gradio-container {
    max-width: 1400px !important;
    margin: auto;
}

/* Header Styling */
.header-banner {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 20px 30px;
    border-radius: 16px;
    margin-bottom: 20px;
    box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
}

.header-banner h1 {
    color: white !important;
    font-size: 2.5em !important;
    margin: 0 !important;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
}

.header-banner p {
    color: rgba(255,255,255,0.9) !important;
    margin: 5px 0 0 0 !important;
}

/* Stats Bar */
.stats-bar {
    background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
    padding: 12px 20px;
    border-radius: 10px;
    color: #a0a0ff;
    font-family: 'Courier New', monospace;
    text-align: center;
    margin-bottom: 15px;
}

.stats-bar strong {
    color: #a0a0ff;
}

/* Tab Styling */
.tab-nav button {
    font-size: 1.1em !important;
    padding: 12px 24px !important;
    border-radius: 10px 10px 0 0 !important;
}

.tab-nav button.selected {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    color: white !important;
}

/* Card Styling */
.input-card, .output-card {
    background: #fafafa;
    border-radius: 12px;
    padding: 15px;
    border: 1px solid #e0e0e0;
}

/* Button Styling */
.primary-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    font-size: 1.1em !important;
    padding: 12px 24px !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4) !important;
}

.primary-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5) !important;
}

/* Mode indicator */
.mode-indicator {
    background: #f0f0ff;
    border: 2px solid #667eea;
    border-radius: 8px;
    padding: 10px;
    margin: 10px 0;
    font-weight: bold;
}

/* Language Indicator */
.lang-indicator {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 5px 15px;
    border-radius: 20px;
    font-weight: bold;
}

/* Footer */
.footer {
    text-align: center;
    padding: 20px;
    color: #888;
    font-size: 0.9em;
}

/* 彻底隐藏定位点图上的所有功能按钮 */
.no-clear-btn .built-in-buttons,
.no-clear-btn .button-group {
    display: none !important;
}
"""
