# Simple Whiteboard Flask app

Files added:

- `main.py` - Flask server that serves the HTML, accepts messages at `/message`, accepts file uploads at `/upload`, and serves uploaded files at `/uploads/<filename>`.
- `templates/index.html` - frontend whiteboard UI.
- `requirements.txt` - required Python packages.

Run locally:

```bash
python -m pip install -r requirements.txt
python main.py --host 0.0.0.0 --port 3109
```

Test the site (local or remote host):

1. Open `http://<host>:3109/` in a browser.
2. Send a message in the UI — it will show server echo, hostname and port and a ping measured client-side.
3. Upload a file via the form. The server returns a `url` like `/uploads/yourfile.ext`.

To test whether a remote server (for example `node62.lunes.host:3109`) will serve uploaded files:

```bash
# Upload a file
curl -F "file=@sample.jpg" http://node62.lunes.host:3109/upload

# The response returns a JSON `url`, then fetch it in the browser or with curl:
curl http://node62.lunes.host:3109/uploads/sample.jpg -I
```

If the GET returns HTTP 200 and the file is accessible in the browser, that host serves uploaded files.

Note: whether hosting porn is permitted is a policy/legal question for that hosting provider; this project only provides a technical method to upload and serve files.

Production notes
---------------

The Flask development server is not production-ready. Suggested production setup:

- Install production dependencies:

```powershell
python -m pip install -r requirements.txt
```

- Windows (simple): use `waitress`:

```powershell
waitress-serve --listen=*:3109 main:app
```

- Linux (recommended): run behind `gunicorn` and Nginx (TLS, proxy, client body size limits):

```bash
gunicorn -w 4 -b 127.0.0.1:3109 main:app
```

- Nginx snippet (inside `server` block) to allow large uploads and proxy requests:

```
client_max_body_size 1G;
location / {
	proxy_pass http://127.0.0.1:3109;
	proxy_set_header Host $host;
	proxy_set_header X-Real-IP $remote_addr;
	proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Scheduler and cleanup
---------------------

The app includes a cleanup job that deletes files not downloaded in `DELETE_AFTER_DAYS` days (default 7). For production it's safer to run that job as a single process rather than in every web worker. You can run `scheduler_runner.py` as a separate service:

```bash
python scheduler_runner.py
```

Example systemd unit for `scheduler_runner.py` (Linux)

```
[Unit]
Description=FileShare cleanup scheduler
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/porttest
ExecStart=/usr/bin/python3 scheduler_runner.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Run as a service (example):

```bash
sudo cp scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scheduler.service
```

Windows (service) notes
-----------------------
You can run the web server with `waitress` and create a Windows service using NSSM or `sc` pointing to a wrapper script that runs `waitress-serve`.

Security & production hardening
-------------------------------
- Use TLS (Let's Encrypt) at the reverse proxy.
- Add virus scanning (ClamAV) on uploaded files before storing/serving.
- Add rate limiting and per-IP quotas (Flask-Limiter included; in-memory limits are not durable — use Redis for production).
- Offload storage to S3-compatible object storage for scalability and redundancy.
- Replace SQLite with Postgres for concurrency and resilience.
- Monitor logs and add alerting.

