from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from epub2m4b.core.dependencies import (
    deepspeed_available,
    dependency_issues,
    ffmpeg_installed,
    windows_vctools_available,
)
from epub2m4b.core.epub import EpubParseError, parse_epub
from epub2m4b.core.models import ParsedBook, PipelineOptions, QUALITY_PRESETS, TocEntry
from epub2m4b.tts.registry import ENGINE_CLASSES, engine_infos
from epub2m4b.tts.xtts_subprocess_pool import AUTO_WORKERS
from epub2m4b.tts.xtts import (
    DEFAULT_SPEAKER,
    PERFORMANCE_MODE_COMPATIBILITY,
    PERFORMANCE_MODE_DEEPSPEED,
    PERFORMANCE_MODE_OPTIMIZED,
    VOICE_MODE_BUILTIN,
    VOICE_MODE_CLONE,
)

from .worker import (
    ConversionWorker,
    DeepSpeedDependencyWorker,
    DependencyWorker,
    XTTSBenchmarkWorker,
    XTTSPreviewWorker,
    XTTSSpeakerWorker,
)


XTTS_PREVIEW_TEXT = (
    "Merhaba. Bu, Türkçe sesli kitap için hazırlanan kısa bir ses önizlemesidir. "
    "Seçtiğiniz anlatıcıyı ve konuşma hızını burada dinleyebilirsiniz."
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EPUB -> M4B Türkçe Sesli Kitap")
        self.resize(1040, 900)
        self.worker: ConversionWorker | None = None
        self.dep_worker: DependencyWorker | None = None
        self.deepspeed_worker: DeepSpeedDependencyWorker | None = None
        self.speaker_worker: XTTSSpeakerWorker | None = None
        self.preview_worker: XTTSPreviewWorker | None = None
        self.benchmark_worker: XTTSBenchmarkWorker | None = None
        self.current_book: ParsedBook | None = None
        self.current_epub_path: Path | None = None
        self._toc_syncing = False
        self.last_preview_path: Path | None = None
        self.audio_output = QAudioOutput(self)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self._build_ui()
        self._engine_changed()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        title = QLabel("EPUB -> M4B Türkçe Sesli Kitap")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        subtitle = QLabel("Yerel açık kaynak TTS motorları • bölüm işaretleri • kapak gömme • AAC/M4B")
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        files_box = QGroupBox("1. Kitap ve çıktı")
        files_form = QFormLayout(files_box)
        self.epub_edit = QLineEdit()
        epub_row = QHBoxLayout()
        epub_row.addWidget(self.epub_edit, 1)
        browse_epub = QPushButton("EPUB Seç")
        browse_epub.clicked.connect(self._browse_epub)
        epub_row.addWidget(browse_epub)
        analyze = QPushButton("Analiz Et")
        analyze.clicked.connect(self._analyze_epub)
        epub_row.addWidget(analyze)
        files_form.addRow("EPUB:", epub_row)

        self.output_edit = QLineEdit()
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        browse_output = QPushButton("Kaydet...")
        browse_output.clicked.connect(self._browse_output)
        output_row.addWidget(browse_output)
        files_form.addRow("M4B çıktı:", output_row)
        self.book_info = QLabel("Henüz EPUB analiz edilmedi.")
        self.book_info.setWordWrap(True)
        files_form.addRow("Kitap:", self.book_info)
        layout.addWidget(files_box)

        toc_box = QGroupBox("2. İçindekiler / Seslendirilecek Bölümler")
        toc_layout = QVBoxLayout(toc_box)
        toc_hint = QLabel(
            "EPUB içindekiler yapısı aşağıda gösterilir. TOC'de bulunan okunabilir içerik varsayılan "
            "olarak seçilir; spine'da bulunup TOC'de görünmeyen ek içerik listelenir ama seçilmez."
        )
        toc_hint.setWordWrap(True)
        toc_hint.setStyleSheet("color: #666;")
        toc_layout.addWidget(toc_hint)
        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderLabels(["İçerik", "Karakter", "Kaynak / statü"])
        self.toc_tree.setRootIsDecorated(True)
        self.toc_tree.setAlternatingRowColors(True)
        self.toc_tree.setMinimumHeight(170)
        self.toc_tree.itemChanged.connect(self._toc_item_changed)
        toc_layout.addWidget(self.toc_tree)
        toc_actions = QHBoxLayout()
        self.toc_select_toc_btn = QPushButton("TOC İçeriğini Seç")
        self.toc_select_toc_btn.clicked.connect(self._select_toc_content)
        toc_actions.addWidget(self.toc_select_toc_btn)
        self.toc_select_all_btn = QPushButton("Tümünü Seç")
        self.toc_select_all_btn.clicked.connect(lambda: self._set_all_toc(Qt.CheckState.Checked))
        toc_actions.addWidget(self.toc_select_all_btn)
        self.toc_clear_all_btn = QPushButton("Tümünü Kaldır")
        self.toc_clear_all_btn.clicked.connect(lambda: self._set_all_toc(Qt.CheckState.Unchecked))
        toc_actions.addWidget(self.toc_clear_all_btn)
        self.toc_selection_label = QLabel("EPUB analiz edildiğinde bölüm seçimi burada görünecek.")
        toc_actions.addWidget(self.toc_selection_label, 1)
        toc_layout.addLayout(toc_actions)
        toc_box.setEnabled(False)
        self.toc_box = toc_box
        layout.addWidget(toc_box)

        engine_box = QGroupBox("3. TTS motoru")
        engine_form = QFormLayout(engine_box)
        self.engine_combo = QComboBox()
        for info in engine_infos():
            self.engine_combo.addItem(info.name, info.id)
        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        engine_form.addRow("Model:", self.engine_combo)

        self.engine_desc = QLabel()
        self.engine_desc.setWordWrap(True)
        engine_form.addRow("Özellik:", self.engine_desc)

        self.license_label = QLabel()
        self.license_label.setOpenExternalLinks(True)
        self.license_label.setWordWrap(True)
        engine_form.addRow("Lisans:", self.license_label)

        dep_row = QHBoxLayout()
        self.dep_status = QLabel()
        dep_row.addWidget(self.dep_status, 1)
        self.install_dep_btn = QPushButton("Bağımlılıkları Kur/Onar")
        self.install_dep_btn.clicked.connect(self._install_dependencies)
        dep_row.addWidget(self.install_dep_btn)
        engine_form.addRow("Kurulum:", dep_row)

        self.device_combo = QComboBox()
        self.device_combo.addItem("Otomatik", "auto")
        self.device_combo.addItem("NVIDIA CUDA", "cuda")
        self.device_combo.addItem("CPU", "cpu")
        engine_form.addRow("Aygıt:", self.device_combo)

        self.xtts_mode_label = QLabel("Ses yöntemi:")
        self.xtts_mode_combo = QComboBox()
        self.xtts_mode_combo.addItem("Hazır XTTS sesi", VOICE_MODE_BUILTIN)
        self.xtts_mode_combo.addItem("Referans sesten klonlama", VOICE_MODE_CLONE)
        self.xtts_mode_combo.currentIndexChanged.connect(self._xtts_mode_changed)
        engine_form.addRow(self.xtts_mode_label, self.xtts_mode_combo)

        self.xtts_speaker_label = QLabel("XTTS sesi:")
        speaker_row = QHBoxLayout()
        self.xtts_speaker_combo = QComboBox()
        self.xtts_speaker_combo.addItem(DEFAULT_SPEAKER)
        speaker_row.addWidget(self.xtts_speaker_combo, 1)
        self.xtts_speakers_btn = QPushButton("Sesleri Yükle/Yenile")
        self.xtts_speakers_btn.clicked.connect(self._load_xtts_speakers)
        speaker_row.addWidget(self.xtts_speakers_btn)
        engine_form.addRow(self.xtts_speaker_label, speaker_row)

        self.xtts_speed_label = QLabel("Konuşma hızı:")
        self.xtts_speed = QDoubleSpinBox()
        self.xtts_speed.setRange(0.7, 1.6)
        self.xtts_speed.setSingleStep(0.05)
        self.xtts_speed.setDecimals(2)
        self.xtts_speed.setValue(1.0)
        self.xtts_speed.setSuffix("x")
        engine_form.addRow(self.xtts_speed_label, self.xtts_speed)

        self.xtts_performance_label = QLabel("XTTS calisma modu:")
        self.xtts_performance_combo = QComboBox()
        self.xtts_performance_combo.addItem("Optimize (onerilen)", PERFORMANCE_MODE_OPTIMIZED)
        self.xtts_performance_combo.addItem("DeepSpeed (deneysel / hizli)", PERFORMANCE_MODE_DEEPSPEED)
        self.xtts_performance_combo.addItem("Uyumluluk / klasik TTS.api", PERFORMANCE_MODE_COMPATIBILITY)
        self.xtts_performance_combo.currentIndexChanged.connect(self._xtts_performance_changed)
        performance_row = QHBoxLayout()
        performance_row.addWidget(self.xtts_performance_combo, 1)
        self.xtts_deepspeed_btn = QPushButton("DeepSpeed Kur/Onar")
        self.xtts_deepspeed_btn.clicked.connect(self._install_deepspeed)
        performance_row.addWidget(self.xtts_deepspeed_btn)
        engine_form.addRow(self.xtts_performance_label, performance_row)

        self.xtts_workers_label = QLabel("XTTS worker:")
        worker_row = QHBoxLayout()
        self.xtts_workers_combo = QComboBox()
        self.xtts_workers_combo.addItem("Otomatik (1-4 worker olc, en hizlisini sec)", AUTO_WORKERS)
        self.xtts_workers_combo.addItem("1 worker (daha az VRAM)", 1)
        self.xtts_workers_combo.addItem("2 worker (RTX 3090 icin guvenli baslangic)", 2)
        self.xtts_workers_combo.addItem("3 worker (24 GB VRAM - deneysel)", 3)
        self.xtts_workers_combo.addItem("4 worker (24 GB VRAM - 4x hedefi icin deneysel)", 4)
        self.xtts_workers_combo.setCurrentIndex(0)
        worker_row.addWidget(self.xtts_workers_combo, 1)
        self.xtts_benchmark_btn = QPushButton("Hiz Testi")
        self.xtts_benchmark_btn.clicked.connect(self._benchmark_xtts)
        worker_row.addWidget(self.xtts_benchmark_btn)
        engine_form.addRow(self.xtts_workers_label, worker_row)

        self.xtts_benchmark_result = QLabel("Hedef: 4.00x realtime. Otomatik mod 1-4 worker'i olcer ve en hizlisini secer.")
        self.xtts_benchmark_result.setWordWrap(True)
        self.xtts_benchmark_result.setStyleSheet("color: #666;")
        engine_form.addRow("XTTS benchmark:", self.xtts_benchmark_result)

        self.xtts_preview_label = QLabel("Ses önizleme:")
        preview_row = QHBoxLayout()
        self.xtts_preview_btn = QPushButton("~10 sn Örnek Ses Üret")
        self.xtts_preview_btn.clicked.connect(self._preview_xtts)
        preview_row.addWidget(self.xtts_preview_btn)
        self.xtts_play_btn = QPushButton("Tekrar Oynat")
        self.xtts_play_btn.setEnabled(False)
        self.xtts_play_btn.clicked.connect(self._play_xtts_preview)
        preview_row.addWidget(self.xtts_play_btn)
        preview_row.addStretch(1)
        engine_form.addRow(self.xtts_preview_label, preview_row)

        self.reference_edit = QLineEdit()
        ref_row = QHBoxLayout()
        ref_row.addWidget(self.reference_edit, 1)
        self.reference_btn = QPushButton("Referans WAV Seç")
        self.reference_btn.clicked.connect(self._browse_reference)
        ref_row.addWidget(self.reference_btn)
        self.reference_label = QLabel("XTTS referans sesi:")
        engine_form.addRow(self.reference_label, ref_row)

        self.voice_consent = QCheckBox("Bu referans sesi kullanma/klonlama iznine sahibim.")
        engine_form.addRow("", self.voice_consent)

        self.license_ack = QCheckBox()
        engine_form.addRow("", self.license_ack)
        layout.addWidget(engine_box)

        output_box = QGroupBox("4. M4B kalite")
        output_form = QFormLayout(output_box)
        self.quality_combo = QComboBox()
        for key, preset in QUALITY_PRESETS.items():
            self.quality_combo.addItem(preset.label, key)
        self.quality_combo.setCurrentIndex(1)
        output_form.addRow("AAC kalite:", self.quality_combo)
        self.keep_work = QCheckBox("Ara WAV dosyalarını/önbelleği başarılı işlemden sonra koru")
        output_form.addRow("", self.keep_work)
        layout.addWidget(output_box)

        actions = QHBoxLayout()
        self.start_btn = QPushButton("M4B Oluştur")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.clicked.connect(self._start)
        actions.addWidget(self.start_btn, 1)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        actions.addWidget(self.cancel_btn)
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        self.performance_status = QLabel("Performans bilgisi donusum basladiginda burada gorunecek.")
        self.performance_status.setWordWrap(True)
        self.performance_status.setStyleSheet("color: #555;")
        layout.addWidget(self.performance_status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("İşlem günlüğü burada görünecek...")
        layout.addWidget(self.log, 1)

    @property
    def engine_id(self) -> str:
        return str(self.engine_combo.currentData())

    def _browse_epub(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "EPUB seç", "", "EPUB (*.epub)")
        if not path:
            return
        self.epub_edit.setText(path)
        if not self.output_edit.text().strip():
            self.output_edit.setText(str(Path(path).with_suffix(".m4b")))
        self._analyze_epub()

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "M4B kaydet", self.output_edit.text(), "M4B (*.m4b)")
        if path:
            if not path.lower().endswith(".m4b"):
                path += ".m4b"
            self.output_edit.setText(path)

    def _browse_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Referans ses seç", "", "Audio (*.wav *.mp3 *.flac *.m4a)")
        if path:
            self.reference_edit.setText(path)

    def _analyze_epub(self) -> bool:
        path = Path(self.epub_edit.text().strip())
        if not path.is_file():
            self.current_book = None
            self.current_epub_path = None
            self.toc_tree.clear()
            self.toc_box.setEnabled(False)
            return False
        try:
            book = parse_epub(path)
        except EpubParseError as exc:
            self.book_info.setText(f"Hata: {exc}")
            self.current_book = None
            self.current_epub_path = None
            self.toc_tree.clear()
            self.toc_box.setEnabled(False)
            return False
        self.current_book = book
        self.current_epub_path = path.resolve()
        cover = "var" if book.metadata.cover_bytes else "yok"
        chars = sum(len(c.text) for c in book.chapters)
        self.book_info.setText(
            f"<b>{book.metadata.title}</b> — {book.metadata.author}<br>"
            f"{len(book.chapters)} bölüm • {chars:,} karakter • kapak: {cover}"
        )
        self._populate_toc(book)
        return True

    def _populate_toc(self, book: ParsedBook) -> None:
        chapter_chars = {chapter.index: len(chapter.text) for chapter in book.chapters}
        self._toc_syncing = True
        self.toc_tree.clear()

        source_labels = {
            "toc": "TOC",
            "spine": "Spine / TOC dışı",
            "spine_no_toc": "Spine (TOC yok)",
        }

        def add_entry(parent: QTreeWidget | QTreeWidgetItem, entry: TocEntry) -> None:
            is_group = bool(entry.children)
            chars = chapter_chars.get(entry.chapter_index or -1) if not is_group else None
            source_label = source_labels.get(entry.source, entry.source or "-")
            item = QTreeWidgetItem(
                parent,
                [entry.title, f"{chars:,}" if chars is not None else "", source_label],
            )
            item.setData(0, Qt.ItemDataRole.UserRole, entry.chapter_index if not is_group else None)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Checked if entry.default_selected else Qt.CheckState.Unchecked,
            )
            if is_group and entry.chapter_index is not None:
                direct_chars = chapter_chars.get(entry.chapter_index)
                direct_item = QTreeWidgetItem(
                    item,
                    [
                        "Bölüm başlangıcı / ana metin",
                        f"{direct_chars:,}" if direct_chars is not None else "",
                        source_label,
                    ],
                )
                direct_item.setData(0, Qt.ItemDataRole.UserRole, entry.chapter_index)
                direct_item.setFlags(direct_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                direct_item.setCheckState(
                    0,
                    Qt.CheckState.Checked if entry.default_selected else Qt.CheckState.Unchecked,
                )
            for child in entry.children:
                add_entry(item, child)

        for entry in book.toc:
            add_entry(self.toc_tree, entry)
        self._toc_syncing = False
        self.toc_tree.expandAll()
        self.toc_tree.resizeColumnToContents(1)
        self.toc_tree.resizeColumnToContents(2)
        self.toc_box.setEnabled(True)
        self._update_toc_selection_summary()

    @staticmethod
    def _iter_tree_items(tree: QTreeWidget):
        stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    def _set_children_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> set[int]:
        changed_indices: set[int] = set()
        for index in range(item.childCount()):
            child = item.child(index)
            child.setCheckState(0, state)
            chapter_index = child.data(0, Qt.ItemDataRole.UserRole)
            if chapter_index is not None:
                changed_indices.add(int(chapter_index))
            changed_indices.update(self._set_children_state(child, state))
        return changed_indices

    def _update_parent_states(self, item: QTreeWidgetItem | None) -> None:
        while item is not None:
            states = [item.child(i).checkState(0) for i in range(item.childCount())]
            if states:
                if all(state == Qt.CheckState.Checked for state in states):
                    state = Qt.CheckState.Checked
                elif all(state == Qt.CheckState.Unchecked for state in states):
                    state = Qt.CheckState.Unchecked
                else:
                    state = Qt.CheckState.PartiallyChecked
                item.setCheckState(0, state)
            item = item.parent()

    def _toc_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._toc_syncing or column != 0:
            return
        self._toc_syncing = True
        state = item.checkState(0)
        affected_parents: list[QTreeWidgetItem | None] = [item.parent()]
        if state in (Qt.CheckState.Checked, Qt.CheckState.Unchecked):
            changed_indices = self._set_children_state(item, state)
            # Some EPUB TOCs contain multiple anchors that point into the same
            # XHTML spine document. v0.1.x synthesizes at document granularity,
            # so all visible TOC aliases for that document must move together.
            chapter_index = item.data(0, Qt.ItemDataRole.UserRole)
            if chapter_index is not None:
                changed_indices.add(int(chapter_index))
            if changed_indices:
                for other in self._iter_tree_items(self.toc_tree):
                    other_index = other.data(0, Qt.ItemDataRole.UserRole)
                    if other_index is not None and int(other_index) in changed_indices:
                        other.setCheckState(0, state)
                        affected_parents.append(other.parent())
        for parent in affected_parents:
            self._update_parent_states(parent)
        self._toc_syncing = False
        self._update_toc_selection_summary()

    def _set_all_toc(self, state: Qt.CheckState) -> None:
        if not self.current_book:
            return
        self._toc_syncing = True
        for item in self._iter_tree_items(self.toc_tree):
            item.setCheckState(0, state)
        self._toc_syncing = False
        self._update_toc_selection_summary()


    def _select_toc_content(self) -> None:
        """Restore the safe default: TOC content on, spine-only extras off."""
        if not self.current_book:
            return
        selected = set(self.current_book.default_selected_chapter_indices())
        self._toc_syncing = True
        for item in self._iter_tree_items(self.toc_tree):
            chapter_index = item.data(0, Qt.ItemDataRole.UserRole)
            if chapter_index is not None:
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if int(chapter_index) in selected else Qt.CheckState.Unchecked,
                )
        # Recompute group/parent states bottom-up.
        items = list(self._iter_tree_items(self.toc_tree))
        for item in reversed(items):
            self._update_parent_states(item)
        self._toc_syncing = False
        self._update_toc_selection_summary()

    def _selected_chapter_indices(self) -> tuple[int, ...]:
        selected: set[int] = set()
        for item in self._iter_tree_items(self.toc_tree):
            chapter_index = item.data(0, Qt.ItemDataRole.UserRole)
            if chapter_index is not None and item.checkState(0) != Qt.CheckState.Unchecked:
                selected.add(int(chapter_index))
        return tuple(sorted(selected))

    def _update_toc_selection_summary(self) -> None:
        if not self.current_book:
            self.toc_selection_label.setText("EPUB analiz edildiğinde bölüm seçimi burada görünecek.")
            return
        selected = set(self._selected_chapter_indices())
        chars = sum(len(chapter.text) for chapter in self.current_book.chapters if chapter.index in selected)
        self.toc_selection_label.setText(
            f"Seçili: {len(selected)}/{len(self.current_book.chapters)} bölüm • {chars:,} karakter"
        )

    def _engine_changed(self) -> None:
        info = ENGINE_CLASSES[self.engine_id].info
        self.engine_desc.setText(info.description)
        use_text = "ticari kullanım mümkün" if info.commercial_use else "yalnız ticari olmayan kullanım"
        self.license_label.setText(f'<a href="{info.license_url}">{info.license_name}</a> — {use_text}')
        self.license_ack.setVisible(info.requires_license_ack)
        self.license_ack.setChecked(info.requires_license_ack)
        self.license_ack.setText(f"{info.license_name} koşullarını okudum ve kabul ediyorum.")
        xtts_visible = self.engine_id == "xtts"
        self.xtts_mode_label.setVisible(xtts_visible)
        self.xtts_mode_combo.setVisible(xtts_visible)
        self.xtts_speed_label.setVisible(xtts_visible)
        self.xtts_speed.setVisible(xtts_visible)
        self.xtts_performance_label.setVisible(xtts_visible)
        self.xtts_performance_combo.setVisible(xtts_visible)
        self.xtts_deepspeed_btn.setVisible(xtts_visible)
        self.xtts_workers_label.setVisible(xtts_visible)
        self.xtts_workers_combo.setVisible(xtts_visible)
        self.xtts_benchmark_btn.setVisible(xtts_visible)
        self.xtts_benchmark_result.setVisible(xtts_visible)
        self.xtts_preview_label.setVisible(xtts_visible)
        self.xtts_preview_btn.setVisible(xtts_visible)
        self.xtts_play_btn.setVisible(xtts_visible)
        if xtts_visible:
            self._xtts_mode_changed()
        else:
            self.xtts_speaker_label.setVisible(False)
            self.xtts_speaker_combo.setVisible(False)
            self.xtts_speakers_btn.setVisible(False)
            self.reference_label.setVisible(info.needs_reference_audio)
            self.reference_edit.setVisible(info.needs_reference_audio)
            self.reference_btn.setVisible(info.needs_reference_audio)
            self.voice_consent.setVisible(info.needs_reference_audio)
        self._refresh_dependency_status()
        if xtts_visible:
            self._xtts_performance_changed()

    def _xtts_mode_changed(self) -> None:
        if self.engine_id != "xtts":
            return
        clone_mode = str(self.xtts_mode_combo.currentData()) == VOICE_MODE_CLONE
        self.xtts_speaker_label.setVisible(not clone_mode)
        self.xtts_speaker_combo.setVisible(not clone_mode)
        self.xtts_speakers_btn.setVisible(not clone_mode)
        self.reference_label.setVisible(clone_mode)
        self.reference_edit.setVisible(clone_mode)
        self.reference_btn.setVisible(clone_mode)
        self.voice_consent.setVisible(clone_mode)

    def _xtts_performance_changed(self) -> None:
        if self.engine_id != "xtts":
            return
        deep = str(self.xtts_performance_combo.currentData()) == PERFORMANCE_MODE_DEEPSPEED
        self.xtts_deepspeed_btn.setEnabled(deep and not (self.deepspeed_worker and self.deepspeed_worker.isRunning()))
        if deep:
            if deepspeed_available():
                self.xtts_benchmark_result.setText(
                    "DeepSpeed hazir. Otomatik worker modu 1-4 worker'i ayni yuklu modellerle olcer; Hiz Testi ile en hizlisini secin."
                )
            else:
                self.xtts_benchmark_result.setText(
                    "DeepSpeed henuz hazir degil. Kur/Onar ile deneyin; kurulamazsa uygulama Optimize moda geri doner."
                )
        else:
            self.xtts_benchmark_result.setText("Hedef: 4.00x realtime. Otomatik mod 1-4 worker'i ayni yuklu modellerle olcer ve en hizlisini secer.")

    def _install_deepspeed(self) -> None:
        if self.deepspeed_worker and self.deepspeed_worker.isRunning():
            return
        install_build_tools = False
        if sys.platform.startswith("win") and not windows_vctools_available():
            answer = QMessageBox.question(
                self,
                "Visual C++ Build Tools gerekli",
                "DeepSpeed Windows'ta derleme gerektiriyor ve VS2022 C++ Build Tools bulunamadi.\n\n"
                "winget ile Visual Studio 2022 Build Tools + VCTools otomatik kurulsun mu? "
                "Indirme birkac GB olabilir ve UAC onayi isteyebilir.\n\n"
                "Hayir derseniz mevcut XTTS Optimize modu aynen calismaya devam eder.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.log.appendPlainText("DeepSpeed kurulumu iptal edildi; XTTS Optimize modu korunuyor.")
                return
            install_build_tools = True

        self.xtts_deepspeed_btn.setEnabled(False)
        self.log.appendPlainText("XTTS DeepSpeed opsiyonel kurulumu baslatiliyor...")
        self.deepspeed_worker = DeepSpeedDependencyWorker(
            install_build_tools=install_build_tools,
            parent=self,
        )
        self.deepspeed_worker.log_message.connect(self.log.appendPlainText)
        self.deepspeed_worker.succeeded.connect(self._deepspeed_done)
        self.deepspeed_worker.failed.connect(self._deepspeed_failed)
        self.deepspeed_worker.start()

    def _deepspeed_done(self) -> None:
        self.log.appendPlainText("DeepSpeed kurulumu/import testi tamamlandi.")
        self.xtts_deepspeed_btn.setEnabled(True)
        self._xtts_performance_changed()

    def _deepspeed_failed(self, message: str) -> None:
        self.log.appendPlainText("DeepSpeed kurulumu basarisiz: " + message)
        self.xtts_deepspeed_btn.setEnabled(True)
        if str(self.xtts_performance_combo.currentData()) == PERFORMANCE_MODE_DEEPSPEED:
            optimized_index = self.xtts_performance_combo.findData(PERFORMANCE_MODE_OPTIMIZED)
            if optimized_index >= 0:
                self.xtts_performance_combo.setCurrentIndex(optimized_index)
                self.log.appendPlainText(
                    "DeepSpeed hazir olmadigi icin XTTS calisma modu otomatik olarak Optimize'a alindi. "
                    "Secili coklu-worker sayisi korunuyor."
                )
        self._xtts_performance_changed()
        QMessageBox.warning(
            self,
            "DeepSpeed kurulumu",
            message
            + "\n\nXTTS calisma modu Optimize'a alindi; 2/3/4 worker paralelligini "
            "DeepSpeed olmadan da kullanabilirsiniz.",
        )

    def _benchmark_xtts(self) -> None:
        if not self._validate_xtts_aux_action():
            return
        if self.benchmark_worker and self.benchmark_worker.isRunning():
            return
        voice_mode = str(self.xtts_mode_combo.currentData())
        reference: Path | None = None
        if voice_mode == VOICE_MODE_CLONE:
            text = self.reference_edit.text().strip()
            reference = Path(text) if text else None
            if reference is None or not reference.is_file():
                QMessageBox.warning(self, "Referans ses", "Benchmark icin gecerli bir referans ses secin.")
                return
            if not self.voice_consent.isChecked():
                QMessageBox.warning(self, "Ses izni", "Referans sesi kullanma/klonlama iznini onaylayin.")
                return
        self.xtts_benchmark_btn.setEnabled(False)
        self.xtts_benchmark_result.setText("XTTS hiz testi calisiyor; model yukleme ve isinma birkac dakika surebilir...")
        self.benchmark_worker = XTTSBenchmarkWorker(
            device=str(self.device_combo.currentData()),
            accept_model_license=True,
            voice_mode=voice_mode,
            speaker=self.xtts_speaker_combo.currentText().strip() or DEFAULT_SPEAKER,
            speed=float(self.xtts_speed.value()),
            performance_mode=str(self.xtts_performance_combo.currentData()),
            worker_count=int(self.xtts_workers_combo.currentData()),
            reference_wav=reference,
            parent=self,
        )
        self.benchmark_worker.log_message.connect(self.log.appendPlainText)
        self.benchmark_worker.benchmark_ready.connect(self._benchmark_ready)
        self.benchmark_worker.failed.connect(self._benchmark_failed)
        self.benchmark_worker.start()

    def _benchmark_ready(self, result: dict) -> None:
        self.xtts_benchmark_btn.setEnabled(True)
        factor = float(result.get("realtime_factor") or 0.0)
        workers = int(result.get("workers") or 1)
        requested_raw = result.get("requested_workers")
        requested = int(requested_raw) if requested_raw is not None else workers
        mode = str(result.get("effective_performance_mode") or "?")
        vram = result.get("vram_workers_allocated_gb") or result.get("vram_allocated_gb")
        device_used = result.get("vram_device_used_gb")
        device_total = result.get("vram_device_total_gb") or result.get("vram_total_gb")
        target = "HEDEF GECILDI" if factor >= 4.0 else f"4.00x hedefinin %{min(999, round(factor / 4.0 * 100))}'i"
        if requested == AUTO_WORKERS:
            worker_text = f"AutoTune -> {workers} worker"
        else:
            worker_text = f"{workers} worker" if workers == requested else f"{workers}/{requested} worker (fallback)"
        text = f"Benchmark: {factor:.2f}x realtime | {worker_text} | mod={mode} | {target}"
        autotune_factors = result.get("autotune_factors") or {}
        if autotune_factors:
            table = " / ".join(
                f"{key}w={float(value):.2f}x" for key, value in sorted(autotune_factors.items(), key=lambda item: int(item[0]))
            )
            text += " | " + table
            # Benchmark already measured the chosen configuration; select it so
            # a subsequent conversion does not repeat the AutoTune warmup.
            chosen_index = self.xtts_workers_combo.findData(workers)
            if chosen_index >= 0:
                self.xtts_workers_combo.setCurrentIndex(chosen_index)
        if device_used is not None and device_total is not None:
            text += f" | cihaz VRAM {float(device_used):.1f}/{float(device_total):.1f} GB"
        if vram is not None:
            text += f" | worker PyTorch alloc ~{float(vram):.1f} GB"
        self.xtts_benchmark_result.setText(text)
        self.log.appendPlainText(text)

    def _benchmark_failed(self, message: str) -> None:
        self.xtts_benchmark_btn.setEnabled(True)
        self.xtts_benchmark_result.setText("Benchmark basarisiz: " + message)
        QMessageBox.warning(self, "XTTS benchmark", message)

    def _validate_xtts_aux_action(self) -> bool:
        if self.engine_id != "xtts":
            return False
        issues = dependency_issues("xtts")
        if issues:
            QMessageBox.warning(
                self,
                "XTTS bağımlılıkları eksik/uyumsuz",
                "Önce 'Bağımlılıkları Kur/Onar' düğmesini çalıştırın:\n\n- " + "\n- ".join(issues),
            )
            return False
        if not self.license_ack.isChecked():
            QMessageBox.warning(self, "Lisans onayı", "XTTS v2 model lisansını önce kabul etmelisiniz.")
            return False
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Dönüştürme sürüyor", "Ses önizleme işlemi dönüştürme bittikten sonra kullanılabilir.")
            return False
        if self.benchmark_worker and self.benchmark_worker.isRunning():
            QMessageBox.information(self, "Benchmark sürüyor", "Önce XTTS hız testinin tamamlanmasını bekleyin.")
            return False
        return True

    def _load_xtts_speakers(self) -> None:
        if not self._validate_xtts_aux_action():
            return
        if self.speaker_worker and self.speaker_worker.isRunning():
            return
        self.xtts_speakers_btn.setEnabled(False)
        self.log.appendPlainText("XTTS hazır speaker listesi modelden okunuyor...")
        self.speaker_worker = XTTSSpeakerWorker(
            device=str(self.device_combo.currentData()),
            accept_model_license=True,
            parent=self,
        )
        self.speaker_worker.log_message.connect(self.log.appendPlainText)
        self.speaker_worker.speakers_ready.connect(self._xtts_speakers_ready)
        self.speaker_worker.failed.connect(self._xtts_speakers_failed)
        self.speaker_worker.start()

    def _xtts_speakers_ready(self, speakers: list[str]) -> None:
        current = self.xtts_speaker_combo.currentText().strip() or DEFAULT_SPEAKER
        self.xtts_speaker_combo.clear()
        if speakers:
            self.xtts_speaker_combo.addItems(speakers)
            preferred = DEFAULT_SPEAKER if DEFAULT_SPEAKER in speakers else current
            index = self.xtts_speaker_combo.findText(preferred)
            self.xtts_speaker_combo.setCurrentIndex(index if index >= 0 else 0)
            self.log.appendPlainText(f"XTTS: {len(speakers)} hazır speaker bulundu.")
        else:
            self.xtts_speaker_combo.addItem(DEFAULT_SPEAKER)
            self.log.appendPlainText("XTTS speaker listesi boş döndü; önerilen varsayılan ses korunuyor.")
        self.xtts_speakers_btn.setEnabled(True)

    def _xtts_speakers_failed(self, message: str) -> None:
        self.xtts_speakers_btn.setEnabled(True)
        self.log.appendPlainText("XTTS speaker listesi alınamadı: " + message)
        QMessageBox.warning(self, "XTTS speaker listesi", message)

    def _preview_xtts(self) -> None:
        if not self._validate_xtts_aux_action():
            return
        if self.preview_worker and self.preview_worker.isRunning():
            return

        voice_mode = str(self.xtts_mode_combo.currentData())
        reference: Path | None = None
        if voice_mode == VOICE_MODE_CLONE:
            text = self.reference_edit.text().strip()
            reference = Path(text) if text else None
            if reference is None or not reference.is_file():
                QMessageBox.warning(self, "Referans ses", "Voice cloning önizlemesi için geçerli bir referans ses seçin.")
                return
            if not self.voice_consent.isChecked():
                QMessageBox.warning(self, "Ses izni", "Referans sesi kullanma/klonlama iznini onaylayın.")
                return

        self.xtts_preview_btn.setEnabled(False)
        self.xtts_play_btn.setEnabled(False)
        self.log.appendPlainText("XTTS kısa ses önizlemesi üretiliyor...")
        self.preview_worker = XTTSPreviewWorker(
            device=str(self.device_combo.currentData()),
            accept_model_license=True,
            voice_mode=voice_mode,
            speaker=self.xtts_speaker_combo.currentText().strip() or DEFAULT_SPEAKER,
            speed=float(self.xtts_speed.value()),
            performance_mode=str(self.xtts_performance_combo.currentData()),
            reference_wav=reference,
            preview_text=XTTS_PREVIEW_TEXT,
            parent=self,
        )
        self.preview_worker.log_message.connect(self.log.appendPlainText)
        self.preview_worker.preview_ready.connect(self._xtts_preview_ready)
        self.preview_worker.failed.connect(self._xtts_preview_failed)
        self.preview_worker.start()

    def _xtts_preview_ready(self, output: str) -> None:
        self.xtts_preview_btn.setEnabled(True)
        self.last_preview_path = Path(output)
        self.xtts_play_btn.setEnabled(True)
        self.log.appendPlainText(f"XTTS önizleme hazır: {output}")
        self._play_xtts_preview()

    def _xtts_preview_failed(self, message: str) -> None:
        self.xtts_preview_btn.setEnabled(True)
        self.log.appendPlainText("XTTS önizleme hatası: " + message)
        QMessageBox.warning(self, "XTTS önizleme", message)

    def _play_xtts_preview(self) -> None:
        if not self.last_preview_path or not self.last_preview_path.is_file():
            return
        self.media_player.stop()
        self.media_player.setSource(QUrl.fromLocalFile(str(self.last_preview_path)))
        self.media_player.play()

    def _refresh_dependency_status(self) -> None:
        issues = dependency_issues(self.engine_id)
        ffmpeg = ffmpeg_installed()
        if not issues and ffmpeg:
            self.dep_status.setText("Hazır ✓")
        else:
            parts = []
            if issues:
                parts.append("Python: " + "; ".join(issues))
            if not ffmpeg:
                parts.append("FFmpeg eksik")
            self.dep_status.setText("Eksik/Uyumsuz — " + "; ".join(parts))
        self.dep_status.setWordWrap(True)
        self.install_dep_btn.setEnabled(not (self.dep_worker and self.dep_worker.isRunning()))

    def _install_dependencies(self) -> None:
        if self.dep_worker and self.dep_worker.isRunning():
            return
        self.log.appendPlainText(f"[{self.engine_id}] bağımlılık kurulumu başlatılıyor...")
        if not ffmpeg_installed():
            self.log.appendPlainText("FFmpeg Python paketi değildir. scripts/install_windows.bat veya install_linux.sh bunu ayrıca kurabilir.")
        self.install_dep_btn.setEnabled(False)
        self.dep_worker = DependencyWorker(self.engine_id, self)
        self.dep_worker.log_message.connect(self.log.appendPlainText)
        self.dep_worker.succeeded.connect(self._dependencies_done)
        self.dep_worker.failed.connect(self._dependencies_failed)
        self.dep_worker.start()

    def _dependencies_done(self) -> None:
        self.log.appendPlainText("Bağımlılıklar kuruldu/onarıldı ve çalışma zamanı import testi geçti.")
        self._refresh_dependency_status()
        answer = QMessageBox.question(
            self,
            "Bağımlılıklar hazır",
            "Paketler güncellendi. Python daha önce yüklenmiş eski modülleri bellekte tutabileceği için "
            "uygulamayı yeniden başlatmak en güvenli seçenektir.\n\nŞimdi yeniden başlatılsın mı?",
        )
        if answer == QMessageBox.Yes:
            started = QProcess.startDetached(sys.executable, ["-m", "epub2m4b.app"])
            if isinstance(started, tuple):
                started = started[0]
            if started:
                app = QApplication.instance()
                if app is not None:
                    app.quit()
            else:
                QMessageBox.warning(
                    self,
                    "Yeniden başlatma",
                    "Yeni uygulama süreci başlatılamadı. Uygulamayı kapatıp scripts\\run_windows.bat ile yeniden açın.",
                )

    def _dependencies_failed(self, message: str) -> None:
        self.log.appendPlainText("Bağımlılık kurulumu başarısız: " + message)
        self.install_dep_btn.setEnabled(True)

    def _start(self) -> None:
        epub_path = Path(self.epub_edit.text().strip())
        output_path = Path(self.output_edit.text().strip())
        info = ENGINE_CLASSES[self.engine_id].info

        if not epub_path.is_file():
            QMessageBox.warning(self, "Eksik EPUB", "Geçerli bir EPUB dosyası seçin.")
            return
        if not output_path.name:
            QMessageBox.warning(self, "Eksik çıktı", "M4B çıktı dosyasını seçin.")
            return
        if not ffmpeg_installed():
            QMessageBox.warning(self, "FFmpeg eksik", "FFmpeg bulunamadı. Önce scripts/install_windows.bat veya install_linux.sh çalıştırın.")
            return
        issues = dependency_issues(self.engine_id)
        if issues:
            answer = QMessageBox.question(
                self,
                "Bağımlılıklar eksik/uyumsuz",
                "Tespit edilen sorunlar:\n- " + "\n- ".join(issues) + "\n\nŞimdi onarılsın mı?",
            )
            if answer == QMessageBox.Yes:
                self._install_dependencies()
            return

        resolved_epub = epub_path.resolve()
        if self.current_book is None or self.current_epub_path != resolved_epub:
            if not self._analyze_epub():
                QMessageBox.warning(self, "EPUB analizi", "EPUB analiz edilemedi.")
                return
        selected_chapters = self._selected_chapter_indices()
        if not selected_chapters:
            QMessageBox.warning(self, "Bölüm seçimi", "En az bir içerik/bölüm seçmelisiniz.")
            return
        if info.requires_license_ack and not self.license_ack.isChecked():
            QMessageBox.warning(self, "Lisans onayı", "Seçili modelin lisans koşullarını kabul etmelisiniz.")
            return

        if (
            (self.speaker_worker and self.speaker_worker.isRunning())
            or (self.preview_worker and self.preview_worker.isRunning())
            or (self.benchmark_worker and self.benchmark_worker.isRunning())
        ):
            QMessageBox.information(self, "XTTS işlemi sürüyor", "Önce speaker/önizleme/benchmark işleminin tamamlanmasını bekleyin.")
            return

        engine_options: dict[str, object] = {}
        reference = Path(self.reference_edit.text().strip()) if self.reference_edit.text().strip() else None
        reference_required = info.needs_reference_audio
        if self.engine_id == "xtts":
            voice_mode = str(self.xtts_mode_combo.currentData())
            engine_options = {
                "voice_mode": voice_mode,
                "speaker": self.xtts_speaker_combo.currentText().strip() or DEFAULT_SPEAKER,
                "speed": float(self.xtts_speed.value()),
                "performance_mode": str(self.xtts_performance_combo.currentData()),
                "worker_count": int(self.xtts_workers_combo.currentData()),
            }
            reference_required = voice_mode == VOICE_MODE_CLONE
            if not reference_required:
                reference = None

        if reference_required:
            if reference is None or not reference.is_file():
                QMessageBox.warning(self, "Referans ses", "XTTS için geçerli bir referans ses dosyası seçin.")
                return
            if not self.voice_consent.isChecked():
                QMessageBox.warning(self, "Ses izni", "Referans sesi kullanma/klonlama iznini onaylayın.")
                return

        options = PipelineOptions(
            epub_path=epub_path,
            output_path=output_path,
            engine_id=self.engine_id,
            quality_key=str(self.quality_combo.currentData()),
            device=str(self.device_combo.currentData()),
            reference_wav=reference,
            accept_model_license=self.license_ack.isChecked(),
            voice_consent=self.voice_consent.isChecked() if reference_required else False,
            keep_work_files=self.keep_work.isChecked(),
            engine_options=engine_options,
            selected_chapter_indices=selected_chapters,
        )

        self.log.clear()
        self.progress.setValue(0)
        self.performance_status.setText("Performans olculuyor...")
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.worker = ConversionWorker(options, self)
        self.worker.log_message.connect(self.log.appendPlainText)
        self.worker.progress_changed.connect(self._progress)
        self.worker.stats_changed.connect(self._stats)
        self.worker.succeeded.connect(self._success)
        self.worker.failed.connect(self._failure)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.start()

    def _progress(self, done: int, total: int, message: str) -> None:
        percent = round(done * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.progress.setFormat(f"%p% — {message}")

    def _stats(self, payload: dict) -> None:
        parts: list[str] = []
        gpu_name = payload.get("gpu_name")
        if gpu_name:
            gpu = str(gpu_name)
            util = payload.get("gpu_util_percent")
            if util is not None:
                gpu += f" %{int(util)}"
            power = payload.get("power_w")
            if power is not None:
                gpu += f" / {int(power)} W"
            device_used = payload.get("vram_device_used_gb")
            device_total = payload.get("vram_device_total_gb") or payload.get("vram_total_gb")
            workers_allocated = payload.get("vram_workers_allocated_gb")
            allocated = payload.get("vram_allocated_gb")
            if device_used is not None and device_total is not None:
                gpu += f" / VRAM cihaz {float(device_used):.1f}/{float(device_total):.1f} GB"
            elif allocated is not None and device_total is not None:
                gpu += f" / VRAM {float(allocated):.1f}/{float(device_total):.1f} GB"
            if workers_allocated is not None:
                gpu += f" / XTTS worker {float(workers_allocated):.1f} GB"
            parts.append(gpu)
        else:
            parts.append("Aygit: " + str(payload.get("device", "?")))

        factor = float(payload.get("realtime_factor") or 0.0)
        if factor > 0:
            parts.append(f"Uretim hizi: {factor:.2f}x realtime")
        elif payload.get("eta_warmup"):
            parts.append("Uretim hizi: isiniyor")
        workers = payload.get("effective_workers") or payload.get("workers")
        requested_workers = payload.get("requested_workers")
        worker_mode = str(payload.get("worker_mode") or "")
        if workers:
            if worker_mode == "auto" or requested_workers == AUTO_WORKERS:
                parts.append(f"Worker: Auto->{int(workers)}")
            elif requested_workers and int(requested_workers) != int(workers):
                parts.append(f"Worker: {int(workers)}/{int(requested_workers)} fallback")
            else:
                parts.append(f"Worker: {int(workers)}")
        mode = payload.get("effective_performance_mode")
        if mode:
            parts.append("Mod: " + str(mode))
        worker_factor = float(payload.get("worker_realtime_factor") or 0.0)
        if worker_factor > 0 and int(workers or 1) > 1:
            parts.append(f"Tek-worker verimi: {worker_factor:.2f}x")
        worker_factors = payload.get("worker_realtime_factors") or {}
        if worker_factors and int(workers or 1) > 1:
            values = [float(value) for value in worker_factors.values() if float(value) > 0]
            if values:
                parts.append(f"Worker araligi: {min(values):.2f}-{max(values):.2f}x")
        eta = payload.get("eta_seconds")
        if eta is not None:
            parts.append("Kalan: " + self._format_duration(float(eta)))
        generated = float(payload.get("generated_audio_seconds") or 0.0)
        if generated > 0:
            parts.append("Uretilen ses: " + self._format_duration(generated))
        cache_hits = int(payload.get("cache_hits") or 0)
        if cache_hits:
            parts.append(f"Cache: {cache_hits} parca")
        self.performance_status.setText(" | ".join(parts))

    @staticmethod
    def _format_duration(value: float) -> str:
        seconds = max(0, int(round(value)))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours} sa {minutes:02d} dk"
        if minutes:
            return f"{minutes} dk {seconds:02d} sn"
        return f"{seconds} sn"

    def _finish_ui(self) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _success(self, output: str) -> None:
        self.progress.setValue(100)
        self._finish_ui()
        QMessageBox.information(self, "Tamamlandı", f"M4B oluşturuldu:\n{output}")

    def _failure(self, message: str) -> None:
        self._finish_ui()
        self.log.appendPlainText("HATA: " + message)
        QMessageBox.critical(self, "Dönüştürme hatası", message)

    def _cancelled(self, message: str) -> None:
        self._finish_ui()
        self.log.appendPlainText(message)

    def _cancel(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.log.appendPlainText("İptal isteği alındı; mevcut TTS parçası tamamlanınca durdurulacak...")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            event.ignore()
            QMessageBox.information(self, "İşlem sürüyor", "Önce işlem iptal edilip worker sonlanmalıdır.")
            return
        if (
            (self.speaker_worker and self.speaker_worker.isRunning())
            or (self.preview_worker and self.preview_worker.isRunning())
            or (self.benchmark_worker and self.benchmark_worker.isRunning())
            or (self.deepspeed_worker and self.deepspeed_worker.isRunning())
        ):
            event.ignore()
            QMessageBox.information(
                self,
                "XTTS işlemi sürüyor",
                "Model yükleme/önizleme/benchmark/kurulum işlemi tamamlandıktan sonra kapatın.",
            )
            return
        event.accept()
