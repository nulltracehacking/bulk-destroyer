# bulk_destroyer.py
import tkinter as tk
from tkinter import scrolledtext
import threading, asyncio, random, string, time, aiohttp, psutil, requests
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ----------------------------
# Configuration
# ----------------------------
REQUEST_TIMEOUT = 2.0
GRAPH_UPDATE_INTERVAL_MS = 300
RETRY_INTERVAL = 0.05

# ----------------------------
# User agents
# ----------------------------
UserAgents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/90.0.4430.93 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/14.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 11; SM-G981B) AppleWebKit/537.36 Chrome/90.0.4430.210 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 Version/14.0 Mobile/15E148 Safari/604.1"
]

# ----------------------------
# Payload generator (heavier)
# ----------------------------
def random_payload():
    big_text = ''.join(random.choices(string.ascii_letters + string.digits, k=10000))  # 10k chars
    big_list = [random.randint(1, 1000) for _ in range(200)]
    nested = {
        "level1": {
            "numbers": [random.random() for _ in range(100)],
            "texts": [''.join(random.choices(string.ascii_letters, k=200)) for _ in range(50)],
            "deep": {"a": random.random(), "b": big_text[:500]}
        }
    }
    return {
        "int": random.randint(1, 1000000),
        "float": random.random() * 10000,
        "text": big_text,
        "list": big_list,
        "nested": nested
    }

# ----------------------------
# Target Controller
# ----------------------------
class TargetController:
    def __init__(self, get_ordered_urls_fn, log_fn):
        self.get_ordered_urls = get_ordered_urls_fn
        self.log = log_fn
        self.lock = threading.Lock()
        self.current_target = None
        self.url_status = {}
        self._stop = False
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def _probe(self, url):
        try:
            requests.head(url, timeout=REQUEST_TIMEOUT)
            return True
        except:
            return False

    def _monitor_loop(self):
        while not self._stop:
            ordered = self.get_ordered_urls()
            if not ordered:
                with self.lock:
                    self.current_target = None
                time.sleep(RETRY_INTERVAL)
                continue

            for u in ordered:
                self.url_status[u] = self._probe(u)

            chosen = None
            for u in ordered:
                if self.url_status.get(u):
                    chosen = u
                    break

            with self.lock:
                prev = self.current_target
                self.current_target = chosen

            if chosen != prev:
                if chosen is None:
                    self.log("No URLs reachable. All down.", "down")
                else:
                    self.log(f"Switched target to: {chosen}", "info")

            time.sleep(RETRY_INTERVAL)

    def get_target(self):
        with self.lock:
            return self.current_target

    def stop(self):
        self._stop = True
        self._thread.join(timeout=1)

# ----------------------------
# Async Worker
# ----------------------------
async def async_worker(target, log_fn, response_times, rt_lock, running_flag):
    async with aiohttp.ClientSession() as session:
        while running_flag():
            payload = random_payload()
            headers = {"User-Agent": random.choice(UserAgents)}
            start = time.time()
            try:
                async with session.post(target, json=payload, headers=headers, timeout=REQUEST_TIMEOUT) as resp:
                    elapsed = time.time() - start
                    with rt_lock:
                        response_times.setdefault(target, []).append(elapsed)
                    log_fn(f"URL: {target} | Status: {resp.status} | Time: {elapsed:.3f}s", "info")
            except Exception as e:
                log_fn(f"Error: {e}", "down")
            await asyncio.sleep(0)

def thread_worker(target_fn, log_fn, response_times, rt_lock, running_flag):
    target = target_fn()
    if not target:
        return
    asyncio.run(async_worker(target, log_fn, response_times, rt_lock, running_flag))

# ----------------------------
# GUI App (modified layout)
# ----------------------------
class BulkDestroyerApp:
    def __init__(self, root):
        self.root = root
        root.title("Bulk Destroyer")

        # Left frame for controls/log
        left_frame = tk.Frame(root)
        left_frame.grid(row=0, column=0, sticky="n")

        # Main URL + extras
        tk.Label(left_frame, text="Main URL:").grid(row=0,column=0,sticky="w")
        self.main_url_entry = tk.Entry(left_frame,width=40)
        self.main_url_entry.grid(row=0,column=1)
        self.main_url_entry.insert(0,"http://127.0.0.1:8000")

        self.extra_entries = []
        for i in range(4):
            tk.Label(left_frame, text=f"Extra URL {i+2}:").grid(row=1+i,column=0,sticky="w")
            e = tk.Entry(left_frame,width=40)
            e.grid(row=1+i,column=1)
            self.extra_entries.append(e)

        # Threads
        tk.Label(left_frame,text="Threads:").grid(row=5,column=0,sticky="w")
        self.threads_entry = tk.Entry(left_frame,width=10); self.threads_entry.grid(row=5,column=1)
        self.threads_entry.insert(0,"50")

        # Buttons
        self.start_btn = tk.Button(left_frame,text="Start",command=self.start_test); self.start_btn.grid(row=6,column=0)
        self.stop_btn = tk.Button(left_frame,text="Stop",command=self.stop_test,state="disabled"); self.stop_btn.grid(row=6,column=1)

        # Log
        self.log_area = scrolledtext.ScrolledText(left_frame,width=50,height=25)
        self.log_area.grid(row=7,column=0,columnspan=2)
        self.log_area.tag_config("info",foreground="blue")
        self.log_area.tag_config("down",foreground="red")

        # CPU/RAM
        self.cpu_label = tk.Label(left_frame,text="CPU: 0%"); self.cpu_label.grid(row=8,column=0)
        self.ram_label = tk.Label(left_frame,text="RAM: 0%"); self.ram_label.grid(row=8,column=1)

        # Right frame for graph only
        right_frame = tk.Frame(root)
        right_frame.grid(row=0, column=1, sticky="ns")

        # Graph (bigger)
        self.fig = Figure(figsize=(10,8))
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Response Times"); self.ax.set_xlabel("Request #"); self.ax.set_ylabel("Time (s)")
        self.canvas = FigureCanvasTkAgg(self.fig,master=right_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Internal state
        self.testing=False
        self.worker_threads=[]
        self.response_times={}; self.rt_lock=threading.Lock()
        self.controller = TargetController(self.get_ordered_urls, self.log)
        root.after(GRAPH_UPDATE_INTERVAL_MS,self.update_graph)
        root.after(500,self.update_system_usage)

    def get_ordered_urls(self):
        urls = []
        main = self.main_url_entry.get().strip()
        if main: urls.append(main)
        for e in self.extra_entries:
            u = e.get().strip()
            if u: urls.append(u)
        return urls

    def log(self,msg,tag=None):
        ts=time.strftime("%H:%M:%S")
        if tag: self.log_area.insert(tk.END,f"[{ts}] {msg}\n",tag)
        else: self.log_area.insert(tk.END,f"[{ts}] {msg}\n")
        self.log_area.see(tk.END)

    # ----------------------------
    # Start / Stop
    # ----------------------------
    def start_test(self):
        if self.testing:
            return
        try:
            threads_count = int(self.threads_entry.get())
        except:
            threads_count = 50
        self.testing=True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.log("Starting Bulk Destroyer...", "info")
        self.worker_threads=[]
        with self.rt_lock:
            self.response_times = {u: [] for u in self.get_ordered_urls()}
        for _ in range(threads_count):
            t=threading.Thread(
                target=thread_worker,
                args=(self.controller.get_target,self.log,self.response_times,self.rt_lock,lambda: self.testing),
                daemon=True
            )
            self.worker_threads.append(t)
            t.start()

    def stop_test(self):
        if not self.testing:
            return
        self.testing=False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log("Stopping Bulk Destroyer...", "info")

    # ----------------------------
    # Graph & Monitoring
    # ----------------------------
    def update_graph(self):
        with self.rt_lock:
            self.ax.clear()
            self.ax.set_title("Response Times")
            self.ax.set_xlabel("Request #")
            self.ax.set_ylabel("Time (s)")
            for url,times in self.response_times.items():
                if times: self.ax.plot(times,label=url)
            if self.response_times: self.ax.legend(fontsize="small")
            self.canvas.draw()
        self.root.after(GRAPH_UPDATE_INTERVAL_MS,self.update_graph)

    def update_system_usage(self):
        self.cpu_label.config(text=f"CPU: {psutil.cpu_percent()}%")
        self.ram_label.config(text=f"RAM: {psutil.virtual_memory().percent}%")
        self.root.after(500,self.update_system_usage)

    def close(self):
        self.testing=False
        self.controller.stop()
        self.root.destroy()

# ----------------------------
# Run
# ----------------------------
if __name__=="__main__":
    root=tk.Tk()
    app=BulkDestroyerApp(root)
    root.protocol("WM_DELETE_WINDOW",app.close)
    root.mainloop()