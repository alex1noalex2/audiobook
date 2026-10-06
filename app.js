import { extractText, toChunks, detectLang } from './extract.js';
import * as store from './store.js';

const VOICES = {
  ru: [['ru-RU-Chirp3-HD-Aoede', 'Русский · женский'], ['ru-RU-Chirp3-HD-Charon', 'Русский · мужской']],
  ro: [['ro-RO-Chirp3-HD-Aoede', 'Română · feminin'], ['ro-RO-Chirp3-HD-Charon', 'Română · masculin']],
};
const $ = id => document.getElementById(id);
const audio = $('audio');
let book = null;   // открытая книга
let idx = 0;       // текущий кусок
let ready = new Set(); // куски, уже лежащие на телефоне
let downloading = false;
let url = null;

const status = msg => ($('status').textContent = msg || '');
const pref = (k, v) => { try { return v === undefined ? localStorage.getItem(k) : localStorage.setItem(k, v); } catch { return null; } };

// ---------- библиотека ----------
async function renderLibrary() {
  const books = (await store.getBooks()).sort((a, b) => b.opened - a.opened);
  $('books').replaceChildren(...books.map(b => {
    const li = document.createElement('li');
    const pct = Math.round((b.pos.i / b.chunks.length) * 100);
    li.innerHTML = `<b></b><small>${pct}% · ${b.chunks.length} частей</small>`;
    li.querySelector('b').textContent = b.title;
    li.onclick = () => openBook(b.id);
    return li;
  }));
}

$('file').onchange = async e => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  const hint = $('library').querySelector('.hint');
  const old = hint.textContent;
  hint.textContent = 'Читаю книгу…';
  try {
    const text = await extractText(file);
    const chunks = toChunks(text);
    if (!chunks.length) throw new Error('В файле нет текста (возможно, это скан — такие пока не поддерживаются)');
    const lang = detectLang(text);
    const id = `${file.name}-${file.size}`;
    await store.putBook({
      id, title: file.name.replace(/\.[^.]+$/, ''), chunks, lang,
      voice: VOICES[lang][0][0], pos: { i: 0, t: 0 }, opened: Date.now(),
    });
    hint.textContent = old;
    openBook(id);
  } catch (err) {
    hint.textContent = 'Ошибка: ' + err.message;
  }
};

// ---------- плеер ----------
async function openBook(id) {
  book = await store.getBook(id);
  book.opened = Date.now();
  store.putBook(book);
  idx = book.pos.i;
  ready = await store.audioKeys(book.id, book.voice);
  $('library').hidden = true;
  $('player').hidden = false;
  $('title').textContent = book.title;
  $('voice').replaceChildren(...Object.values(VOICES).flat().map(([v, name]) => new Option(name, v, false, v === book.voice)));
  $('seek').max = book.chunks.length - 1;
  status('');
  showPart();
  await load(idx, book.pos.t);
}

function showPart() {
  $('part').textContent = `Часть ${idx + 1} из ${book.chunks.length} · скачано ${ready.size}`;
  $('seek').value = idx;
  $('text').textContent = book.chunks[idx];
}

async function fetchChunk(i, voice = book.voice, b = book) {
  const cached = await store.getAudio(b.id, voice, i);
  if (cached) return cached;
  for (let attempt = 0; ; attempt++) {
    try {
      const r = await fetch('/api/tts', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: b.chunks[i], voice }),
      });
      if (!r.ok) throw new Error(`сервер ответил ${r.status}`);
      const blob = await r.blob();
      await store.putAudio(b.id, voice, i, blob);
      if (b === book && voice === book.voice) { ready.add(i); showPart(); }
      return blob;
    } catch (err) {
      if (!navigator.onLine) throw new Error('Нет интернета, а эта часть ещё не скачана');
      if (attempt >= 2) throw err;
      await new Promise(r => setTimeout(r, 1500 * (attempt + 1)));
    }
  }
}

// Загружает кусок i в плеер; играет, если autoplay.
async function load(i, t = 0, autoplay = false) {
  idx = Math.max(0, Math.min(i, book.chunks.length - 1));
  showPart();
  status(ready.has(idx) ? '' : 'Озвучиваю…');
  let blob;
  try { blob = await fetchChunk(idx); } catch (err) { status('Ошибка: ' + err.message); return; }
  if (i !== idx) return; // пока грузили, пользователь ушёл на другой кусок
  status('');
  if (url) URL.revokeObjectURL(url);
  url = URL.createObjectURL(blob);
  audio.src = url;
  audio.playbackRate = +$('rate').value;
  if (t) audio.addEventListener('loadedmetadata', () => (audio.currentTime = t), { once: true });
  if (autoplay) audio.play().catch(() => {});
  savePos();
  // заранее готовим следующие две части, чтобы не было пауз
  for (const n of [idx + 1, idx + 2]) if (n < book.chunks.length && !ready.has(n)) fetchChunk(n).catch(() => {});
}

function savePos() {
  if (!book) return;
  book.pos = { i: idx, t: audio.currentTime || 0 };
  store.putBook(book);
}

audio.onplay = () => { $('play').textContent = '⏸'; setMediaSession(); };
audio.onpause = () => { $('play').textContent = '▶'; savePos(); };
audio.onended = () => { if (idx + 1 < book.chunks.length) load(idx + 1, 0, true); else status('Книга дочитана'); };
setInterval(() => { if (!audio.paused) savePos(); }, 5000);

$('play').onclick = () => (audio.paused ? (audio.src ? audio.play() : load(idx, 0, true)) : audio.pause());
const skip = s => {
  const t = audio.currentTime + s;
  if (t < 0 && idx > 0) return load(idx - 1, 0, !audio.paused);
  if (t > audio.duration && idx + 1 < book.chunks.length) return load(idx + 1, 0, !audio.paused);
  audio.currentTime = Math.max(0, t);
};
$('rew').onclick = () => skip(-15);
$('fwd').onclick = () => skip(30);
$('prev').onclick = () => load(idx - 1, 0, !audio.paused);
$('next').onclick = () => load(idx + 1, 0, !audio.paused);
$('seek').onchange = () => load(+$('seek').value, 0, !audio.paused);

$('rate').value = pref('rate') || '1';
$('rate').onchange = () => { audio.playbackRate = +$('rate').value; pref('rate', $('rate').value); };

$('voice').onchange = async () => {
  book.voice = $('voice').value;
  ready = await store.audioKeys(book.id, book.voice);
  savePos();
  load(idx, 0, !audio.paused);
};

$('download').onclick = async () => {
  if (downloading) { downloading = false; return; }
  downloading = true;
  const b = book, voice = book.voice;
  const todo = b.chunks.map((_, i) => i).filter(i => !ready.has(i));
  const bar = $('dlbar');
  bar.hidden = false; bar.max = b.chunks.length;
  $('download').textContent = 'Остановить скачивание';
  if ('storage' in navigator) navigator.storage.persist?.();
  let failed = 0;
  const worker = async () => {
    while (downloading && todo.length && book === b) {
      try { await fetchChunk(todo.shift(), voice, b); } catch { failed++; }
      bar.value = ready.size;
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  downloading = false;
  bar.hidden = true;
  $('download').textContent = 'Скачать всю книгу для офлайн';
  if (book === b) status(failed ? `Не скачалось частей: ${failed}. Нажмите ещё раз, чтобы докачать.`
    : ready.size === b.chunks.length ? 'Книга целиком на телефоне — можно слушать без интернета' : '');
};

// Удаление в два нажатия — confirm() во встроенных браузерах отключён.
$('delete').onclick = async () => {
  if ($('delete').dataset.armed !== '1') {
    $('delete').dataset.armed = '1';
    $('delete').textContent = 'Нажмите ещё раз, чтобы удалить';
    setTimeout(() => { $('delete').dataset.armed = ''; $('delete').textContent = 'Удалить книгу'; }, 4000);
    return;
  }
  const id = book.id;
  book = null; // иначе событие pause успеет сохранить книгу обратно
  audio.pause();
  await store.deleteBook(id);
  closeBook();
};

function closeBook() {
  savePos();
  audio.pause();
  downloading = false;
  book = null;
  $('player').hidden = true;
  $('library').hidden = false;
  renderLibrary();
}
$('back').onclick = closeBook;

// Управление с экрана блокировки / наушников
function setMediaSession() {
  if (!('mediaSession' in navigator) || !book) return;
  navigator.mediaSession.metadata = new MediaMetadata({ title: book.title, artist: `Часть ${idx + 1} из ${book.chunks.length}` });
  const h = {
    play: () => audio.play(), pause: () => audio.pause(),
    seekbackward: () => skip(-15), seekforward: () => skip(30),
    previoustrack: () => load(idx - 1, 0, true), nexttrack: () => load(idx + 1, 0, true),
  };
  for (const [k, fn] of Object.entries(h)) try { navigator.mediaSession.setActionHandler(k, fn); } catch {}
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js');
renderLibrary();
