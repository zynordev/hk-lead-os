# HK Yazılım WhatsApp Gönderim Köprüsü

Bu klasör, `whatsclaude` projesindeki Baileys bağlı cihaz yaklaşımını kullanır. Yalnızca yerel gönderim servisi sağlar; otomatik kampanya yürütmez.

## Kurulum

```powershell
cd .\whatsapp_sender
npm install
Copy-Item .env.example .env
npm run setup
```

İlk çalıştırmada QR görünür. WhatsApp telefonunda **Bağlı Cihazlar → Cihaz Bağla** ile okut. `auth/` klasörünü paylaşma.

Varsayılan gönderim kapalıdır: `WHATSAPP_OUTBOUND_ENABLED=0`.

Kontrol:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health
```

Gönderim yalnızca outbound açık, `approved: true`, doğru approval token, geçerli telefon, açık bağlantı ve daha önce gönderilmemiş `lead_id` koşullarında gerçekleşir. Endpoint internete açılmamalı; yalnızca `127.0.0.1` üzerinde kalmalıdır.
