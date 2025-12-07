import os
import subprocess
import sys
import shutil


def find_chromedriver():
    # Priorität: zuerst /usr/bin/chromedriver
    common_paths = [
        "/usr/bin/chromedriver",                      # Linux Standard
        "/usr/local/bin/chromedriver",                # Manuell installiert (z. B. via brew)
        "C:\\Program Files\\ChromeDriver\\chromedriver.exe",  # Windows
        "C:\\chromedriver\\chromedriver.exe"
    ]

    for path in common_paths:
        if os.path.isfile(path):
            return path

    # Wenn in PATH gefunden → als Fallback
    chromedriver = shutil.which("chromedriver")
    if chromedriver:
        return chromedriver

    return None


def open_env_file(env_path):
    try:
        if sys.platform.startswith("darwin"):  # macOS
            subprocess.call(["open", env_path])
        elif os.name == "nt":  # Windows
            os.startfile(env_path)
        elif os.name == "posix":  # Linux
            subprocess.call(["xdg-open", env_path])
    except Exception as e:
        print(f"❌ Failed to open .env file: {e}")


def generate_env():
    base_dir = os.path.dirname(__file__)
    example_path = os.path.join(base_dir, ".env.example")
    env_path = os.path.join(base_dir, ".env")

    if os.path.exists(env_path):
        print("⚠️  .env already exists. Aborting to avoid overwriting.")
        return

    try:
        with open(example_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        print("❌ .env.example not found.")
        return

    chromedriver_path = find_chromedriver()
    if chromedriver_path:
        print(f"✅ Found ChromeDriver at: {chromedriver_path}")
        content = content.replace("/path/to/chromedriver", chromedriver_path)
    else:
        print("⚠️ ChromeDriver not found. Please enter the path manually.")

    with open(env_path, "w") as f:
        f.write(content)

    print("✅ .env created.")
    print("👉 Opening it so you can fill in your credentials...")
    open_env_file(env_path)


if __name__ == "__main__":
    generate_env()
