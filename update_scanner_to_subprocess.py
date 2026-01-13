"""
Script to update GUI to use subprocess for scanner instead of async in thread.

This replaces the problematic async event loop approach with a cleaner subprocess approach.
"""
import re
from pathlib import Path


def update_gui():
    """Update gui.py to use subprocess for scanner."""

    gui_path = Path('gui.py')
    with open(gui_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find and replace _start_scanner, _run_scanner_async, _test_proxies, _run_scanner methods
    # These methods span from line ~1544 to ~1695

    # Pattern to find the old scanner methods
    old_methods_pattern = r'    def _start_scanner\(self\):.*?(?=\n    def _log\(self, message: str\):)'

    new_methods = '''    def _start_scanner(self):
        """Запустить сканер TM Parser в отдельном процессе."""
        if self.scanner_running:
            self._log("⚠️ Сканер уже работает!")
            return

        self._log("🔄 Запуск сканера TM Parser...")
        self.scanner_status_label.configure(text="Статус: запуск...", text_color="yellow")

        try:
            # Prepare scanner configuration
            scanner_config = {
                'min_price': float(self.min_price_entry.get() or 1000),
                'max_price': float(self.max_price_entry.get() or 10000),
                'min_profit': float(self.scanner_profit_entry.get() or -5.0),
                'min_sales_7d': int(self.sales_7d_entry.get() or 50),
                'proxy_file': self.proxy_file_entry.get() or 'proxies.txt',
                'requests_per_proxy': int(self.requests_per_proxy_entry.get() or 50),
                'max_items': int(self.max_items_entry.get() or 10),
                'delay': float(self.delay_entry.get() or 7.0),
                'workers': int(self.workers_entry.get() or 1),
            }

            self._log(f"📊 Настройки: цена {scanner_config['min_price']}-{scanner_config['max_price']}, мин. профит {scanner_config['min_profit']}%")
            self._log(f"📊 Макс. предметов: {scanner_config['max_items']}, задержка: {scanner_config['delay']}s, воркеров: {scanner_config['workers']}")

            # Save config to file
            config_path = Path('scanner_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(scanner_config, f, indent=2)

            # Remove old stop flag if exists
            stop_flag = Path('scanner_stop.flag')
            if stop_flag.exists():
                stop_flag.unlink()

            # Start scanner process
            python_exe = sys.executable
            scanner_script = Path('src/bottm/scanner_process.py')

            self.scanner_process = subprocess.Popen(
                [python_exe, str(scanner_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            self.scanner_running = True
            self._log("✅ Процесс сканера запущен")

            # Start monitoring thread
            self.scanner_monitor_thread = threading.Thread(target=self._monitor_scanner_process, daemon=True)
            self.scanner_monitor_thread.start()

        except Exception as e:
            logger.error(f"Failed to start scanner: {e}", exc_info=True)
            self._log(f"❌ Ошибка запуска сканера: {e}")
            self.scanner_status_label.configure(text="Статус: ошибка", text_color="red")
            self.scanner_running = False

    def _monitor_scanner_process(self):
        """Monitor scanner process and display output."""
        try:
            self.scanner_status_label.configure(text="Статус: сканирование...", text_color="yellow")

            # Read process output line by line
            for line in iter(self.scanner_process.stdout.readline, ''):
                if not line:
                    break

                line = line.strip()
                if line:
                    # Display in logs (remove timestamp as we add our own)
                    if '] ' in line:
                        # Extract message after timestamp
                        msg = line.split('] ', 1)[-1]
                        self._log(msg)
                    else:
                        self._log(line)

            # Wait for process to complete
            return_code = self.scanner_process.wait()

            if return_code == 0:
                self._log("✅ Сканирование завершено успешно!")
                self.scanner_status_label.configure(text="Статус: завершено", text_color="green")
                # Refresh profitable items display
                self._refresh_profitable_items()
            else:
                self._log(f"❌ Сканер завершился с ошибкой (код: {return_code})")
                self.scanner_status_label.configure(text="Статус: ошибка", text_color="red")

        except Exception as e:
            logger.error(f"Scanner monitor error: {e}", exc_info=True)
            self._log(f"❌ Ошибка мониторинга сканера: {e}")
            self.scanner_status_label.configure(text="Статус: ошибка", text_color="red")
        finally:
            self.scanner_running = False
            self.scanner_process = None

    def _stop_scanner(self):
        """Остановить процесс сканера."""
        if not self.scanner_running or not self.scanner_process:
            self._log("⚠️ Сканер не запущен")
            return

        try:
            self._log("⏸️ Остановка сканера...")

            # Create stop flag file
            stop_flag = Path('scanner_stop.flag')
            stop_flag.touch()

            # Terminate process
            self.scanner_process.terminate()

            # Wait up to 5 seconds for graceful shutdown
            try:
                self.scanner_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if not stopped
                self.scanner_process.kill()
                self.scanner_process.wait()

            self._log("✅ Сканер остановлен")
            self.scanner_status_label.configure(text="Статус: остановлен", text_color="gray")
            self.scanner_running = False
            self.scanner_process = None

        except Exception as e:
            logger.error(f"Failed to stop scanner: {e}", exc_info=True)
            self._log(f"❌ Ошибка остановки сканера: {e}")

'''

    # Replace using regex with DOTALL flag
    content_new = re.sub(old_methods_pattern, new_methods, content, flags=re.DOTALL)

    # Write back
    with open(gui_path, 'w', encoding='utf-8') as f:
        f.write(content_new)

    print("✅ GUI updated successfully!")
    print("Scanner methods replaced with subprocess version.")


if __name__ == '__main__':
    update_gui()
