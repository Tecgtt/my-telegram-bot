#!/usr/bin/env python3
"""
Gradio entrypoint for Hugging Face Spaces to run Telegram Bot 24/7.
"""
import os
import threading
import gradio as gr
import bot

# Start Telegram Bot in background thread
bot_thread = threading.Thread(target=bot.main, daemon=True)
bot_thread.start()

def get_bot_status():
    return "✅ Telegram Video & MP3 Downloader Bot 24/7 Live hai aur successfully chal raha hai!"

demo = gr.Interface(
    fn=get_bot_status,
    inputs=[],
    outputs=gr.Textbox(label="Bot Live Status", value="✅ Online & Running 24/7"),
    title="🎬 Telegram Video Downloader Bot",
    description="Bot is actively running in background on Hugging Face 24/7.",
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
