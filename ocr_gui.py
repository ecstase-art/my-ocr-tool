import os
import time
import zipfile
import io
import threading
import queue
import uuid
import json
import shutil
import tempfile
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import cv2
import pytesseract
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# ===== НАСТРОЙКИ =====
API_KEY = "sk-i7BjlvyEx7FuSu59A8oMk02pmTl6CQGt9M4wzkxGY8yFvl9J"
EXTENSIONS = ('.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
              '.png', '.jpg', '.jpeg', '.jp2', '.webp', '.gif', '.bmp')
OFFICE_EXTENSIONS = ('.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx')
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.jp2', '.webp', '.gif', '.bmp')
BATCH_SIZE = 20  # Уменьшение размера пакетов
MAX_RETRIES = 3
TIMEOUT = 3600
CHECKPOINT_FILE = "processed.json"

# ===== СЕССИЯ С ПОВТОРАМИ =====
def get_session():
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "PUT", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=5, pool_maxsize=5)  # Уменьшение числа потоков
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

session = get_session()

# ===== КОРРЕКЦИЯ ОРИЕНТАЦИИ ИЗОБРАЖЕНИЙ =====
def correct_image_orientation(image_path):
    try:
        img = cv2.imread(image_path)
        if img is None:
            return image_path

        try:
            osd_data = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
            angle = osd_data.get('orientation', 0)
            if angle == 180:
                rotated = cv2.rotate(img, cv2.ROTATE_180)
            elif angle == 90:
                rotated = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif angle == 270:
                rotated = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            else:
                return image_path
            temp_path = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name
            cv2.imwrite(temp_path, rotated)
            return temp_path
        except Exception as e:
            logging.error(f"Error processing image {image_path}: {e}")
        finally:
            os.remove(image_path)  # Удаление исходного изображения
            return temp_path
    except ImportError:
        return image_path

# ===== ГЛАВНОЕ ПРИЛОЖЕНИЕ =====
class OCRApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MinerU OCR – Пакетная обработка")
        self.root.geometry("650x580")
        self.root.resizable(True, True)
        self.folder_path = tk.StringVar()
        self.project_name = tk.StringVar()
        self.running = False
        self.log_queue = queue.Queue()
        self.progress_var = tk.IntVar()
        self.status_var = tk.StringVar(value="Готов к работе")
        self.create_widgets()
        self.root.after(100, self.process_log_queue)

    def create_widgets(self):
        # Папка
        tk.Label(self.root, text="Папка с файлами:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(self.root, textvariable=self.folder_path, width=50).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(self.root, text="Обзор...", command=self.browse_folder).grid(row=0, column=2, padx=5, pady=5)

        # Название проекта
        tk.Label(self.root, text="Название проекта:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(self.root, textvariable=self.project_name, width=50).grid(row=1, column=1, padx=5, pady=5)

        # Кнопка запуска
        self.btn_start = tk.Button(self.root, text="Запустить обработку", command=self.start_processing,
                                   bg="lightblue", font=("Arial", 10))
        self.btn_start.grid(row=2, column=0, columnspan=3, pady=10)

        # Статус
        tk.Label(self.root, text="Статус:").grid(row=3, column=0, sticky="w", padx=10)
        tk.Label(self.root, textvariable=self.status_var, font=("Arial", 9), fg="blue").grid(row=3, column=1, sticky="w", columnspan=2)

        # Прогресс-бар
        self.progress = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100, length=500)
        self.progress.grid(row=4, column=0, columnspan=3, padx=10, pady=5, sticky="ew")

        # Лог
        tk.Label(self.root, text="Лог обработки:").grid(row=5, column=0, sticky="w", padx=10)
        self.log_text = scrolledtext.ScrolledText(self.root, height=15, width=80, state="disabled")
        self.log_text.grid(row=6, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")
        self.root.grid_rowconfigure(6, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

    def browse_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку с документами")
        if folder:
            self.folder_path.set(folder)

    def log(self, msg):
        self.log_queue.put(msg)
        logging.debug(msg)  # Добавление логирования для отладки

    def set_status(self, msg):
        self.root.after(0, lambda: self.status_var.set(msg))

    def set_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(value))

    def process_log_queue(self):
        if self.log_queue.empty():
            self.root.after(100, self.process_log_queue)
            return

        messages = []
        while not self.log_queue.empty():
            messages.append(self.log_queue.get_nowait())

        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, "\n".join(messages) + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.root.after(100, self.process_log_queue)

    def show_error(self, msg):
        self.root.after(0, lambda: messagebox.showerror("Ошибка", msg))

    def show_completion(self, output_dir):
        self.root.after(0, lambda: self._show_completion_gui(output_dir))

    def _show_completion_gui(self, output_dir):
        top = tk.Toplevel(self.root)
        top.title("Готово!")
        top.geometry("420x160")
        top.transient(self.root)
        top.grab_set()
        tk.Label(top, text="✅ Все файлы обработаны!", font=("Arial", 12, "bold")).pack(pady=8)
        tk.Label(top, text=f"Результаты в:\n{output_dir}", font=("Arial", 10)).pack(pady=5)
        frame = tk.Frame(top)
        frame.pack(pady=10)

        def open_folder():
            try:
                os.startfile(output_dir)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не открыть папку:\n{e}")
            top.destroy()
            self.root.quit()

        def close_app():
            top.destroy()
            self.root.quit()

        tk.Button(frame, text="📂 Открыть папку", command=open_folder, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(frame, text="OK", command=close_app, width=10).pack(side=tk.LEFT, padx=5)

    def start_processing(self):
        if self.running:
            return
        folder = self.folder_path.get().strip()
        if not folder or not os.path.isdir(folder):
            self.show_error("Выберите существующую папку.")
            return
        proj = self.project_name.get().strip()
        if not proj:
            self.show_error("Введите название проекта.")
            return
        self.running = True
        self.btn_start.config(state="disabled")
        self.progress_var.set(0)
        self.status_var.set("Начинаем обработку...")
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
        threading.Thread(target=self.process, args=(folder, proj), daemon=True).start()

    def process(self, input_dir, project_name):
        try:
            output_dir = os.path.join(input_dir, project_name)
            os.makedirs(output_dir, exist_ok=True)
            self.log(f"📁 Результаты: {output_dir}")

            checkpoint_path = os.path.join(output_dir, CHECKPOINT_FILE)
            processed = set()
            if os.path.exists(checkpoint_path):
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    processed = set(json.load(f))
                self.log(f"⏳ Пропускаем {len(processed)} ранее обработанных")

            entries = []
            abs_output_dir = os.path.abspath(output_dir)
            for root, _, files in os.walk(input_dir):
                if os.path.abspath(root).startswith(abs_output_dir):
                    continue
                for f in files:
                    ext = Path(f).suffix.lower()
                    if ext not in EXTENSIONS:
                        continue
                    abs_path = os.path.join(root, f)
                    base = Path(f).stem
                    if base in processed:
                        continue
                    if os.path.exists(os.path.join(output_dir, base + ".html")):
                        self.log(f"  ⏩ {base} уже есть результат")
                        processed.add(base)
                        with open(checkpoint_path, "w", encoding="utf-8") as cp:
                            json.dump(list(processed), cp, ensure_ascii=False)
                        continue
                    entries.append((abs_path, base))

            if not entries:
                self.log("❌ Нет новых файлов.")
                self.show_error("Нет новых файлов.")
                return

            total_files = len(entries)
            self.log(f"📄 Найдено новых: {total_files}")
            self.set_status(f"Найдено {total_files} файлов. Обработка...")
            self.process_entries(entries, output_dir, checkpoint_path, processed, total_files)

            if os.path.exists(checkpoint_path):
                os.remove(checkpoint_path)

            self.set_status("Готово!")
            self.set_progress(100)
            self.log("\n🎉 Готово!")
            self.show_completion(output_dir)

        except Exception as e:
            self.log(f"❌ Ошибка: {e}")
            self.show_error(str(e))
        finally:
            self.running = False
            self.btn_start.config(state="normal")

    def process_entries(self, entries, output_dir, checkpoint_path, processed, total_files):
        if not entries:
            return

        api_mapping = {}
        for abs_path, base in entries:
            ext = Path(abs_path).suffix
            api_name = uuid.uuid4().hex + ext
            api_mapping[api_name] = (abs_path, base)

        api_items = list(api_mapping.items())
        total = len(api_items)
        processed_count = 0

        for i in range(0, total, BATCH_SIZE):
            batch = api_items[i:i+BATCH_SIZE]
            self.log(f"📦 Пакет {i//BATCH_SIZE + 1} ({len(batch)} файлов)")

            try:
                batch_id, upload_urls = self.get_upload_urls([x[0] for x in batch])
            except Exception as e:
                self.log(f"❌ Ошибка ссылок: {e}")
                self.show_error(str(e))
                return

            if not self.upload_files_with_retry([x[1][0] for x in batch], upload_urls):
                self.log("❌ Загрузка прервана.")
                return

            self.log("⏳ Ожидание...")
            results = self.poll_batch_result(batch_id)

            for api_name, zip_url in results.items():
                if api_name not in api_mapping:
                    continue
                abs_path, base = api_mapping[api_name]
                if zip_url and self.extract_and_save(zip_url, output_dir, base):
                    processed.add(base)
                    with open(checkpoint_path, "w", encoding="utf-8") as f:
                        json.dump(list(processed), f, ensure_ascii=False)
                    self.copy_office_original(abs_path, output_dir, base)
                else:
                    self.log(f"  ⚠️ {base} не обработан")

                processed_count += 1
                progress = int((processed_count / total_files) * 100)
                self.set_progress(progress)
                self.set_status(f"Обработано {processed_count} из {total_files} файлов")

            self.log("✅ Пакет завершён.\n")

    def copy_office_original(self, src_path, dst_dir, base_name):
        ext = Path(src_path).suffix.lower()
        if ext not in OFFICE_EXTENSIONS:
            return
        dst_name = base_name + ext
        dst_path = os.path.join(dst_dir, dst_name)
        if os.path.exists(dst_path):
            counter = 1
            while True:
                new_name = f"{base_name}_{counter}{ext}"
                new_path = os.path.join(dst_dir, new_name)
                if not os.path.exists(new_path):
                    dst_path = new_path
                    break
                counter += 1
        try:
            shutil.copy2(src_path, dst_path)
            self.log(f"  📂 Оригинал сохранён: {os.path.basename(dst_path)}")
        except Exception as e:
            self.log(f"  ❌ Ошибка копирования: {e}")

    # ===== API-ФУНКЦИИ =====
    def get_upload_urls(self, file_names, model_version="vlm"):
        url = "https://mineru.net/api/v4/file-urls/batch"
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        data = {
            "files": [{"name": name} for name in file_names],
            "model_version": model_version,
            "extra_formats": ["html"],
            "language": "east_slavic",
            "enable_table": True,
            "enable_formula": True,
            "is_ocr": True
        }
        resp = session.post(url, headers=headers, json=data, timeout=(10, 120))
        if resp.status_code != 200:
            raise Exception(f"Ошибка ссылок: {resp.text}")
        result = resp.json()
        if result["code"] != 0:
            raise Exception(f"API: {result['msg']}")
        return result["data"]["batch_id"], result["data"]["file_urls"]

    def upload_files_with_retry(self, file_paths, upload_urls):
        success = True
        for path, url in zip(file_paths, upload_urls):
            filename = os.path.basename(path)
            use_path = path
            if Path(path).suffix.lower() in IMAGE_EXTENSIONS:
                corrected = correct_image_orientation(path)
                if corrected != path:
                    use_path = corrected
                    self.log(f"  🔄 Ориентация скорректирована для {filename}")

            ok = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    with open(use_path, "rb") as f:
                        resp = session.put(url, data=f, timeout=(10, 180))
                    if resp.status_code in (200, 201):
                        self.log(f"  ✅ Загружен: {filename}")
                        ok = True
                        break
                    self.log(f"  ⚠️ Попытка {attempt}: {resp.status_code}")
                    time.sleep(2 ** attempt)
                except Exception as e:
                    self.log(f"  ⚠️ Попытка {attempt}: {e}")
                    time.sleep(2 ** attempt)
            if not ok:
                self.log(f"  ❌ Не удалось загрузить {filename}")
                success = False
            if use_path != path and os.path.exists(use_path):
                try:
                    os.unlink(use_path)
                except:
                    pass
        return success

    def poll_batch_result(self, batch_id, timeout=TIMEOUT, interval=5):
        url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        headers = {"Authorization": f"Bearer {API_KEY}"}
        start = time.time()
        done = {}
        while time.time() - start < timeout:
            try:
                resp = session.get(url, headers=headers, timeout=(10, 60))
            except:
                time.sleep(interval)
                continue
            if resp.status_code != 200:
                time.sleep(interval)
                continue
            result = resp.json()
            if result["code"] != 0:
                time.sleep(interval)
                continue
            for item in result["data"]["extract_result"]:
                fname = item["file_name"]
                state = item["state"]
                if state == "done":
                    if fname not in done:
                        done[fname] = item["full_zip_url"]
                        self.log(f"  ✅ Готов: {fname}")
                elif state == "failed":
                    self.log(f"  ❌ Ошибка {fname}: {item.get('err_msg', '')}")
                    done[fname] = None
            if len(done) == len(result["data"]["extract_result"]):
                break
            time.sleep(interval)
        return done

    def extract_and_save(self, zip_url, output_dir, base):
        try:
            resp = session.get(zip_url, timeout=(10, 120))
        except Exception as e:
            self.log(f"  ❌ Не скачать zip для {base}: {e}")
            return False
        if resp.status_code != 200:
            self.log(f"  ❌ Ошибка {resp.status_code} для {base}")
            return False

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                html_files = [n for n in zf.namelist() if n.endswith((".html", ".htm"))]
                if html_files:
                    content = zf.read(html_files[0]).decode("utf-8")
                else:
                    md_files = [n for n in zf.namelist() if n.endswith(".md")]
                    if md_files:
                        content = zf.read(md_files[0]).decode("utf-8")
                        try:
                            import markdown
                            content = markdown.markdown(content, extensions=["tables", "fenced_code"])
                        except:
                            content = f"<html><body><pre>{content}</pre></body></html>"
                    else:
                        self.log(f"  ❌ Нет HTML/MD в ZIP для {base}")
                        return False

                out_path = os.path.join(output_dir, base + ".html")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.log(f"  💾 Сохранено: {base}.html")
                return True
        except zipfile.BadZipFile:
            self.log(f"  ❌ Битый ZIP для {base}")
            return False
        except Exception as e:
            self.log(f"  ❌ Ошибка распаковки {base}: {e}")
            return False

if __name__ == "__main__":
    root = tk.Tk()
    OCRApp(root)
    root.mainloop()
