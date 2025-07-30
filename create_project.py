import os
from pathlib import Path

# تعریف ساختار پروژه
# Define the project structure
project_structure = {
    "core": [
        "__init__.py",
        "config.py",
        "database.py",
        "db_models.py", # جابجایی به داخل core بر اساس درخواست اولیه
    ],
    ".": [ # فایل‌های موجود در ریشه پروژه
        ".env",
        "bot.py",
        "celery_app.py",
        "docker-compose.yml",
        "Dockerfile",
        "prompt.txt",
        "requirements.txt",
        "scheduler.py",
        "tasks.py",
        "translate_prompt.txt",
        "utils.py",
    ],
}

def create_project_structure(base_path="."):
    """
    اسکریپتی برای ایجاد ساختار فایل و دایرکتوری پروژه.
    A script to create the project file and directory structure.
    """
    base_path = Path(base_path)

    for directory, files in project_structure.items():
        # مسیر کامل دایرکتوری را ایجاد می‌کند
        # Create the full directory path
        dir_path = base_path / directory
        if directory != ".":
            try:
                os.makedirs(dir_path, exist_ok=True)
                print(f"دایرکتوری ایجاد شد: {dir_path}")
                # Directory created: {dir_path}
            except OSError as e:
                print(f"خطا در ایجاد دایرکتوری {dir_path}: {e}")
                # Error creating directory {dir_path}: {e}
                continue

        # فایل‌ها را در دایرکتوری مربوطه ایجاد می‌کند
        # Create files in the respective directory
        for file_name in files:
            file_path = dir_path / file_name
            try:
                file_path.touch()
                print(f"  فایل ایجاد شد: {file_path}")
                #   File created: {file_path}
            except IOError as e:
                print(f"  خطا در ایجاد فایل {file_path}: {e}")
                #   Error creating file {file_path}: {e}

if __name__ == "__main__":
    # اسکریپت را در دایرکتوری فعلی اجرا می‌کند
    # Run the script in the current directory
    create_project_structure()
    print("\nساختار پروژه با موفقیت ایجاد شد!")
    # Project structure created successfully!
    