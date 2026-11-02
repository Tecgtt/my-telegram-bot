---
title: Telegram Bot
emoji: 🎬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 🎬 All-in-One Telegram Video & Audio (MP3) Downloader Bot

एक शक्तिशाली और आसान टेलीग्राम बॉट जिससे आप **YouTube**, **Instagram Reels**, और **Facebook Videos** को केवल उनका लिंक भेजकर सीधे टेलीग्राम पर **Video (MP4)** या **Audio (MP3)** में डाउनलोड कर सकते हैं।

---

## 👑 Admin Panel & Tracking (नया फीचर)
बॉट में एक संपूर्ण **एडमिन कंट्रोल पैनल** और **डेटाबेस ट्रैकिंग सिस्टम (SQLite)** शामिल है:
- **एडमिन कमांड:** `/admin` (केवल `@yqios` के लिए उपलब्ध)
- **लाइव अलर्ट (Real-Time Notification):** जब भी कोई यूज़र वीडियो या MP3 डाउनलोड करेगा, एडमिन को तुरंत टेलीग्राम पर अलर्ट मैसेज मिलेगा (यूज़र का नाम, यूज़रनेम, वीडियो का नाम और साइज़ सहित)।
- **डैशबोर्ड आँकड़े:** कुल यूज़र्स, कुल डाउनलोड्स (Video vs MP3), कुल डेटा ट्रांसफर, और आज के नए डाउनलोड्स।
- **यूज़र्स लिस्ट व हिस्ट्री:** हालिया सक्रिय यूज़र्स और उनके द्वारा डाउनलोड किए गए लिंक्स का रिकॉर्ड।
- **डेटाबेस बैकअप:** 1-क्लिक में पूरी SQLite `.db` फ़ाइल डाउनलोड करने का विकल्प।

---

## 📞 Support & Contact Info
- **Telegram:** [@yqios](https://t.me/yqios)
- **WhatsApp:** [+917015346487](https://wa.me/917015346487)

---

## 🚀 बॉट चलाने का तरीका

```bash
cd /Users/mac/.gemini/antigravity/scratch/telegram_video_bot
./run_bot.sh
```
