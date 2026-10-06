import { chromium } from 'playwright';
const S = process.argv[2] || process.cwd(); // где лежат фикстуры и node_modules
const libs = {
  'pdf.min.js': S + '/node_modules/pdfjs-dist/build/pdf.min.js',
  'pdf.worker.min.js': S + '/node_modules/pdfjs-dist/build/pdf.worker.min.js',
  'jszip.min.js': S + '/node_modules/jszip/dist/jszip.min.js',
};
let fails = 0;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) fails++; };
const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const ctx = await browser.newContext();
await ctx.route('https://cdnjs.cloudflare.com/**', r => r.fulfill({ path: libs[r.request().url().split('/').pop()], contentType: 'text/javascript', headers: { 'access-control-allow-origin': '*' } }));
const page = await ctx.newPage();
page.on('pageerror', e => { console.log('PAGEERROR', e.message); fails++; });
await page.goto('http://127.0.0.1:8765/');
const status = () => page.textContent('#status');
const part = () => page.textContent('#part');

// PDF, русский
await page.setInputFiles('#file', S + '/ru.pdf');
await page.waitForSelector('#player:not([hidden])');
const text = await page.textContent('#text');
ok(text.startsWith('Глава 1'), 'PDF: текст начинается с «Глава 1»');
ok(text.includes('переносом') && !text.includes('перено-'), 'PDF: перенос слова склеен');
ok(!/\n\s*1\s*\n/.test(text), 'PDF: номер страницы выброшен');
ok(await page.inputValue('#voice') === 'ru-RU-SvetlanaNeural', 'PDF: язык ru → Светлана');
const total = +(await part()).match(/из (\d+)/)[1];
ok(total >= 2, `PDF: ${total} частей`);
const bad = await page.evaluate(() => fetch('/api/tts', { method: 'POST', body: JSON.stringify({ text: 'x', voice: 'evil' }) }).then(r => r.status));
ok(bad === 400, 'API: чужой голос отклонён (400)');

// Проигрывание и автопереход
await page.selectOption('#rate', '2');
await page.click('#play');
await page.waitForFunction(() => !document.getElementById('audio').paused, null, { timeout: 5000 });
ok(true, 'Плеер играет');
await page.waitForFunction(() => document.getElementById('part').textContent.startsWith('Часть 2'), null, { timeout: 10000 });
ok(true, 'После конца части сам перешёл на часть 2');
await page.click('#play'); // пауза → сохраняет позицию

// Перезагрузка — позиция и скорость на месте
await page.reload();
await page.waitForSelector('#books li');
ok((await page.textContent('#books li')).includes('ru'), 'Библиотека: книга сохранилась после перезагрузки');
await page.click('#books li');
await page.waitForSelector('#player:not([hidden])');
ok((await part()).startsWith('Часть 2'), 'Позиция восстановлена (часть 2)');
ok(await page.inputValue('#rate') === '2', 'Скорость запомнена');

// Скачать всю книгу
await page.click('#download');
await page.waitForFunction(() => document.getElementById('status').textContent.includes('целиком'), null, { timeout: 15000 });
ok(true, 'Скачивание: вся книга на телефоне');

// Офлайн: приложение открывается, скачанная книга играет
await page.evaluate(() => navigator.serviceWorker.ready);
await page.reload(); // чтобы SW контролировал страницу
await ctx.setOffline(true);
await page.reload();
await page.waitForSelector('#books li');
ok(true, 'Офлайн: приложение открылось');
await page.click('#books li');
await page.waitForSelector('#player:not([hidden])');
await page.click('#next');
await page.click('#play');
await page.waitForFunction(() => !document.getElementById('audio').paused, null, { timeout: 5000 });
ok(true, 'Офлайн: скачанная часть играет');
await page.click('#play');

// Офлайн: EPUB добавляется, но неозвученная часть честно говорит, что нет интернета
await page.click('#back');
await page.setInputFiles('#file', S + '/ro.epub');
await page.waitForSelector('#player:not([hidden])');
const et = await page.textContent('#text');
ok(et.startsWith('Capitolul unu') && !et.includes('Capitolul doi'), 'EPUB: главы в порядке spine');
ok(await page.inputValue('#voice') === 'ro-RO-AlinaNeural', 'EPUB: язык ro → Alina');
await page.waitForFunction(() => document.getElementById('status').textContent.includes('Нет интернета'), null, { timeout: 5000 });
ok(true, 'Офлайн: понятное сообщение для нескачанной части');
await ctx.setOffline(false);

// Смена голоса — новая озвучка
await page.selectOption('#voice', 'ro-RO-EmilNeural');
await page.waitForFunction(() => document.getElementById('status').textContent === '', null, { timeout: 5000 });
ok((await part()).includes('скачано'), 'Смена голоса работает');

// Удаление в два нажатия
await page.click('#delete');
ok(await page.isVisible('#player'), 'Удаление: первое нажатие только предупреждает');
await page.click('#delete');
await page.waitForSelector('#library:not([hidden])');
await page.waitForTimeout(300);
const titles = await page.$$eval('#books li b', l => l.map(x => x.textContent));
ok(titles.length === 1 && titles[0] === 'ru', 'Удаление: осталась только ru');
await page.reload();
await page.waitForSelector('#books li');
ok((await page.$$('#books li')).length === 1, 'Удаление: после перезагрузки книга не воскресла');

await browser.close();
console.log(fails ? `ИТОГО ОШИБОК: ${fails}` : 'ВСЁ ПРОШЛО');
process.exit(fails ? 1 : 0);
