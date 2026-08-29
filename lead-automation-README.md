# HK Yazılım Lead Automation — Gemini + Apify

Bu ilk çekirdektir: Apify Actor verisini toplar, Gemini worker'larına analiz ettirir ve çalıştırma çıktısını `lead_runs/` altında saklar. WhatsApp gönderimi bu sürümde yoktur ve hiçbir şekilde otomatik mesaj göndermez.

## Kurulum

1. Apify hesabından bir API token oluştur.
2. Token'ı PowerShell oturumunda tanımla; sohbete veya dosyaya gönderme:

```powershell
$env:APIFY_API_TOKEN = "..."
```

3. Önce güvenli dry-run:

```powershell
python .\lead_automation.py --query "kafe Samsun" --dry-run
```

4. Gerçek keşif ve 5 Gemini worker analizi:

```powershell
python .\lead_automation.py --query "kafe Samsun" --limit 20 --workers 5 --concurrency 2
```

Google Places zorunludur. Herkese açık Instagram ve web verisini eklemek için Actor input JSON dosyaları verilebilir:

```powershell
python .\lead_automation.py --query "kafe Samsun" --instagram-input .\instagram-input.json --website-input .\website-input.json
```

Instagram ve web verisi yalnızca verilen herkese açık URL/input üzerinden alınır. Scraped metin Gemini’ye talimat değil kanıt olarak etiketlenir; kişi adı, telefon ve e-posta gibi alanlar AI prompt’undan çıkarılır. Gerçek iletişim ve WhatsApp onayı sonraki aşamada yerel state/Google Sheets katmanında tutulmalıdır.

## Çıktılar

- `places.json`: Apify’den gelen ham Google Places sonuçları
- `worker_prompt.txt`: Gemini worker’larına gönderilen kanıt ve talimat
- `gemini_summary.md`: HK-Agents konsolide çıktısı

Bu çıktıların Google Sheets dashboard’una aktarılması ve WhatsApp onay kuyruğuna bağlanması sonraki aşamadır. `Approve` olmadan gönderim yapılmayacak.

## Yerel review dashboard'u

Kalıcı aday state’i ve manuel review dashboard’u artık `lead_system/` altındadır:

```powershell
python -m lead_system.run_dashboard
```

Sonra http://127.0.0.1:8790 adresini aç. Adayları içeri almak için önce bir keşif çalıştır; `lead_system/data/leads.json` dosyası deduplication ve onay durumlarını tutar. Dashboard’un WhatsApp’a gönderebilmesi için `WHATSAPP_APPROVAL_TOKEN` ortam değişkeni, WhatsApp sender’ın token’ıyla aynı olmalıdır. Outbound kapalıyken gönderim endpoint’i 423 döner.

Google Sheets senkronizasyonu için `lead_system/requirements-optional.txt` paketlerini kurup `.env.example` içindeki spreadsheet/service-account değerlerini ortam değişkeni olarak tanımla. Kimlik bilgilerini repoya koyma.

Windows Task Scheduler için hazır çalıştırıcı:

```powershell
.\run_lead_scan.ps1 -Query "kafe Samsun" -Limit 20 -Workers 5 -Concurrency 2
```

Bu script token’ı yalnızca süreç ortamında okur ve işlem sonunda temizler. Task Scheduler kaydı ayrıca elle oluşturulmalıdır; varsayılan otomatik zamanlama etkin değildir.
