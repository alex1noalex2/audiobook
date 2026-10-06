// IndexedDB: книги (текст по кускам + позиция) и готовое аудио по кускам.
let dbp;
function db() {
  return (dbp ??= new Promise((ok, fail) => {
    const r = indexedDB.open('audiobook', 1);
    r.onupgradeneeded = () => {
      r.result.createObjectStore('books', { keyPath: 'id' });
      r.result.createObjectStore('audio');
    };
    r.onsuccess = () => ok(r.result);
    r.onerror = () => fail(r.error);
  }));
}

async function req(store, mode, fn) {
  const tx = (await db()).transaction(store, mode);
  const r = fn(tx.objectStore(store));
  return new Promise((ok, fail) => {
    tx.oncomplete = () => ok(r?.result);
    tx.onerror = () => fail(tx.error);
  });
}

export const getBooks = () => req('books', 'readonly', s => s.getAll());
export const getBook = id => req('books', 'readonly', s => s.get(id));
export const putBook = b => req('books', 'readwrite', s => s.put(b));

const key = (id, voice, i) => `${id}|${voice}|${i}`;
export const getAudio = (id, voice, i) => req('audio', 'readonly', s => s.get(key(id, voice, i)));
export const putAudio = (id, voice, i, blob) => req('audio', 'readwrite', s => s.put(blob, key(id, voice, i)));

// Какие куски уже скачаны для этого голоса.
export async function audioKeys(id, voice) {
  const prefix = `${id}|${voice}|`;
  const keys = await req('audio', 'readonly', s => s.getAllKeys(IDBKeyRange.bound(prefix, prefix + '￿')));
  return new Set(keys.map(k => +k.slice(prefix.length)));
}

export async function deleteBook(id) {
  await req('books', 'readwrite', s => s.delete(id));
  await req('audio', 'readwrite', s => s.delete(IDBKeyRange.bound(id + '|', id + '|￿')));
}
