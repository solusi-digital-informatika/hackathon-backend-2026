# AI Production Workflow — Backend

FastAPI, SQLAlchemy, PostgreSQL. Modul: projects, shots, brief, dan moodboards.

## Menjalankan seluruh backend dengan Docker Compose

Jalankan dari folder `backend`. File `compose.yaml` dan konfigurasi `.env` berada di folder ini:

```powershell
cd backend
# Hanya jika .env belum ada:
Copy-Item .env.example .env
# Isi AI_API_KEY, AI_VISION_MODEL, dan AI_BASE_URL di .env.
docker compose up --build -d
docker compose ps
```

Jangan menimpa `.env` yang sudah berisi konfigurasi. Tanpa konfigurasi AI, server dan
fitur CRUD tetap berjalan; endpoint analisis mengembalikan 503 `ai_not_configured`.

- Swagger: http://localhost:8000/docs
- Frontend: http://localhost:5173
- Health: http://localhost:8000/health
- PostgreSQL lokal: localhost:5435 (internal container: db:5432)
- Log: `docker compose logs -f api`
- Stop: `docker compose down` (data pada named volumes tetap disimpan)

Provider harus kompatibel dengan Chat Completions `/chat/completions`, menerima
input gambar `image_url` berupa data URL, dan mendukung `response_format: json_object`.
Gunakan model vision milik provider Anda; tidak ada mock/fallback visual di production.
Jika provider/9router berjalan di komputer host, set `AI_BASE_URL` menjadi
`http://host.docker.internal:PORT/v1`, bukan `localhost` di dalam container.
API key hanya dikirim dari server ke endpoint provider yang dikonfigurasi.

Compose menjalankan satu process API agar recovery dan scheduling job tidak ganda.
Job tersimpan dalam PostgreSQL; gambar asli dan preview tersimpan pada volume
`moodboard_data`. Job queued/running dilanjutkan setelah restart. Database dibuat
melalui `create_all` mengikuti backend awal; perubahan kolom tabel lama memerlukan
migrasi terpisah. Modul ini hanya menambahkan tabel baru.

Deployment default dibatasi ke localhost karena aplikasi belum memiliki autentikasi.

## Alur API moodboard

Prefix mengikuti API yang sudah ada: `/projects/{project_id}/moodboards`.
Semua endpoint memeriksa bahwa moodboard dan turunannya berada dalam project tersebut.

### 1. Buat project dan moodboard

`POST /projects`

```json
{"name":"Botanical Campaign"}
```

`POST /projects/{project_id}/moodboards`

```json
{"title":"Botanical Moodboard","context":"Warna dari referensi pertama; framing dari referensi kedua.","intended_use":"image"}
```

Respons memuat `id` dan `revision`. Simpan revision terbaru untuk setiap mutasi.

### 2. Upload gambar

`POST /projects/{project_id}/moodboards/{moodboard_id}/sources`

Multipart form:

- `revision`: revision moodboard terkini.
- `files`: satu atau beberapa gambar JPG/PNG/WebP statis.

Contoh curl (ganti ID dengan hasil endpoint sebelumnya):

```bash
curl -X POST http://localhost:8000/projects/PROJECT_ID/moodboards/MOODBOARD_ID/sources \
  -F "revision=1" -F "files=@moodboard.png"
```

Respons `items` berisi status per file: `created`, `duplicate`, atau `rejected`.
File invalid tidak membuang file valid lainnya. Duplicate menunjuk sumber yang sudah
ada; gunakan PATCH source untuk memasukkannya kembali jika sebelumnya dikeluarkan.
Maksimum default: 10 gambar, 10 MB/file, 50 MB/snapshot, 40 megapiksel/file.
Original tetap disimpan; salinan analisis maksimal 2048 piksel dan tanpa EXIF.

`PATCH /{moodboard_id}/sources/{source_id}` mengatur peran, catatan, urutan, dan inclusion:

```json
{"revision":2,"label":"Warna utama","notes":"Hanya ikuti palet; bukan model manusia.","roles":["color"],"included":true,"sequence_order":1}
```

`GET /{moodboard_id}/sources/{source_id}/file` mengunduh original;
tambahkan `?preview=true` untuk salinan analisis. Tidak ada path storage di respons API.
Set `included:false` untuk mengeluarkan sumber dari analisis berikutnya tanpa menghapus histori.

### 3. Mulai analisis dan pantau progres

`POST /{moodboard_id}/analyses` dengan header `Idempotency-Key: analysis-unique-1`:

```json
{"revision":3}
```

Respons 202 memuat ID versi sekaligus ID job. Poll:

`GET /{moodboard_id}/analyses/{version_id}`

Status: queued, running, partial, succeeded, failed, cancelled.
`per_source` menyimpan hasil dan kegagalan tiap gambar. `stage` menunjukkan tahap.
Hasil partial bisa direview tetapi tidak diapprove; retry memerlukan review ulang
hasil lengkap. Review parsial sebelumnya tetap disimpan pada event partial_retry.
Saat succeeded, `human_summary` memiliki field sesuai MB-07 PRD:

```text
status_analisis, status_panduan, ringkasan_visual, referensi,
gaya_utama, nuansa, palet_warna, elemen_visual, kelompok_visual,
panduan_bersama, perbedaan_atau_konflik, pertanyaan_klarifikasi, keterbatasan
```

`referensi.id` memakai `G1-P1` untuk panel pertama gambar pertama. Field lokasi
bersifat deskriptif, bukan koordinat crop. Field kelompok visual memakai
`{nama, deskripsi, referensi}`; konflik memakai `{deskripsi, referensi}`.

- Retry hasil parsial/gagal: `POST /{moodboard_id}/analyses/{version_id}/retry`.
- Cancel best effort: `POST /{moodboard_id}/analyses/{version_id}/cancel`.
- Daftar versi: `GET /{moodboard_id}/versions`.

Analisis ulang dengan idempotency key baru membuat versi baru. Snapshot menyimpan
sumber, urutan, konteks, dan catatan pada waktu analisis, sehingga perubahan draft
tidak mengubah hasil atau ekspor lama. `based_on_version_id` opsional mencatat asal
revisi; koreksi dan approval tidak otomatis diwarisi karena perlu review baru.

### 4. Review dan approval

`findings` memuat ID, path field, nilai asli, nilai review, sumber, confidence,
review state, dan kekuatan arahan. Semua temuan awalnya pending.

`PATCH /{moodboard_id}/versions/{version_id}/review`:

```json
{
  "revision":1,
  "decisions":[
    {"finding_id":"F-001","decision":"accepted","strength":"reference_only"},
    {"finding_id":"F-002","decision":"edited","value":{"deskripsi":"Ilustrasi botanical","ciri_utama":["Organik"],"dasar":"instruksi_pengguna","referensi":["G1-P1"],"keyakinan":"tinggi"},"strength":"prefer","note":"Arahan director"}
  ],
  "conflict_resolutions":{"0":"Pakai pencahayaan hangat; referensi dingin hanya untuk framing."},
  "instructions":[{"text":"Pertahankan identitas karakter","strength":"must"}]
}
```

`value` untuk edited harus mengikuti bentuk nilai asli temuan. Accepted/rejected
tidak menerima value. Jangan mengirim resolusi index 0 jika hasil tidak mempunyai
konflik. Instructions, jika dikirim, mengganti seluruh daftar instruksi tambahan.
Strength: must, prefer, avoid, reference_only. Rejected selalu reference_only.

Setelah semua temuan selesai direview dan konflik diputuskan:

`POST /{moodboard_id}/versions/{version_id}/approve`

```json
{"revision":2}
```

Versi approved menjadi immutable. Buat analisis baru untuk perubahan berikutnya.
Review dan approval disimpan pada log `GET /{moodboard_id}/versions/{version_id}/events`.

### 5. Ekspor Markdown

`POST /{moodboard_id}/versions/{version_id}/exports`
Header: `Idempotency-Key: export-unique-1`.

```json
{"language":"id"}
```

Respons memuat export ID, filename, content (preview), dan hash.

- Preview: `GET /{moodboard_id}/exports/{export_id}/preview`.
- Unduh `.md`: `GET /{moodboard_id}/exports/{export_id}`.
- Bahasa Inggris (`en`) diterjemahkan dan berstatus pending_confirmation;
  periksa preview lalu `POST /{moodboard_id}/exports/{export_id}/confirm` sebelum download.

Markdown mencakup konteks, style, mood, warna, seluruh komponen visual, constraint
manusia, panduan, manifest referensi, konflik/keputusan, unknown, keterbatasan, dan
arahan siap salin. Konteks dan catatan sumber asli dipertahankan sebagai data;
ekspor Inggris menerjemahkan analisis dan constraint. Gambar tidak tertanam;
lampirkan original secara terpisah ke AI tujuan bila dibutuhkan.
Download versi lama mengembalikan bytes dan hash yang sama. Tidak ada upload otomatis ke AI lain.

### 6. Metadata, arsip, dan error

- `GET /` memakai limit/offset; `?archived=true` menampilkan arsip.
- `PATCH /{moodboard_id}` menerima revision dan title/context/intended_use/archived.
- Arsip tidak menghapus original, histori, dan ekspor.
- 400: input invalid; 404: tidak ditemukan dalam project; 409: revision stale atau state salah;
  503: provider belum dikonfigurasi; 502: terjemahan gagal.
- Format error mengikuti backend: `{"error":{"code":"...","message":"...","fields":[]}}`.

## Pengujian

Dari root workspace, pengujian PostgreSQL pada container terpisah:

```bash
docker compose --profile test run --build --rm test
```

Service db-test tidak menggunakan volume produksi. Test vision memakai adapter yang
dimock untuk menghindari biaya/API key; production tetap memakai provider nyata.
Tes mencakup CRUD yang sudah ada dan upload, output schema, review, approval,
isolation, partial/retry, immutable history, dan ekspor moodboard.

## Menjalankan tanpa Docker

Dari folder backend, install `requirements.txt`, isi `.env` berdasarkan
`.env.example`, lalu:

```bash
uvicorn app.main:app --reload --port 8000
```

PostgreSQL harus tersedia. Gunakan satu process API untuk runner MVP ini.
