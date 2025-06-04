import os
import zipfile
import time
import json
import threading
import ftplib
import paramiko
import logging
import tempfile
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 配置文件路径
CONFIG_FILE = "config.json"

# 默认配置
DEFAULT_CONFIG = {
    "plugin_dir": "/path/to/your/plugin",  # 插件源代码目录
    "server_plugin_dir": "/path/to/server/plugins",  # 服务器插件目录
    "plugin_name": "your_plugin_name.zip",  # 插件的 ZIP 文件名称
    "auto_upload": True,  # 是否启用自动上传（True: 自动监测文件变化，False: 手动触发）
    "upload_method": "ftp",  # 上传方式: "ftp" 或 "sftp"
    "ftp": {
        "host": "ftp.example.com",
        "port": 21,
        "username": "your_ftp_username",
        "password": "your_ftp_password",
    },
    "sftp": {
        "host": "sftp.example.com",
        "port": 22,
        "username": "your_sftp_username",
        "password": "your_sftp_password",  # 密码，或者使用 "private_key_file"
        "private_key_file": "/path/to/private/key",  # 密钥文件路径（可选）
    }
}

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# 读取或创建配置文件
def load_config():
    if not os.path.exists(CONFIG_FILE):
        log.info(f"配置文件 {CONFIG_FILE} 不存在，正在创建默认配置文件...")
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        log.info(f"已创建默认配置文件: {CONFIG_FILE}")
        return DEFAULT_CONFIG
    else:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)

# 创建ZIP包
def create_zip_from_dir(directory, zip_name):
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(directory):
            for file in files:
                zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), directory))

# FTP 上传
def upload_ftp(config, zip_path):
    ftp_config = config["ftp"]
    try:
        with ftplib.FTP() as ftp:
            ftp.connect(ftp_config["host"], ftp_config["port"])
            ftp.login(ftp_config["username"], ftp_config["password"])
            ftp.cwd(config["server_plugin_dir"])  # 切换到目标目录
            with open(zip_path, 'rb') as f:
                ftp.storbinary(f"STOR {config['plugin_name']}", f)
            log.info(f"插件已通过 FTP 上传到服务器: {zip_path}")
    except Exception as e:
        log.error(f"FTP 上传失败: {e}")

# SFTP 上传
def upload_sftp(config, zip_path):
    sftp_config = config["sftp"]
    try:
        transport = paramiko.Transport((sftp_config["host"], sftp_config["port"]))
        if sftp_config.get("private_key_file"):
            private_key = paramiko.RSAKey.from_private_key_file(sftp_config["private_key_file"])
            transport.connect(username=sftp_config["username"], pkey=private_key)
        else:
            transport.connect(username=sftp_config["username"], password=sftp_config["password"])
        sftp = paramiko.SFTPClient.from_transport(transport)
        remote_path = f"{config['server_plugin_dir']}/{config['plugin_name']}"
        sftp.put(zip_path, remote_path)
        sftp.close()
        transport.close()
        log.info(f"插件已通过 SFTP 上传到服务器: {remote_path}")
    except Exception as e:
        log.error(f"SFTP 上传失败: {e}")

# 根据配置选择 FTP 或 SFTP 上传
def upload_plugin(config):
    temp_dir = tempfile.gettempdir()
    zip_path = os.path.join(temp_dir, config["plugin_name"])
    create_zip_from_dir(config["plugin_dir"], zip_path)

    # 根据配置选择上传方法
    if config["upload_method"] == "ftp":
        upload_ftp(config, zip_path)
    elif config["upload_method"] == "sftp":
        upload_sftp(config, zip_path)
    else:
        log.error("上传方法无效，请选择 'ftp' 或 'sftp'")
    try:
        os.remove(zip_path)
    except Exception as e:
        log.warning(f"删除临时文件失败: {e}")
    log.info("插件已重载")

# 监视插件目录的文件变化
class WatcherHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        # 只监视 Python 文件变化
        if event.src_path.endswith(".py"):
            log.info(f"检测到文件变更: {event.src_path}, 正在重新打包并上传...")
            upload_plugin(config)

# 启动监控程序
def start_watcher(config, stop_event):
    event_handler = WatcherHandler()
    observer = Observer()
    observer.schedule(event_handler, config["plugin_dir"], recursive=True)
    observer.start()

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()

# 手动触发上传
def manual_upload(config):
    while True:
        command = input("请输入命令（'upload' 上传插件，'exit' 退出程序）: ")
        if command.lower() == "upload":
            upload_plugin(config)
        elif command.lower() == "exit":
            break
        else:
            print("无效命令，请输入 'upload' 或 'exit'。")

# 监听退出命令
def listen_for_exit(stop_event):
    while True:
        command = input("输入 'exit' 来停止自动监测并退出程序: ")
        if command.lower() == "exit":
            stop_event.set()
            break

if __name__ == "__main__":
    log.info("插件自动化更新程序已启动，开始加载配置...")
    config = load_config()

    stop_event = threading.Event()

    if config["auto_upload"]:
        log.info("启用自动上传模式，开始监视文件变化...")

        # 启动后台线程，进行文件监控
        watcher_thread = threading.Thread(target=start_watcher, args=(config, stop_event))
        watcher_thread.start()

        # 启动监听退出命令的线程
        exit_thread = threading.Thread(target=listen_for_exit, args=(stop_event,))
        exit_thread.start()

        # 等待退出信号
        exit_thread.join()

        # 等待文件监控线程结束
        watcher_thread.join()

        log.info("程序已退出")
    else:
        log.info("启用手动上传模式，等待用户命令...")
        manual_upload(config)
