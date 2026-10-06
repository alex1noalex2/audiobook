# Аудиокниги

Лёгкое веб-приложение для телефона: загружаешь книгу (PDF, EPUB, TXT) на русском
или румынском — оно озвучивает её голосами Google Chirp 3 HD и сохраняет аудио на телефоне, чтобы слушать без интернета и с выключенным экраном.

## Как устроено

- `index.html`, `app.js` — библиотека и плеер (позиция, скорость, экран блокировки).
- `extract.js` — текст из PDF (pdf.js) / EPUB (JSZip) / TXT, нарезка на куски ≤1500 символов.
- `store.js` — IndexedDB: книги и готовое MP3 по кускам.
- `sw.js` — кэш оболочки, чтобы приложение открывалось офлайн.
- `api/tts.py` — функция Vercel: `POST /api/tts {text, voice}` → MP3 через Google Cloud Text-to-Speech.

Голоса: Chirp 3 HD Aoede (женский) и Charon (мужской) для ru-RU и ro-RO.

## Настройка

В Vercel → Settings → Environment Variables добавить `GOOGLE_TTS_KEY` —
ключ API Google Cloud, ограниченный только Cloud Text-to-Speech API.
Бесплатно 1 млн символов Chirp 3 HD в месяц (≈ 2 книги), дальше ≈ $30 за 1 млн.

## Выкладка

```
vercel deploy --prod
```

## Тест

```
sh tests/run.sh
```

Браузерный тест (Playwright) на сгенерированных PDF и EPUB; голоса Google
подменены заглушкой. Нужны python3 с reportlab, ffmpeg и Chromium.

## Ограничения

- Сверх бесплатного лимита Google берёт деньги, жёсткого «стоп» нет — только
  оповещение бюджета в Google Cloud Billing.
- Сканы PDF (картинки страниц) без распознавания текста не читаются.

## Озвучка на своём Mac (OmniVoice, бесплатно)

```
sh local/setup.sh книга.epub                       # установка + проверка на 3 кусках
.venv/bin/python local/book2audio.py книга.epub    # вся книга -> книга.mp3
```

Один голос на всю книгу: без образца модель берёт новый случайный голос для каждого куска.
```
.venv/bin/python local/book2audio.py --voices 8                       # 8 голосов читают одну фразу
.venv/bin/python local/book2audio.py книга.epub --ref voices/voice_03.wav
```
Свой голос: `--ref голос.wav --ref-text "точный текст записи"` (до 10 секунд).
Прерванный запуск продолжается с того же места.
