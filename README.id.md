# Hololive Dreams Auto Jump Rope

[English](README.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Indonesian](README.id.md) · [简体中文](README.zh-CN.md)

Program lompat tali untuk *hololive Dreams* versi Windows. Program mengenali posisi tali dari layar game, melompat melalui input mouse biasa, lalu melanjutkan ke ronde berikutnya setelah layar hasil.

## Unduh

Unduh **1.3.1** dari [Releases](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/releases/latest) dan ekstrak paket lengkap Windows x64 `.7z`. Paket menyertakan TensorRT 10.13 dan DirectML. Sistem NVIDIA yang kompatibel otomatis memakai TensorRT FP16; GPU lain yang didukung memakai DirectML.

Simpan EXE, `_internal/`, dan `accelerators/` dalam folder yang sama. Program tidak menggunakan PyTorch saat dijalankan. Saat TensorRT pertama kali dimulai, program membangun dan menyimpan cache engine untuk GPU lokal sebelum mengoperasikan game; proses ini dapat memerlukan beberapa menit.

Kode sumber sebelumnya dan Lisensi MIT disimpan di [archive/v1.2.1](archive/v1.2.1/).

## Fitur

- Batas skor dapat dipilih tanpa batas atau diisi 1–999. Setelah skor HUD dipastikan mencapai batas, lompatan berhenti hingga layar hasil, lalu ronde berikutnya mengikuti batas ronde.
- Melacak gerakan tali dan menentukan waktu lompatan secara otomatis.
- Penggeser waktu lompat kontinu −40 hingga +40 ms berlaku untuk putaran dan sapuan lantai. Tengah mempertahankan setelan standar; negatif lebih awal, positif lebih lambat. Klik 0 atau tengah rel untuk mereset. Tanda lain tidak membatasi posisi.
- Mengenali menu mulai dan hasil, lalu melanjutkan setelah ronde selesai.
- Mendukung enam bahasa antarmuka: Mandarin Tradisional, Mandarin Sederhana, Inggris, Jepang, Korea, dan Indonesia. Bahasa program tidak mengubah pengaturan game.
- Target ronde dapat diatur; program berhenti saat target tercapai.
- Pintasan bawaan: F8 untuk mulai, F9 untuk berhenti. Klik kolom pintasan lalu tekan tombol atau kombinasi tombol baru. Pintasan mulai dan berhenti harus berbeda.
- Riwayat aktivitas dan mode diagnostik lokal opsional.

## Cara menggunakan

1. Buka layar mulai atau hasil lompat tali di game.
2. Jalankan EXE dan pilih bahasa program pada Bahasa/Language.
3. Atur target 1–999 ronde; nilai bawaan adalah 1. Untuk mengganti pintasan, klik kolomnya lalu tekan tombol yang diinginkan.
4. Klik Mulai atau tekan pintasan mulai. Program mencoba membawa game ke depan. Pastikan seluruh game terlihat tanpa halangan pada monitor utama. Pilih karakter berwarna gelap, berambut pendek, dengan sedikit hiasan dan aksesori, misalnya **Juufuutei Raden (kostum bawaan)** dengan pixel sunglasses.
5. Tekan pintasan berhenti atau klik Berhenti. Jika game kehilangan fokus, program mencoba mengembalikannya ke depan, maksimal tiga kali per rangkaian ronde. Hentikan program sebelum beralih ke program lain.

## Persyaratan dan batasan

Program hanya memakai inferensi GPU. Paket lengkap menyertakan TensorRT 10.13 dan ONNX Runtime DirectML. Lingkungan NVIDIA yang kompatibel otomatis memakai TensorRT FP16; selain itu, DirectML berjalan pada GPU perangkat keras DirectX 12 yang didukung.

Memerlukan Windows 10／11 x64 dan game versi Windows. Pertahankan area klien game pada rasio 16:9; jangan meminimalkan, menutupi, atau memindahkan jendelanya selama program berjalan.

Naikkan pengaturan grafis setinggi mungkin selama game tetap stabil pada 60 FPS.

Input lompat pada antarmuka adalah jumlah input; lihat skor sebenarnya pada layar hasil game. Warna karakter, animasi, resolusi, kinerja komputer, dan pembaruan game dapat memengaruhi pengenalan. Hentikan program dan berikan data diagnostik jika terjadi masalah.

## Implementasi teknis

Seluruh area klien game diubah menjadi 640×640 dengan letterbox yang menjaga rasio aspek. Satu model YOLO26n Detect mengenali kotak tali yang terlihat serta penanda segitiga pemain. Bobot yang sama dijalankan pada GPU perangkat keras melalui TensorRT 10.13 FP16 atau ONNX Runtime DirectML; inferensi model pada CPU dinonaktifkan.

[Pengendali temporal](controller/policy.py) menggabungkan batas kotak berurutan, gerakan, selang waktu frame nyata, dan pola gerakan acuan untuk memperkirakan lintasan tali berikutnya. Penanda pemain dan riwayat input membantu memastikan keadaan melayang atau mendarat. Kotak sebagian hanya menjadi bukti sebagian, tanpa mengisi tali yang tertutup. Reservasi singkat yang stabil dapat bertahan dalam oklusi terbatas, dan waktu gerakan melingkar mengikuti perkiraan kecepatan.

[Penggeser](timing_control.py) mengubah jendela input dan reservasi gerakan melingkar maupun menyapu lantai secara kontinu dari −40 hingga +40 ms. Titik tengah adalah waktu bawaan; klik 0 atau tengah lintasan untuk mengatur ulang.

[Pemantau skor](score_limit.py) membaca angka HUD dari gambar tangkapan yang sama. Pembacaan andal berulang serta pemeriksaan kenaikan skor mengonfirmasi ambang berhenti. Setelah tercapai, reservasi dan input dilepas sambil menunggu layar hasil normal. Mode tanpa batas tidak membaca skor.

[Loop kendali](jump_rope_bot.py) menggunakan satu penangkap DXGI dan satu pemilik input. Timer terpisah yang dapat dihentikan melepas input setelah target 25 ms sementara pengamatan berlanjut. Sebelum menekan, program memeriksa fokus, ukuran, permintaan berhenti, dan identitas gambar sumber. Jendela waktu lintasan dan batas waktu prediksi saat terhalang tetap berlaku; menu mulai dan hasil dikenali dari bentuk dan warna tanpa bergantung pada teks.

## Laporan masalah dan mode pengembang

Laporkan kegagalan melanjutkan ronde, masalah lompatan, atau masalah lain melalui [GitHub Issues](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/issues).

Aktifkan Mode pengembang sebelum mengulangi masalah. Mode ini menyimpan gambar diagnostik, catatan pengenalan tiap frame, waktu input, dan durasi pemrosesan secara lokal tanpa unggahan otomatis. Mengaktifkannya menambah beban pemrosesan.

Klik `?` untuk melihat dan membuka folder diagnostik:

```text
%LOCALAPPDATA%\HololiveJumpRopeAuto\sessions\
```

`session-diagnostics.zip` untuk seluruh proses juga disimpan jika inisialisasi gagal sebelum gambar ditangkap. Mode pengembang mencatat judul jendela, nama proses yang mengambil fokus, dan proses pemulihan.

Setiap proses membuat folder dengan nama waktu. Setelah setiap ronde selesai, `diagnostics.zip` dibuat dalam folder `round-nomor`. Sertakan versi program, bahasa／karakter game, resolusi, skala tampilan Windows, deskripsi masalah, dan ZIP ronde bermasalah dalam laporan.

## Kode sumber dan lisensi

Cara menjalankan, membangun, dan menguji tersedia dalam [panduan pengembangan](docs/DEVELOPMENT.md). Pelatihan dan ekspor ada di [training/](training/README.md), dan perubahan terdahulu ada dalam [riwayat versi](docs/VERSION_HISTORY.md).

Program saat ini dan bobot turunan YOLO memakai [AGPL-3.0](LICENSE); versi arsip tetap memakai MIT. Hak cipta serta ketentuan pihak ketiga tercantum dalam [NOTICE.md](NOTICE.md).

[Anotasi](annotations/README.md) mencakup 672 sampel tali yang diperbaiki manual dan siap dilatih, serta 3 sampel belum pasti yang dikeluarkan dari pelatihan. Anotasi orisinal memakai CC BY 4.0; hak gambar game tetap pada pemiliknya.
