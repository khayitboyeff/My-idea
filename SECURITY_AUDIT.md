# CyberAI Pro — Security Audit

## 30 bandli passiv tekshiruv

Loyiha papkasida terminal/CMD ochib ishga tushiring:

```bat
python security.py
```

Boshqa loyiha papkasini tekshirish:

```bat
python security.py C:\CyberAI_Pro
```

O'zingiz boshqaradigan lokal serverning HTTP sarlavhalarini ham tekshirish:

```bat
python security.py . --url http://127.0.0.1:5000
```

Skript hujum payloadlari yubormaydi. U kod/configuration belgilarini tekshiradi, shuning uchun natija professional penetration test yoki xavfsizlik kafolati emas.

## Login bloklash

- Username bo'yicha 15 daqiqalik oynada 3 ta noto'g'ri paroldan keyin 15 daqiqaga vaqtincha bloklaydi.
- Urinishning IP manzili `security_login_log` jadvalida saqlanadi.
- Muvaffaqiyatli login hisoblagichni tozalaydi; bloklangan hisobni kutish muddati tugagach qayta ishlatish mumkin.
- IP `request.remote_addr` dan olinadi. Reverse proxy ishlatsangiz, faqat ishonchli proxy orqali IP uzatishni alohida sozlang; kelgan `X-Forwarded-For` ga ko'r-ko'rona ishonmang.
- Bir xil username'ni ataylab 3 marta xato kiritib, o'zingizni bloklab qo'ymang. Buni alohida test akkauntida sinang.

## Ishga tushirish

```bat
python -m pip install -r requirements.txt
python security.py
python app.py
```

## 30 banddagi WARN nimani anglatadi?

Ba'zi bandlar (masalan, parolni tiklash yoki HSTS) loyiha ichida yo'q bo'lishi mumkin. HSTS faqat HTTPS to'g'ri sozlangan production domenida yoqilishi kerak. Skript `PASS` chiqarsa ham real ekspluatatsiya, deploy konfiguratsiyasi, dependency audit va ruxsatli dinamik sinovlar o'rnini bosmaydi.
