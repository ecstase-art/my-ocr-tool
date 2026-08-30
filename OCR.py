import os
import time
import zipfile
import io
from pathlib import Path
import requests
import tkinter as tk
from tkinter import filedialog, messagebox

# ===== НАСТРОЙКИ =====
API_KEY = os.environ.get("MINERU_API_KEY")
if not API_KEY:
    raise RuntimeError("MINERU_API_KEY не задан")
EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.docx', '.pptx', '.xlsx')
BATCH_SIZE = 50

# ===== 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ GUI =====
def show_message(title, message, is_error=False):
    """Показывает всплывающее окно с сообщением."""
    root = tk.Tk()
    root.withdraw()
    if is_error:
        messagebox.showerror(title, message)
    else:
        messagebox.showinfo(title, message)
    root.destroy()

def get_input_folder():
    """Открывает диалог выбора папки, возвращает путь."""
    root = tk.Tk()
    root.withdraw()
    folder_path = filedialog.askdirectory(title="Выберите папку с документами")
    root.destroy()
    if not folder_path:
        show_message("Отмена", "Папка не выбрана. Программа завершена.", is_error=True)
        exit(1)
    return folder_path

def get_project_name():
    """Запрашивает название проекта в консоли (простой ввод)."""
    allowed = set(" абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-().№")
    while True:
        name = input("Введите название проекта (можно использовать буквы, цифры, №, (), -_ .): ").strip()
        if not name:
            print("❌ Имя не может быть пустым.")
            continue
        if all(c in allowed for c in name):
            return name
        print("❌ Некорректное имя. Используйте буквы, цифры, пробелы, подчёркивания, дефисы, точки, скобки, №.")

# ===== 2. РАБОТА С API =====
def get_upload_urls(file_names, model_version="vlm", extra_formats=["html"]):
    url = "https://mineru.net/api/v4/file-urls/batch"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "files": [{"name": name} for name in file_names],
        "model_version": model_version,
        "extra_formats": extra_formats,
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

def upload_files(file_paths, upload_urls):
    for path, upload_url in zip(file_paths, upload_urls):
        with open(path, "rb") as f:
            resp = requests.put(upload_url, data=f)
            filename = os.path.basename(path)
            if resp.status_code in (200, 201):
                print(f"  ✅ Загружен: {filename}")
            else:
                print(f"  ❌ Ошибка загрузки {filename}: {resp.status_code}")

def poll_batch_result(batch_id, timeout=600, interval=5):
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
                    print(f"  ✅ Готов: {fname}")
            elif state == "failed":
                print(f"  ❌ Ошибка для {fname}: {item.get('err_msg', '')}")
                done[fname] = None
        if len(done) == len(result["data"]["extract_result"]):
            break
        time.sleep(interval)
    return done

def extract_and_save(zip_url, output_dir, relative_path, original_name):
    resp = requests.get(zip_url)
    if resp.status_code != 200:
        print(f"  ❌ Не удалось скачать zip для {original_name}")
        return
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        html_files = [n for n in zf.namelist() if n.endswith((".html", ".htm"))]
        md_files = [n for n in zf.namelist() if n.endswith(".md")]
        if html_files:
            content_file = html_files[0]
            ext = ".html"
        elif md_files:
            content_file = md_files[0]
            ext = ".md"
        else:
            print(f"  ❌ В ZIP нет HTML/Markdown для {original_name}")
            return
        content = zf.read(content_file).decode("utf-8")
        if ext == ".md" and not html_files:
            try:
                import markdown
                content = markdown.markdown(content, extensions=["tables", "fenced_code"])
                ext = ".html"
            except ImportError:
                pass
        target_dir = os.path.join(output_dir, relative_path)
        os.makedirs(target_dir, exist_ok=True)
        out_path = os.path.join(target_dir, original_name + ext)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  💾 Сохранено: {out_path}")

# ===== 3. ОСНОВНАЯ ФУНКЦИЯ =====
def main():
    print("\n" + "="*50)
    print("MinerU Пакетный OCR (с сохранением структуры)")
    print("="*50)
    input_dir = get_input_folder()
    project_name = get_project_name()

    output_dir = os.path.join(input_dir, project_name)
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 Результаты будут сохранены в: {output_dir}\n")

    # Сбор файлов
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
        print("❌ Не найдено ни одного поддерживаемого файла.")
        show_message("Ошибка", "В выбранной папке не найдено поддерживаемых файлов.\nПоддерживаются: PDF, JPG, PNG, DOCX, PPTX, XLSX.", is_error=True)
        return

    print(f"📄 Найдено файлов: {len(file_entries)}")
    print("🔄 Начинаем обработку...\n")

    for i in range(0, len(file_entries), BATCH_SIZE):
        batch = file_entries[i:i+BATCH_SIZE]
        file_names = [entry[2] for entry in batch]
        print(f"📦 Пакет {i//BATCH_SIZE + 1} ({len(batch)} файлов)")

        try:
            batch_id, upload_urls = get_upload_urls(file_names)
        except Exception as e:
            print(f"  ❌ Ошибка получения ссылок: {e}")
            show_message("Ошибка API", str(e), is_error=True)
            return

        upload_files([entry[0] for entry in batch], upload_urls)

        print("  ⏳ Ожидание завершения обработки...")
        results = poll_batch_result(batch_id)

        for fname, zip_url in results.items():
            if not zip_url:
                continue
            for abs_path, rel_path, orig_fname in batch:
                if orig_fname == fname:
                    base = Path(fname).stem
                    extract_and_save(zip_url, output_dir, rel_path, base)
                    break

        print("  ✅ Пакет завершён.\n")

    print("\n🎉 Все файлы обработаны!")
    print(f"📂 Результаты в папке: {output_dir}")
    show_message("Готово!", f"Все файлы успешно обработаны!\nРезультаты сохранены в:\n{output_dir}")

if __name__ == "__main__":
    main()