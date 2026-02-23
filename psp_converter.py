import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import threading
import queue
import json
import platform
import subprocess
from PIL import Image
import sys
import re
import random
from datetime import datetime

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class PSPVideoConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("PSP Video Converter — Final")
        self.root.geometry("900x720")
        self.root.resizable(True, True)

        self.input_folder = None
        self.thumb_path = None
        self.is_running = False
        self.stop_requested = False
        self.queue = queue.Queue()
        self.total_files = 0
        self.current_progress = 0
        self.current_process = None

        # Находим ffmpeg
        self.ffmpeg_path = self.find_ffmpeg()
        
        self.gpu_type = ctk.StringVar(value="CPU (программное)")  # По умолчанию CPU для надежности
        self.available_encoders = self._detect_encoders()
        self.gpu_info = self._detect_gpu()

        self._create_widgets()
        self._update_ui_from_queue()
        self._log_available_encoders()

    def find_ffmpeg(self):
        """Поиск ffmpeg в системе Windows"""
        possible_paths = [
            "ffmpeg",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
            os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "ffmpeg.exe"),
        ]
        
        for path in possible_paths:
            try:
                if path == "ffmpeg":
                    result = subprocess.run(["where", "ffmpeg"], capture_output=True, text=True, shell=True)
                    if result.returncode == 0:
                        ffmpeg_path = result.stdout.strip().split('\n')[0]
                        return ffmpeg_path
                elif os.path.exists(path):
                    return path
            except:
                continue
        
        # Если не нашли, показываем диалог
        self.log("FFmpeg не найден. Выберите ffmpeg.exe вручную.", "warning")
        ffmpeg_path = filedialog.askopenfilename(
            title="Выберите ffmpeg.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
        )
        
        if ffmpeg_path and os.path.exists(ffmpeg_path):
            return ffmpeg_path
        else:
            messagebox.showerror("Ошибка", 
                "FFmpeg не найден!\n\n"
                "Скачайте ffmpeg с https://www.gyan.dev/ffmpeg/builds/\n"
                "и распакуйте в C:\\ffmpeg\\")
            return None

    def _detect_gpu(self):
        """Определение конкретной модели GPU"""
        gpu_info = {"vendor": "unknown", "model": "unknown", "supports_amf": False}
        
        try:
            # Пробуем через PowerShell получить информацию о GPU
            ps_command = """
            Get-WmiObject Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json
            """
            
            result = subprocess.run(
                ["powershell", "-Command", ps_command],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    gpu_data = json.loads(result.stdout)
                    if isinstance(gpu_data, list):
                        gpu_data = gpu_data[0]
                    
                    gpu_name = gpu_data.get("Name", "").lower()
                    
                    # Определяем производителя
                    if "nvidia" in gpu_name:
                        gpu_info["vendor"] = "nvidia"
                        gpu_info["model"] = gpu_data.get("Name", "NVIDIA GPU")
                    elif "amd" in gpu_name or "radeon" in gpu_name:
                        gpu_info["vendor"] = "amd"
                        gpu_info["model"] = gpu_data.get("Name", "AMD Radeon GPU")
                        gpu_info["supports_amf"] = True
                    elif "intel" in gpu_name:
                        gpu_info["vendor"] = "intel"
                        gpu_info["model"] = gpu_data.get("Name", "Intel GPU")
                except:
                    pass
        except:
            pass
            
        return gpu_info

    def _detect_encoders(self):
        """Определение доступных GPU-энкодеров"""
        encoders = {"nvenc": False, "amf": False, "qsv": False}
        
        if not self.ffmpeg_path:
            return encoders
        
        try:
            # Проверяем энкодеры
            result = subprocess.run([self.ffmpeg_path, "-encoders"], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=8)
            out = result.stdout.lower()
            
            # AMD AMF
            encoders["amf"] = "h264_amf" in out
            
            # NVIDIA NVENC
            encoders["nvenc"] = "h264_nvenc" in out
            
            # Intel QSV
            encoders["qsv"] = "h264_qsv" in out
                    
        except subprocess.TimeoutExpired:
            self.log("Таймаут при проверке энкодеров", "warning")
        except Exception as e:
            self.log(f"Ошибка проверки энкодеров: {e}", "warning")
        
        return encoders

    def _log_available_encoders(self):
        if not self.ffmpeg_path:
            self.log("❌ FFMPEG НЕ НАЙДЕН!", "error")
            return
        
        # Информация о GPU
        self.log(f"\n🔍 Обнаружено GPU: {self.gpu_info['model']}", "info")
        self.log(f"   Производитель: {self.gpu_info['vendor'].upper()}")
        
        lines = ["\n📊 Доступные энкодеры:"]
        
        # AMD
        if self.available_encoders["amf"]:
            lines.append("  ✅ AMD AMF (H.264) - для AMD")
        else:
            lines.append("  ❌ AMD AMF - не обнаружен")
        
        # NVIDIA
        if self.available_encoders["nvenc"]:
            lines.append("  ✅ NVIDIA NVENC")
        else:
            lines.append("  ❌ NVIDIA NVENC - не обнаружен")
        
        # Intel
        if self.available_encoders["qsv"]:
            lines.append("  ✅ Intel QSV")
        else:
            lines.append("  ❌ Intel QSV - не обнаружен")
        
        # CPU
        lines.append("  ✅ CPU (libx264) - РЕКОМЕНДУЕТСЯ для PSP")
        
        self.log("\n".join(lines))

    def _create_widgets(self):
        # Папка
        f_top = ctk.CTkFrame(self.root)
        f_top.pack(pady=8, padx=10, fill="x")
        ctk.CTkLabel(f_top, text="Папка с видео:").pack(side="left", padx=10)
        self.entry_folder = ctk.CTkEntry(f_top, width=450)
        self.entry_folder.pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkButton(f_top, text="Обзор", command=self.select_folder, width=90).pack(side="left")

        # Thumbnail
        f_thumb = ctk.CTkFrame(self.root)
        f_thumb.pack(pady=8, padx=10, fill="x")
        ctk.CTkLabel(f_thumb, text="Обложка .THM:").pack(side="left", padx=10)
        self.entry_thumb = ctk.CTkEntry(f_thumb, width=450, placeholder_text="160x120 пикселей")
        self.entry_thumb.pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkButton(f_thumb, text="Обзор", command=self.select_thumb, width=90).pack(side="left")

        # GPU Info Frame
        f_gpu_info = ctk.CTkFrame(self.root)
        f_gpu_info.pack(pady=8, padx=10, fill="x")
        
        # GPU Selection
        ctk.CTkLabel(f_gpu_info, text="🖥️ Режим кодирования:").pack(side="left", padx=10)

        options = ["CPU (программное) - РЕКОМЕНДУЕТСЯ"]
        
        # Добавляем опции GPU если доступны
        if self.available_encoders["amf"]:
            options.append("AMD AMF (экспериментально)")
        if self.available_encoders["nvenc"]:
            options.append("NVIDIA NVENC (экспериментально)")
        if self.available_encoders["qsv"]:
            options.append("Intel QSV (экспериментально)")

        self.gpu_combo = ctk.CTkComboBox(f_gpu_info, values=options, variable=self.gpu_type, width=250)
        self.gpu_combo.pack(side="left", padx=10)

        # Статус GPU
        gpu_status = f"Обнаружено: {self.gpu_info['model'][:40]}"
        self.gpu_status_label = ctk.CTkLabel(f_gpu_info, text=gpu_status, text_color="#88FF88")
        self.gpu_status_label.pack(side="left", padx=10)

        # PSP Info Frame
        f_psp_info = ctk.CTkFrame(self.root)
        f_psp_info.pack(pady=5, padx=10, fill="x")
        
        psp_info = "🎮 Параметры для PSP: 320x240 (4:3) или 368x208 (16:9), 29.97fps, H.264, AAC"
        ctk.CTkLabel(f_psp_info, text=psp_info, text_color="#FFAA00").pack(pady=2)

        # Основные кнопки
        btn_frame = ctk.CTkFrame(self.root)
        btn_frame.pack(pady=10)
        
        self.btn_start = ctk.CTkButton(btn_frame, text="▶ Начать конвертацию", fg_color="#00C853", 
                                      command=self.start_conversion, width=200, height=40,
                                      state="normal" if self.ffmpeg_path else "disabled")
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ctk.CTkButton(btn_frame, text="⏹ Остановить", fg_color="#D32F2F", 
                                     command=self.request_stop, state="disabled", width=150, height=40)
        self.btn_stop.pack(side="left", padx=5)

        self.btn_rename = ctk.CTkButton(btn_frame, text="📝 Переименовать для PSP", 
                                        command=self.rename_to_psp_format, width=180, height=40)
        self.btn_rename.pack(side="left", padx=5)

        # Прогресс
        self.progressbar = ctk.CTkProgressBar(self.root, width=800, height=15)
        self.progressbar.pack(pady=10, padx=10)
        self.progressbar.set(0)
        
        self.progress_label = ctk.CTkLabel(self.root, text="Готов к работе")
        self.progress_label.pack()

        # Лог
        ctk.CTkLabel(self.root, text="📋 Лог конвертации:").pack(anchor="w", padx=15)
        self.log_text = ctk.CTkTextbox(self.root, height=300, font=("Consolas", 10))
        self.log_text.pack(pady=8, padx=15, fill="both", expand=True)

    def log(self, msg, tag=None):
        self.queue.put(("log", msg, tag))

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.input_folder = folder
            self.entry_folder.delete(0, ctk.END)
            self.entry_folder.insert(0, folder)
            self.log(f"📁 Папка: {folder}")

    def select_thumb(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.png *.bmp")])
        if path:
            self.thumb_path = path
            self.entry_thumb.delete(0, ctk.END)
            self.entry_thumb.insert(0, path)
            self.log(f"🖼️ Обложка: {os.path.basename(path)}")

    def start_conversion(self):
        if not self.input_folder:
            messagebox.showwarning("Ошибка", "Выберите папку!")
            return
        if not self.ffmpeg_path:
            messagebox.showerror("Ошибка", "FFmpeg не найден!")
            return
        if self.is_running:
            return

        self.is_running = True
        self.stop_requested = False
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_rename.configure(state="disabled")
        self.progressbar.set(0)
        self.progress_label.configure(text="Конвертация...")
        self.log("─" * 80)
        self.log(f"🚀 Запуск с профилем: {self.gpu_type.get()}")
        self.log(f"📊 GPU: {self.gpu_info['model']}")

        threading.Thread(target=self._process_folder, daemon=True).start()

    def request_stop(self):
        self.stop_requested = True
        self.log("⏹ Остановка...", "warning")
        if self.current_process:
            try:
                self.current_process.terminate()
            except:
                pass

    def rename_to_psp_format(self):
        """Переименование существующих файлов в формат PSP"""
        if not self.input_folder:
            messagebox.showwarning("Ошибка", "Выберите папку!")
            return
        
        psp_video_dir = os.path.join(self.input_folder, "MP_ROOT", "100ANV01")
        if not os.path.exists(psp_video_dir):
            messagebox.showinfo("Информация", "Папка PSP не найдена. Сначала сконвертируйте видео.")
            return
        
        files = [f for f in os.listdir(psp_video_dir) if f.endswith('_PSP.mp4') or f.endswith('.MP4') and not f.startswith('M4V')]
        
        if not files:
            self.log("Нет файлов для переименования")
            return
        
        renamed = 0
        
        for file in files:
            old_path = os.path.join(psp_video_dir, file)
            file_number = random.randint(10000, 99999)
            new_name = f"M4V{file_number}.MP4"
            new_path = os.path.join(psp_video_dir, new_name)
            
            # Проверяем, не существует ли уже файл с таким именем
            while os.path.exists(new_path):
                file_number = random.randint(10000, 99999)
                new_name = f"M4V{file_number}.MP4"
                new_path = os.path.join(psp_video_dir, new_name)
            
            os.rename(old_path, new_path)
            
            # Создаем информационный файл
            info_file = os.path.join(psp_video_dir, f"{os.path.splitext(file)[0]}.txt")
            with open(info_file, 'w', encoding='utf-8') as f:
                f.write(f"Оригинальный файл: {file}\n")
                f.write(f"PSP файл: {new_name}\n")
                f.write(f"Дата: {self._get_current_time()}\n")
            
            renamed += 1
            self.log(f"  ✅ {file} -> {new_name}")
        
        self.log(f"📝 Переименовано файлов: {renamed}")

    def _process_folder(self):
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mpg', '.m4v'}
        files = [os.path.join(r, f) for r, _, fs in os.walk(self.input_folder) for f in fs if os.path.splitext(f)[1].lower() in video_exts]

        self.total_files = len(files)
        if not self.total_files:
            self.queue.put(("warn", "Видео не найдены"))
            self._finish()
            return

        self.log(f"\n📊 Найдено файлов: {self.total_files}")

        for i, fp in enumerate(files, 1):
            if self.stop_requested:
                self.log("⏹ Прервано пользователем", "warning")
                break

            rel_path = os.path.relpath(fp, self.input_folder)
            self.log(f"\n[{i}/{self.total_files}] 📹 {rel_path}")
            
            try:
                self._convert_one_file(fp)
            except Exception as e:
                self.log(f"  ❌ Ошибка: {str(e)}", "error")

            self.current_progress = i / self.total_files
            self.queue.put(("progress", self.current_progress, f"{i}/{self.total_files}"))

        if not self.stop_requested:
            self.queue.put(("success", "✨ Конвертация завершена!"))
        self._finish()

    def _finish(self):
        self.queue.put(("finish", None))

    def _get_encoder_config(self, choice):
        """Получение конфигурации энкодера"""
        if "CPU" in choice:
            return self._get_cpu_config()
        elif "AMD" in choice:
            return self._get_amf_config()
        elif "NVIDIA" in choice:
            return self._get_nvenc_config()
        elif "Intel" in choice:
            return self._get_qsv_config()
        else:
            return self._get_cpu_config()

    def _get_amf_config(self):
        """Конфигурация для AMD AMF"""
        return {
            "vcodec": "h264_amf",
            "params": [
                "-quality", "speed",
                "-rc", "cbr",
                "-profile", "100",  # 100 = baseline
                "-level", "30",
                "-bf", "0",
                "-usage", "transcoding",
            ],
            "log": "🎮 Используется AMD AMF (экспериментально)"
        }

    def _get_nvenc_config(self):
        """Конфигурация для NVIDIA NVENC"""
        return {
            "vcodec": "h264_nvenc",
            "params": [
                "-preset", "p4",
                "-tune", "hq",
                "-profile:v", "baseline",
                "-level:v", "30",
                "-rc", "cbr",
                "-bf", "0",
            ],
            "log": "🎮 Используется NVIDIA NVENC (экспериментально)"
        }

    def _get_qsv_config(self):
        """Конфигурация для Intel QSV"""
        return {
            "vcodec": "h264_qsv",
            "params": [
                "-preset", "fast",
                "-profile:v", "baseline",
                "-level:v", "30",
                "-rc_mode", "CBR",
                "-bf", "0",
            ],
            "log": "🎮 Используется Intel QSV (экспериментально)"
        }

    def _get_cpu_config(self):
        """Конфигурация для CPU (рекомендуется для PSP)"""
        return {
            "vcodec": "libx264",
            "params": [
                "-preset", "fast",
                "-tune", "fastdecode",
                "-profile:v", "baseline",
                "-level:v", "30",
                "-crf", "23",
                "-threads", "0",
                "-bf", "0",
                "-refs", "1",
                "-weightp", "0",
            ],
            "log": "💻 Используется CPU (рекомендуется для PSP)"
        }

    def _convert_one_file(self, input_file):
        if not self.ffmpeg_path:
            raise Exception("FFmpeg не найден")

        # Исправляем пути для Windows
        input_file = os.path.normpath(input_file)
        
        # Создаем безопасное имя файла
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        safe_base_name = re.sub(r'[<>:"/\\|?*\[\]&]', '_', base_name)
        
        output_dir = os.path.dirname(input_file)
        
        # PSP требует строгую структуру папок
        psp_root = os.path.join(output_dir, "MP_ROOT")
        psp_video_dir = os.path.join(psp_root, "100ANV01")
        
        try:
            os.makedirs(psp_video_dir, exist_ok=True)
            self.log(f"  📁 Создана структура папок: MP_ROOT/100ANV01/")
        except Exception as e:
            self.log(f"  ⚠️ Ошибка создания папок: {e}", "warning")
            psp_video_dir = output_dir
        
        # Получаем информацию о видео для определения оптимальных параметров
        duration, size, width, height = self.get_video_info(input_file)
        
        # Определяем соотношение сторон
        aspect_ratio = width / height if height > 0 else 16/9
        
        # Выбираем оптимальное разрешение для PSP
        if abs(aspect_ratio - 4/3) < 0.2:  # 4:3 видео
            video_width, video_height = 320, 240
            self.log(f"  📐 Формат 4:3 -> 320x240")
        else:  # 16:9 видео
            video_width, video_height = 368, 208
            self.log(f"  📐 Формат 16:9 -> 368x208")
        
        # Битрейт для PSP
        video_bitrate = "768k"
        audio_bitrate = "128k"
        
        # Получаем конфигурацию энкодера
        encoder_config = self._get_encoder_config(self.gpu_type.get())
        self.log(encoder_config["log"])
        
        # Временный файл
        temp_output = os.path.join(output_dir, f"temp_{safe_base_name}.mp4")
        
        # Параметры для PSP
        cmd = [
            self.ffmpeg_path,
            "-i", input_file,
            # Видео параметры
            "-vf", f"scale={video_width}:{video_height}:force_original_aspect_ratio=decrease,pad={video_width}:{video_height}:(ow-iw)/2:(oh-ih)/2,fps=30000/1001",
            "-c:v", encoder_config["vcodec"],
            "-b:v", video_bitrate,
            "-maxrate", video_bitrate,
            "-bufsize", "1536k",
            "-pix_fmt", "yuv420p",
        ]
        
        # Добавляем параметры энкодера
        cmd.extend(encoder_config["params"])
        
        # Аудио параметры
        cmd.extend([
            "-c:a", "aac",
            "-b:a", audio_bitrate,
            "-ar", "44100",
            "-ac", "2",
        ])
        
        # Параметры контейнера
        cmd.extend([
            "-movflags", "+faststart",
            "-f", "mp4",
            "-map_metadata", "-1",
            "-metadata", "title=",
            "-metadata", "encoder=",
            "-y",
            temp_output
        ])
        
        self.log(f"  ⚙️ Битрейт видео: {video_bitrate}")
        self.log(f"  ⚙️ Битрейт аудио: {audio_bitrate}")
        self.log(f"  🚀 Запуск FFmpeg...")
        
        try:
            # Запускаем процесс
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            # Читаем stderr
            stderr_lines = []
            while True:
                if self.stop_requested:
                    self.current_process.terminate()
                    raise Exception("Остановлено пользователем")
                
                line = self.current_process.stderr.readline()
                if not line and self.current_process.poll() is not None:
                    break
                
                if line:
                    stderr_lines.append(line)
                    if "error" in line.lower() or "failed" in line.lower():
                        if "h264_amf" not in line.lower():  # Игнорируем ошибки AMF если используем CPU
                            self.log(f"  ⚠️ {line.strip()}", "warning")
            
            # Проверяем результат
            if self.current_process.returncode != 0:
                error_msg = ""
                for line in stderr_lines[-10:]:
                    if "error" in line.lower() or "failed" in line.lower():
                        error_msg += line + "\n"
                
                if not error_msg:
                    error_msg = '\n'.join(stderr_lines[-3:])
                
                raise Exception(f"FFmpeg ошибка (код {self.current_process.returncode})")
            
            # Проверяем созданный файл
            if os.path.exists(temp_output) and os.path.getsize(temp_output) > 100000:
                # Генерируем имя для PSP
                file_number = random.randint(10000, 99999)
                psp_filename = f"M4V{file_number}.MP4"
                final_output = os.path.join(psp_video_dir, psp_filename)
                
                # Проверяем уникальность имени
                while os.path.exists(final_output):
                    file_number = random.randint(10000, 99999)
                    psp_filename = f"M4V{file_number}.MP4"
                    final_output = os.path.join(psp_video_dir, psp_filename)
                
                # Перемещаем файл
                os.rename(temp_output, final_output)
                
                # Создаем информационный файл
                info_file = os.path.join(psp_video_dir, f"{safe_base_name[:20]}.txt")
                try:
                    with open(info_file, 'w', encoding='utf-8') as f:
                        f.write(f"Оригинальный файл: {base_name}\n")
                        f.write(f"PSP файл: {psp_filename}\n")
                        f.write(f"Разрешение: {video_width}x{video_height}\n")
                        f.write(f"Дата конвертации: {self._get_current_time()}\n")
                except:
                    pass
                
                self.log(f"  ✅ PSP файл создан: {psp_filename}", "success")
                self.log(f"  📁 Папка на PSP: MP_ROOT/100ANV01/")
                
                # Проверяем совместимость
                self._check_psp_compatibility(final_output)
                
                # Создание THM файла
                if self.thumb_path and os.path.exists(self.thumb_path):
                    try:
                        img = Image.open(self.thumb_path).convert("RGB")
                        img = img.resize((160, 120), Image.Resampling.LANCZOS)
                        thm_file = os.path.join(psp_video_dir, os.path.splitext(psp_filename)[0] + ".THM")
                        img.save(thm_file, "JPEG", quality=85, optimize=True)
                        
                        if os.path.exists(thm_file):
                            thm_size = os.path.getsize(thm_file)
                            self.log(f"  🖼️ THM создан: {thm_size} байт")
                    except Exception as e:
                        self.log(f"  ⚠️ Ошибка THM: {e}", "warning")
            else:
                raise Exception("Выходной файл не создан или слишком мал")
                    
        except Exception as e:
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except:
                    pass
            raise e
        finally:
            self.current_process = None

    def _get_current_time(self):
        """Получение текущего времени"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _check_psp_compatibility(self, video_file):
        """Проверка совместимости с PSP"""
        try:
            cmd = [self.ffmpeg_path, "-i", video_file]
            result = subprocess.run(cmd, capture_output=True, text=True)
            output = result.stderr
            
            self.log("  📊 Проверка совместимости с PSP:")
            
            checks = []
            warnings = []
            
            # Разрешение
            resolution_match = re.search(r"(\d+)x(\d+)", output)
            if resolution_match:
                width, height = int(resolution_match.group(1)), int(resolution_match.group(2))
                
                valid_resolutions = [
                    (320, 240), (368, 208), (320, 176), (384, 160), (416, 176)
                ]
                
                if (width, height) in valid_resolutions:
                    checks.append(f"  ✅ Разрешение: {width}x{height}")
                else:
                    warnings.append(f"  ⚠️ Разрешение {width}x{height} может не поддерживаться")
            
            # FPS
            if "29.97" in output or "30" in output or "30000/1001" in output:
                checks.append("  ✅ FPS: 29.97/30")
            else:
                warnings.append("  ⚠️ FPS должен быть 29.97 или 30")
            
            # Профиль
            if "baseline" in output.lower():
                checks.append("  ✅ Профиль: Baseline")
            elif "main" in output.lower():
                checks.append("  ✅ Профиль: Main (поддерживается)")
            else:
                warnings.append("  ⚠️ Профиль должен быть Baseline или Main")
            
            # Уровень
            if "Level 3" in output:
                checks.append("  ✅ Level: 3.0")
            
            # Аудио
            if "aac" in output.lower():
                checks.append("  ✅ Аудио кодек: AAC")
            
            if "44100 Hz" in output:
                checks.append("  ✅ Аудио частота: 44.1 kHz")
            
            # Выводим результаты
            for check in checks:
                self.log(check)
            
            if warnings:
                self.log("  ⚠️ Предупреждения:", "warning")
                for warning in warnings:
                    self.log(warning, "warning")
            
            if len(warnings) == 0:
                self.log("  ✅ Видео полностью совместимо с PSP!", "success")
            elif len(warnings) <= 2:
                self.log("  ⚠️ Видео должно работать на PSP", "warning")
            else:
                self.log("  ❌ Видео может не работать на PSP", "error")
                
        except Exception as e:
            self.log(f"  ⚠️ Ошибка проверки: {e}", "warning")

    def get_video_info(self, input_file):
        """Получение информации о видео"""
        try:
            cmd = [self.ffmpeg_path, "-i", input_file]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Длительность
            duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
            if duration_match:
                h, m, s = duration_match.groups()
                duration = int(h) * 3600 + int(m) * 60 + float(s)
            else:
                duration = 0
            
            # Разрешение
            video_match = re.search(r"Stream.*Video:.* (\d+)x(\d+)", result.stderr)
            if video_match:
                width = int(video_match.group(1))
                height = int(video_match.group(2))
            else:
                width = height = 0
            
            size = os.path.getsize(input_file)
            
            return duration, size, width, height
        except:
            return 0, 0, 0, 0

    def _update_ui_from_queue(self):
        while not self.queue.empty():
            item = self.queue.get()
            if item[0] == "log":
                msg = item[1]
                tag = item[2] if len(item) > 2 else None
                self.log_text.insert("end", msg + "\n")
                if tag:
                    last_line_start = self.log_text.index("end-2c linestart")
                    last_line_end = self.log_text.index("end-1c")
                    self.log_text.tag_add(tag, last_line_start, last_line_end)
                self.log_text.see("end")
            elif item[0] == "progress":
                self.progressbar.set(item[1])
                if len(item) > 2:
                    self.progress_label.configure(text=f"Прогресс: {item[2]}")
            elif item[0] == "warn":
                messagebox.showwarning("Внимание", item[1])
            elif item[0] == "error":
                messagebox.showerror("Ошибка", item[1])
            elif item[0] == "success":
                self.progress_label.configure(text="Готово!")
                messagebox.showinfo("Готово", item[1])
            elif item[0] == "finish":
                self.is_running = False
                self.btn_stop.configure(state="disabled")
                self.btn_start.configure(state="normal")
                self.btn_rename.configure(state="normal")
                self.progress_label.configure(text="Готов к работе")

        self.root.after(100, self._update_ui_from_queue)


if __name__ == "__main__":
    root = ctk.CTk()
    app = PSPVideoConverter(root)

    # Настройка цветов для тегов
    app.log_text.tag_config("success", foreground="#00FF00")
    app.log_text.tag_config("error", foreground="#FF4444")
    app.log_text.tag_config("warning", foreground="#FFAA00")
    app.log_text.tag_config("info", foreground="#88FF88")

    root.mainloop()