from nc_py_api import Nextcloud
import random
import re
import tkinter as tk
from tkinter import messagebox, simpledialog
from dotenv import load_dotenv
import os


class FolderSelectionDialog(simpledialog.Dialog):
    def __init__(self, parent, folders):
        self.folders = folders
        self.selected_folder = None
        super().__init__(parent, title="Выбор папки для изменения ТН")

    def body(self, master):
        tk.Label(master, text="Найдено несколько папок с одинаковым ФИО.\nВыберите нужную:").pack(pady=10)

        self.listbox = tk.Listbox(master, width=80, height=10)
        self.listbox.pack(padx=10, pady=5)

        for folder in self.folders:
            self.listbox.insert(tk.END, folder.name)

        # Выбираем первый элемент по умолчанию
        if self.folders:
            self.listbox.selection_set(0)

        return self.listbox

    def apply(self):
        selection = self.listbox.curselection()
        if selection:
            self.selected_folder = self.folders[selection[0]]


class NextCloudApp:
    def __init__(self, url, user, password):
        self.nc = Nextcloud(nextcloud_url=url, nc_auth_user=user, nc_auth_pass=password)

    def generate_id(self):
        return f"%040x" % random.getrandbits(160)

    def create_employee_folder(self, tn, fullname, force_create=False):
        if not re.match(r'^ТН\d{5}$', tn):
            raise ValueError("ТН должен быть в формате 'ТН00000'")

        existing = self.nc.files.find(["like", "name", f"%{fullname}%"])
        # Фильтруем только папки сотрудников
        employee_folders = [f for f in existing if f.name.split()[0].startswith("ТН")]

        if employee_folders and not force_create:
            return "exists", employee_folders

        unique_id = self.generate_id()
        base_folder_name = f"{tn} {fullname} {unique_id}"
        base_path = f"Сотрудники/{base_folder_name}"
        self.nc.files.makedirs(base_path, exist_ok=True)

        subfolders = ["паспорт", "удостоверения", "снилс и ИНН", "билеты", "другое"]
        for sf in subfolders:
            sf_path = f"{base_path}/{sf} {unique_id}"
            self.nc.files.makedirs(sf_path, exist_ok=True)

        return "created", base_path

    def find_employee_folders(self, search_fio=None, search_id=None):
        """Поиск папок сотрудников по ФИО или ID"""
        if search_fio:
            found_folders = self.nc.files.find(["like", "name", f"%{search_fio}%"])
        elif search_id:
            found_folders = self.nc.files.find(["like", "name", f"%{search_id}%"])
        else:
            return []

        # Фильтруем только папки сотрудников
        employee_folders = [f for f in found_folders if f.name.split()[0].startswith("ТН")]
        return employee_folders

    def change_tn(self, folder_name=None, new_tn=None):
        """Изменение ТН для конкретной папки по её полному имени"""
        if not re.match(r'^ТН\d{5}$', new_tn):
            raise ValueError("Новый ТН должен быть в формате 'ТН00000'")

        if not folder_name:
            return "no_folder_specified"

        # Поиск конкретной папки по полному имени
        found_folders = self.nc.files.find(["like", "name", f"%{folder_name}%"])
        target_folder = None

        for folder in found_folders:
            if folder.name == folder_name:
                target_folder = folder
                break

        if not target_folder:
            return "not_found"

        # Извлекаем ID из исходной папки
        original_id = None
        parts = target_folder.name.split()
        for part in parts:
            if len(part) == 40 and all(c in '0123456789abcdef' for c in part):
                original_id = part
                break

        # Проверка существования нового ТН
        existing_tn_folders = self.nc.files.find(["like", "name", f"{new_tn} %"])

        conflict_exists = any(
            folder.name.startswith(f"{new_tn} ") and
            not folder.name.endswith(original_id)
            for folder in existing_tn_folders
        )

        if conflict_exists:
            return "tn_exists"

        try:
            # Парсинг имени папки
            parts = target_folder.name.split()
            if len(parts) < 3 or not parts[0].startswith("ТН"):
                return "invalid_folder_format"

            # Формирование нового имени
            fio_and_id = ' '.join(parts[1:])
            new_folder_name = f"{new_tn} {fio_and_id}"
            new_folder_path = f"Сотрудники/{new_folder_name}"

            # Создание новой папки
            self.nc.files.makedirs(new_folder_path, exist_ok=True)

            # Перемещение содержимого
            for item in self.nc.files.listdir(target_folder):
                source_path = f"Сотрудники/{target_folder.name}/{item.name}"
                target_path = f"{new_folder_path}/{item.name}"
                self.nc.files.move(source_path, target_path)

            # Удаление исходной папки
            self.nc.files.delete(target_folder)

            return "changed"

        except Exception as e:
            # Откат изменений при ошибке
            if 'new_folder_path' in locals():
                try:
                    self.nc.files.delete(new_folder_path)
                except:
                    pass
            raise RuntimeError(f"Ошибка при изменении ТН: {str(e)}")


class NextCloudAppGUI:
    def __init__(self, app):
        self.app = app
        self.root = tk.Tk()
        self.root.title("NextCloud Employee Manager")
        self._create_widgets()

    def _create_widgets(self):
        fields = [
            ("ФИО для создания:", "entry_create"),
            ("ФИО для поиска:", "entry_search_fio"),
            ("ID для поиска:", "entry_search_id"),
            ("Новый ТН:", "entry_new_tn")
        ]

        for i, (label, var) in enumerate(fields):
            tk.Label(self.root, text=label).grid(row=i, column=0, sticky='w', padx=5, pady=2)
            entry = tk.Entry(self.root, width=50)
            entry.grid(row=i, column=1, padx=5, pady=2)
            setattr(self, var, entry)

        self.btn_create = tk.Button(self.root, text="Создать", command=self._handle_create)
        self.btn_create.grid(row=4, column=0, padx=5, pady=10)

        self.btn_assign = tk.Button(self.root, text="Присвоить ТН", command=self._handle_assign)
        self.btn_assign.grid(row=4, column=1, padx=5, pady=10)

    def _handle_create(self):
        fio = self.entry_create.get().strip()
        if not fio:
            messagebox.showwarning("Ошибка", "Введите ФИО сотрудника")
            return

        try:
            status, info = self.app.create_employee_folder("ТН00000", fio)
            if status == "exists":
                choice = messagebox.askyesnocancel(
                    "Конфликт",
                    "Сотрудник существует. Выберите действие:\n"
                    "Да - Показать существующие папки\n"
                    "Нет - Создать новую папку\n"
                    "Отмена - Отменить операцию"
                )
                if choice is True:
                    msg = "\n".join(f.name for f in info)
                    messagebox.showinfo("Найденные папки", msg)
                elif choice is False:
                    status, info = self.app.create_employee_folder("ТН00000", fio, force_create=True)
                    messagebox.showinfo("Успех", f"Создана новая папка: {info}")
            else:
                messagebox.showinfo("Успех", f"Папка создана: {info}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _handle_assign(self):
        search_fio = self.entry_search_fio.get().strip()
        search_id = self.entry_search_id.get().strip()
        new_tn = self.entry_new_tn.get().strip()

        if not new_tn:
            messagebox.showwarning("Ошибка", "Введите новый ТН")
            return

        if not search_fio and not search_id:
            messagebox.showwarning("Ошибка", "Введите ФИО или ID для поиска")
            return

        try:
            # Поиск папок
            employee_folders = self.app.find_employee_folders(search_fio=search_fio, search_id=search_id)

            if not employee_folders:
                messagebox.showinfo("Результат", "Сотрудник не найден")
                return

            # Выбор папки при множественных результатах
            selected_folder_name = None

            if len(employee_folders) > 1:
                # Показываем диалог выбора
                dialog = FolderSelectionDialog(self.root, employee_folders)
                if dialog.selected_folder is None:
                    return  # Пользователь отменил выбор
                selected_folder_name = dialog.selected_folder.name
            else:
                # Единственная папка найдена
                selected_folder_name = employee_folders[0].name

            # Изменение ТН для выбранной папки
            result = self.app.change_tn(folder_name=selected_folder_name, new_tn=new_tn)

            messages = {
                "not_found": "Сотрудник не найден",
                "tn_exists": "ТН уже используется другим сотрудником",
                "changed": "ТН успешно изменен",
                "no_folder_specified": "Не указана папка для изменения",
                "invalid_folder_format": "Неверный формат папки"
            }
            messagebox.showinfo("Результат", messages.get(result, "Неизвестная ошибка"))

        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    load_dotenv()
    login = os.getenv('NC_USER')
    password = os.getenv('NC_PASS')
    url = os.getenv('NC_URL')

    nc_app = NextCloudApp(url, login, password)
    gui = NextCloudAppGUI(nc_app)
    gui.run()
