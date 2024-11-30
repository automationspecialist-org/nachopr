import subprocess
import sys
import time
from typing import Dict
import os
import signal
import atexit
import threading
from datetime import datetime
from colorama import init, Fore, Style

init()  # Initialize colorama

class DevServer:
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self.handle_interrupt)
        signal.signal(signal.SIGTERM, self.handle_interrupt)

    def log_output(self, process: subprocess.Popen, name: str, color: str):
        """Stream logs from process with color coding"""
        def stream_logs(pipe, prefix):
            for line in iter(pipe.readline, ''):
                timestamp = datetime.now().strftime('%H:%M:%S')
                print(f"{color}[{timestamp}] {name} | {line.strip()}{Style.RESET_ALL}")
        
        threading.Thread(target=stream_logs, args=(process.stdout, 'OUT'), daemon=True).start()
        threading.Thread(target=stream_logs, args=(process.stderr, 'ERR'), daemon=True).start()

    def run_command(self, command: str, name: str, color: str):
        """Run a command and set up logging"""
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                shell=True,
                env=os.environ.copy()
            )
            self.processes[name] = process
            self.log_output(process, name, color)
            return process
        except Exception as e:
            print(f"{Fore.RED}Failed to start {name}: {e}{Style.RESET_ALL}")
            return None

    def setup_redis(self):
        """Configure Redis for development"""
        try:
            redis_process = subprocess.run(
                ["redis-cli", "ping"],
                capture_output=True,
                text=True
            )
            
            if redis_process.returncode == 0:
                # Redis is running, configure it
                subprocess.run(["redis-cli", "CONFIG", "SET", "stop-writes-on-bgsave-error", "no"])
                subprocess.run(["redis-cli", "CONFIG", "SET", "save", "\"\""])
                print(f"{Fore.GREEN}Configured existing Redis server{Style.RESET_ALL}")
            else:
                # Start Redis with configuration
                redis_conf = """
                stop-writes-on-bgsave-error no
                save ""
                """
                with open("redis.conf", "w") as f:
                    f.write(redis_conf)
                
                self.run_command("redis-server redis.conf", "Redis", Fore.RED)
                time.sleep(2)  # Wait for Redis to start
                
        except Exception as e:
            print(f"{Fore.RED}Error setting up Redis: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def start_services(self):
        """Start all development services"""
        print(f"{Fore.GREEN}Starting development services...{Style.RESET_ALL}")
        
        # Setup Redis first
        self.setup_redis()
        
        commands = [
            # Django dev server
            ("uv run python manage.py runserver 8001", "Django", Fore.GREEN),
            
            # Tailwind
            ("uv run python manage.py tailwind start", "Tailwind", Fore.BLUE),
            
            # Celery workers
            ("uv run celery -A core worker --queues=default --loglevel=INFO --concurrency=2 --max-memory-per-child=1000000 -P processes", "Celery-Default", Fore.YELLOW),
            ("uv run celery -A core worker --queues=crawl --loglevel=INFO --concurrency=1 --max-memory-per-child=1000000 -P processes", "Celery-Crawl", Fore.MAGENTA),
            ("uv run celery -A core worker --queues=process --loglevel=INFO --concurrency=2", "Celery-Process", Fore.CYAN),
            ("uv run celery -A core worker --queues=categorize --loglevel=INFO --concurrency=1", "Celery-Categorize", Fore.WHITE),
            
            # Celery beat
            ("uv run celery -A core beat --loglevel=INFO", "Celery-Beat", Fore.LIGHTBLUE_EX),
        ]

        for cmd, name, color in commands:
            print(f"{color}Starting {name}...{Style.RESET_ALL}")
            self.run_command(cmd, name, color)
            time.sleep(2)

        print(f"\n{Fore.GREEN}All services started! Press Ctrl+C to stop all services.{Style.RESET_ALL}\n")
        
        try:
            while True:
                for name, process in list(self.processes.items()):
                    if process.poll() is not None:
                        print(f"{Fore.RED}Process {name} died with exit code {process.poll()}!{Style.RESET_ALL}")
                        self.cleanup()
                        sys.exit(1)
                time.sleep(1)
        except KeyboardInterrupt:
            self.cleanup()

    def cleanup(self):
        print(f"\n{Fore.YELLOW}Stopping all services...{Style.RESET_ALL}")
        for name, process in self.processes.items():
            if process.poll() is None:  # If process is still running
                print(f"{Fore.YELLOW}Stopping {name}...{Style.RESET_ALL}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"{Fore.RED}Force killing {name}...{Style.RESET_ALL}")
                    process.kill()
        self.processes.clear()

    def handle_interrupt(self, signum, frame):
        self.cleanup()
        sys.exit(0)

if __name__ == "__main__":
    # Add colorama to requirements if not already present
    try:
        import colorama
    except ImportError:
        print("Installing required package: colorama")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "colorama"])
        print("Package installed. Restarting script...")
        os.execv(sys.executable, ['python'] + sys.argv)
    
    server = DevServer()
    server.start_services()