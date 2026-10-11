# Hololive Dreams Auto Jump Rope — 1.0

[English](README.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Indonesian](README.id.md) · [简体中文](README.zh-CN.md)

Program lompat tali untuk *hololive Dreams* versi Windows. Program mengenali posisi tali dari layar game, melompat melalui input mouse biasa, lalu melanjutkan ke ronde berikutnya setelah layar hasil.

## Unduh

Buka [GitHub Releases](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/releases/tag/v1.0) dan unduh `HololiveDreamsJumpRopeAuto-1.0.exe`.

Cukup jalankan satu EXE ini; tidak perlu memasang Python. Tersedia berkas checksum SHA-256. ZIP kode sumber perlu dibangun sendiri.

## Fitur

- Melacak gerakan tali dan menentukan waktu lompatan secara otomatis.
- Mengenali menu mulai dan hasil, lalu melanjutkan setelah ronde selesai.
- Mendukung enam bahasa antarmuka: Mandarin Tradisional, Mandarin Sederhana, Inggris, Jepang, Korea, dan Indonesia. Bahasa program tidak mengubah pengaturan game.
- Target ronde dapat diatur; program berhenti saat target tercapai dan mengatur ulang hitungan setiap kali dimulai.
- Pintasan bawaan: F8 untuk mulai, F9 untuk berhenti. Klik kolom pintasan lalu tekan tombol atau kombinasi tombol baru. Pintasan mulai dan berhenti harus berbeda.
- Riwayat aktivitas dan mode diagnostik lokal opsional.

## Cara menggunakan

1. Buka layar mulai atau hasil lompat tali di game.
2. Jalankan EXE dan pilih bahasa program pada Bahasa/Language.
3. Atur target 1–999 ronde; nilai bawaan adalah 1. Untuk mengganti pintasan, klik kolomnya lalu tekan tombol yang diinginkan.
4. Klik Mulai atau tekan pintasan mulai. Program mencoba membawa game ke depan. Pastikan seluruh game terlihat tanpa halangan pada monitor utama. Pilih karakter berwarna gelap, berambut pendek, dengan sedikit hiasan dan aksesori, misalnya **Juufuutei Raden (kostum bawaan)** dengan pixel sunglasses.
5. Tekan pintasan berhenti, klik Berhenti, atau pindah jendela untuk menghentikan program. Mulai kembali akan mengatur ulang hitungan.

## Persyaratan dan batasan

Memerlukan Windows 10／11 x64 dan game versi Windows. Pertahankan area klien game pada rasio 16:9; jangan meminimalkan, menutupi, atau memindahkan jendelanya selama program berjalan. Permainan di latar belakang dan login otomatis setelah pergantian hari tidak didukung.

Naikkan pengaturan grafis setinggi mungkin selama game tetap stabil pada 60 FPS.

Input lompat pada antarmuka adalah jumlah input; lihat skor sebenarnya pada layar hasil game. Warna karakter, animasi, resolusi, kinerja komputer, dan pembaruan game dapat memengaruhi pengenalan. Hentikan program dan berikan data diagnostik jika terjadi masalah.

> [!WARNING]
> **Kesalahan tangkapan pada komputer dengan dua GPU**
>
> Jika saat mulai muncul `-2005270524 / 0x887A0004` (Antarmuka perangkat atau tingkat fitur yang ditentukan tidak didukung pada sistem ini.), ubah preferensi GPU program:
>
> ![Pesan kesalahan tangkapan DXGI](docs/dxgi-unsupported-error.png)
>
> 1. Buka Pengaturan Windows → Sistem → Tampilan → Tampilan tingkat lanjut, pilih monitor utama yang digunakan untuk game, lalu periksa nama GPU yang terhubung ke monitor tersebut.
> 2. Kembali ke Tampilan → Grafik (“Pengaturan grafis” pada Windows 10), tambahkan aplikasi desktop, lalu pilih `HololiveDreamsJumpRopeAuto-1.0.exe` yang benar-benar dijalankan.
> 3. Pilih Opsi aplikasi, pilih GPU di atas pada preferensi Grafis, lalu pilih Simpan. “Hemat daya” biasanya merujuk ke GPU terintegrasi dan “Performa tinggi” ke GPU diskret; periksa nama GPU yang ditampilkan.
> 4. Tutup program sepenuhnya, buka kembali, lalu klik Mulai untuk menguji.
>
> Terapkan pengaturan ini pada EXE program. Layar internal dan monitor eksternal, mode GPU diskret langsung, serta mode hibrida dapat memakai GPU keluaran yang berbeda; pilih berdasarkan koneksi layar saat ini. Jika masih gagal, aktifkan Mode pengembang, reproduksi sekali, lalu sertakan `session.log` dari folder sesi tersebut, model GPU, dan informasi koneksi layar.

## Implementasi teknis

### Pengambilan dan pemrosesan gambar

[Modul tangkapan](vision.py) memakai DXGI／DXcam untuk mengambil frame baru dari area klien game, dengan pemeriksaan fokus, posisi, ukuran, dan halangan sebelum serta sesudah pengambilan. Loop kontrol menargetkan 60 FPS; laju sebenarnya bergantung pada frame baru game, biaya pengenalan, dan penjadwalan sistem. Frame lama tidak digunakan untuk melompat ketika frame baru tidak tersedia. Setelah jeda tangkapan setidaknya 100ms, frame pemulihan dibuang dan detektor diatur ulang. Jika tidak ada frame baru dalam 500ms, program berhenti.

[Pemrosesan area](priority.py) menggunakan acuan pengenalan 960×540. Area sampel dipotong sebelum diubah ukurannya dengan skala semula. Batas potongan mengikuti rasio bilangan bulat antara resolusi masukan dan keluaran agar posisi sampel tetap sama sekaligus mengurangi pemrosesan piksel yang tidak diperlukan.

### Pengenalan tali dan pencocokan kurva

[Pelacak](candidate_tracker.py) mengambil 100 kolom sampel pada lima bagian horizontal. Masker HSV memilih kandidat biru／ungu, emas, merah muda, dan putih terang; perbedaan antar-frame dan kontras garis tipis menyaring latar belakang. Kelompok titik dari bagian berbeda menghasilkan beberapa kurva kuadrat yang dinilai berdasarkan dukungan sepanjang kurva serta distribusinya antarbagian. Pengamatan yang meyakinkan juga memperbarui acuan warna tali untuk pelacakan berikutnya.

Kurva terpilih menghasilkan tinggi tali relatif terhadap pemain, proporsi dukungan yang terlihat, warna utama, dan arah gerakan. Potongan di kedua sisi dapat membatasi kurva saat bagian tengah tertutup karakter atau properti. Ketika bukti tidak cukup, program mempertahankan keadaan yang diperlukan untuk pengamatan ulang, bukan melompat berdasarkan jadwal tetap.

### Keputusan melompat dan pemulihan setelah terhalang

[Detektor](jump_detector.py) memakai keadaan mendekat, melintas, menjauh, dan berbalik pada tali rendah untuk menentukan apakah satu lintasan sudah memicu input. Untuk mengaktifkan kembali lompatan setelah terhalang, program memeriksa potongan yang terlihat secara berurutan, dukungan kedua sisi, dan perubahan tinggi agar lintasan yang sama tidak memicu input berulang.

Pemeriksaan perubahan mendadak memisahkan waktu pengamatan terakhir yang sebenarnya dari waktu posisi terakhir yang diterima. Kurva dengan dukungan sebagian yang tiba-tiba mendekati pemain tidak diterima hanya karena posisi tersimpan sudah lama. Tiga pengamatan mentah terbaru yang menunjukkan pendekatan konsisten dan meyakinkan dapat mengembalikan evaluasi normal.

### Input, menu, dan kelanjutan ronde

Setelah muncul kandidat lompatan, [pengontrol](jump_rope_bot.py) mengambil frame baru lagi untuk memastikan permainan masih aktif, pemain siap, dan tombol lompat terlihat. Koordinat relatif diubah menjadi koordinat layar, lalu input mouse Windows diminta menahan tombol kiri selama 25ms. Tombol tetap dilepas bila input terputus. Durasi sebenarnya dicatat dalam diagnostik dan dapat dipengaruhi penjadwalan sistem.

Pengenalan menu menggunakan posisi tombol, garis luar kapsul sian, tepi putih, dan warna halaman, tanpa membandingkan teks di dalam tombol. Navigasi memerlukan konfirmasi beberapa frame dan membatasi percobaan ulang pada halaman yang sama. Setelah HUD game terkonfirmasi, navigasi menu dinonaktifkan untuk ronde itu. [Kontrol sesi](batch_session.py) hanya memulai ronde berikutnya setelah ronde sebelumnya selesai dan halaman hasil stabil, lalu berhenti pada target. Program memakai gambar layar dan input biasa tanpa membaca atau mengubah memori proses, berkas simpanan, atau berkas game.

## Laporan masalah dan mode pengembang

Laporkan kegagalan melanjutkan ronde, masalah lompatan, atau masalah lain melalui [GitHub Issues](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/issues).

Aktifkan Mode pengembang sebelum mengulangi masalah. Mode ini menyimpan gambar diagnostik, catatan pengenalan tiap frame, waktu input, dan durasi pemrosesan secara lokal tanpa unggahan otomatis. Mengaktifkannya menambah beban pemrosesan.

Klik `?` untuk melihat dan membuka folder diagnostik:

```text
%LOCALAPPDATA%\HololiveJumpRopeAuto\sessions\
```

Setiap proses membuat folder dengan nama waktu. Setelah setiap ronde selesai, `diagnostics.zip` dibuat dalam folder `round-nomor`. Sertakan versi program, bahasa／karakter game, resolusi, skala tampilan Windows, deskripsi masalah, dan ZIP ronde bermasalah dalam laporan.

## Kode sumber dan lisensi

Cara menjalankan sumber, membangun, menguji, dan format diagnostik tersedia di [panduan pengembangan](docs/DEVELOPMENT.md). Perubahan yang disusun dari percakapan ini tersedia di [riwayat versi](docs/VERSION_HISTORY.md); versi terdahulu ditandai sudah digantikan. Kedua dokumen menggunakan Mandarin Tradisional.

Kode menggunakan [MIT License](LICENSE). Hak Logo dan konten terkait game dimiliki pemegang hak masing-masing.
