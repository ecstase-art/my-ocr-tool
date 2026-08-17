import os
import time
import zipfile
import io
import threading
import subprocess
from pathlib import Path
import requests
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox

# ===== НАСТРОЙКИ =====
API_KEY = "sk-i7BjlvyEx7FuSu59A8oMk02pmTl6CQGt9M4wzkxGY8yFvl9J"
EXTENSIONS = ('.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
              '.png', '.jpg', '.jpeg', '.jp2', '.webp', '.gif', '.bmp', '.html')
BATCH_SIZE = 50

class OCRApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MinerU OCR – Пакетная обработка (Markdown)")
        self.root.geometry("650x520")
        self.root.resizable(True, True)
        self.folder_path = tk.StringVar()
        self.project_name = tk.StringVar()
        self.running = False
        self.create_widgets()

    def create_widgets(self):
        tk.Label(self.root, text="Папка с файлами:", font=("Arial", 10)).grid(row=0, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(self.root, textvariable=self.folder_path, width=50).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(self.root, text="Обзор...", command=self.browse_folder).grid(row=0, column=2, padx=5, pady=5)

        tk.Label(self.root, text="Название проекта:", font=("Arial", 10)).grid(row=1, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(self.root, textvariable=self.project_name, width=50).grid(row=1, column=1, padx=5, pady=5)

        self.btn_start = tk.Button(self.root, text="Запустить обработку", command=self.start_processing, bg="lightblue", font=("Arial", 10))
        self.btn_start.grid(row=2, column=0, columnspan=3, pady=10)

        tk.Label(self.root, text="Лог обработки:", font=("Arial", 10)).grid(row=3, column=0, sticky="w", padx=10)
        self.log_text = scrolledtext.ScrolledText(self.root, height=15, width=80, state="disabled")
        self.log_text.grid(row=4, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")

        self.root.grid_rowconfigure(4, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

    def browse_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку с документами")
        if folder:
            self.folder_path.set(folder)

    def log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.root.update()

    def show_error(self, msg):
        messagebox.showerror("Ошибка", msg)

    def show_completion(self, output_dir):
        top = tk.Toplevel(self.root)
        top.title("Готово!")
        top.geometry("420x160")
        top.resizable(False, False)
        top.transient(self.root)
        top.grab_set()

        tk.Label(top, text="✅ Все файлы успешно обработаны!", font=("Arial", 12, "bold")).pack(pady=8)
        tk.Label(top, text=f"Результаты сохранены в:\n{output_dir}", font=("Arial", 10)).pack(pady=5)

        frame = tk.Frame(top)
        frame.pack(pady=10)

        def open_folder():
            subprocess.Popen(['explorer', output_dir])
            top.destroy()
            self.root.quit()

        def close_app():
            top.destroy()
            self.root.quit()

        btn_open = tk.Button(frame, text="📂 Открыть папку", command=open_folder, width=15)
        btn_open.pack(side=tk.LEFT, padx=5)
        btn_ok = tk.Button(frame, text="OK", command=close_app, width=10)
        btn_ok.pack(side=tk.LEFT, padx=5)

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
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
        threading.Thread(target=self.process, args=(folder, proj), daemon=True).start()

    def process(self, input_dir, project_name):
        try:
            output_dir = os.path.join(input_dir, project_name)
            os.makedirs(output_dir, exist_ok=True)
            self.log(f"📁 Результаты: {output_dir}")

            file_entries = []
            for root, dirs, files in os.walk(input_dir):
                if output_dir in root:
                    continue
                for f in files:
                    if Path(f).suffix.lower() in EXTENSIONS:
                        abs_path = os.path.join(root, f)
                        rel_path = os.path.relpath(root, input_dir)
                        if rel_path == ".":
                            rel_path = ""
                        file_entries.append((abs_path, rel_path, f))

            if not file_entries:
                self.log("❌ Нет поддерживаемых файлов.")
                self.show_error("Нет поддерживаемых файлов (PDF, JPG, PNG, DOCX, PPTX, XLSX).")
                return

            self.log(f"📄 Найдено файлов: {len(file_entries)}")

            for i in range(0, len(file_entries), BATCH_SIZE):
                batch = file_entries[i:i+BATCH_SIZE]
                file_names = [entry[2] for entry in batch]
                self.log(f"📦 Пакет {i//BATCH_SIZE + 1} ({len(batch)} файлов)")

                try:
                    batch_id, upload_urls = self.get_upload_urls(file_names)
                except Exception as e:
                    self.log(f"❌ Ошибка: {e}")
                    self.show_error(str(e))
                    return

                self.upload_files([entry[0] for entry in batch], upload_urls)
                self.log("⏳ Ожидание завершения...")
                results = self.poll_batch_result(batch_id)

                for fname, zip_url in results.items():
                    if not zip_url:
                        continue
                    for abs_path, rel_path, orig_fname in batch:
                        if orig_fname == fname:
                            base = Path(fname).stem
                            self.extract_and_save(zip_url, output_dir, rel_path, base)
                            break

                self.log("✅ Пакет завершён.\n")

            self.log("🎉 Все файлы обработаны!")
            self.show_completion(output_dir)

        except Exception as e:
            self.log(f"❌ Критическая ошибка: {e}")
            self.show_error(str(e))
        finally:
            self.running = False
            self.btn_start.config(state="normal")

    # ===== API-функции (обновлены: убран extra_formats) =====
    def get_upload_urls(self, file_names, model_version="vlm"):
        """Запрашивает ссылки для загрузки (без extra_formats, чтобы получить только Markdown)."""
        url = "https://mineru.net/api/v4/file-urls/batch"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "files": [{"name": name} for name in file_names],
            "model_version": model_version,
            # extra_formats НЕ передаём — вернётся только Markdown + JSON
            "language": "east_slavic",
            "enable_table": True,
            "enable_formula": True,
            "is_ocr": True
        }
        resp = requests.post(url, headers=headers, json=data)
        if resp.status_code != 200:
            raise Exception(f"Не удалось получить ссылки: {resp.text}")
        result = resp.json()
        if result["code"] != 0:
            raise Exception(f"Ошибка API: {result['msg']}")
        return result["data"]["batch_id"], result["data"]["file_urls"]

    def upload_files(self, file_paths, upload_urls):
        for path, upload_url in zip(file_paths, upload_urls):
            with open(path, "rb") as f:
                resp = requests.put(upload_url, data=f)
                filename = os.path.basename(path)
                if resp.status_code in (200, 201):
                    self.log(f"  ✅ Загружен: {filename}")
                else:
                    self.log(f"  ❌ Ошибка загрузки {filename}: {resp.status_code}")

    def poll_batch_result(self, batch_id, timeout=600, interval=5):
        url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        headers = {"Authorization": f"Bearer {API_KEY}"}
        start = time.time()
        done = {}
        while time.time() - start < timeout:
            resp = requests.get(url, headers=headers)
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
                    self.log(f"  ❌ Ошибка для {fname}: {item.get('err_msg', '')}")
                    done[fname] = None
            if len(done) == len(result["data"]["extract_result"]):
                break
            time.sleep(interval)
        return done

    def extract_and_save(self, zip_url, output_dir, relative_path, original_name):
        """Извлекает из ZIP только .md файлы и сохраняет их как .md."""
        resp = requests.get(zip_url)
        if resp.status_code != 200:
            self.log(f"  ❌ Не удалось скачать zip для {original_name}")
            return
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            # Ищем только .md файлы (должны быть, т.к. мы не запрашивали HTML)
            md_files = [n for n in zf.namelist() if n.endswith(".md")]
            if not md_files:
                # если вдруг .md нет (редко, но бывает), пробуем взять .html или .txt
                fallback = [n for n in zf.namelist() if n.endswith((".html", ".htm", ".txt"))]
                if fallback:
                    content_file = fallback[0]
                    self.log(f"  ⚠️ .md не найден, берём {os.path.basename(content_file)}")
                else:
                    self.log(f"  ❌ В ZIP нет текстовых файлов для {original_name}")
                    return
            else:
                content_file = md_files[0]
            content = zf.read(content_file).decode("utf-8")
            # Сохраняем всегда с расширением .md
            target_dir = os.path.join(output_dir, relative_path)
            os.makedirs(target_dir, exist_ok=True)
            out_path = os.path.join(target_dir, original_name + ".md")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log(f"  💾 Сохранено: {out_path}")

if __name__ == "__main__":
    root = tk.Tk()
    app = OCRApp(root)
    root.mainloop()