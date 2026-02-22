import os
import time
import json
import threading
import atexit
import signal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EVENT_LOG = os.path.join(BASE_DIR, 'uptime_events.jsonl')
HEARTBEAT = os.path.join(BASE_DIR, 'uptime_heartbeat.json')
HEARTBEAT_INTERVAL = 30  # seconds


def _append_event(state, ts=None):
    ts = int(ts or time.time())
    line = json.dumps({'ts': ts, 'state': state})
    with open(EVENT_LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def _write_heartbeat():
    data = {'ts': int(time.time())}
    try:
        with open(HEARTBEAT, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception:
        pass


class UptimeTracker:
    def __init__(self):
        self._running = False
        self._thr = None

    def start(self):
        # record up event
        try:
            # If last event was 'up' without a following 'down', assume previous run crashed
            last = self._read_last_event()
            now = int(time.time())
            if last and last.get('state') == 'up':
                # write an inferred down at last heartbeat (if available) or now
                hb = self._read_heartbeat_ts()
                down_ts = hb or now
                _append_event('down', ts=down_ts)
        except Exception:
            pass
        _append_event('up')
        # start heartbeat thread
        self._running = True
        self._thr = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thr.start()
        # ensure we write down on exit
        atexit.register(self.stop)
        signal.signal(signal.SIGINT, lambda *a: self.stop())
        try:
            signal.signal(signal.SIGTERM, lambda *a: self.stop())
        except Exception:
            pass

    def stop(self):
        if not self._running:
            # still append a down event to ensure pairing
            try:
                _append_event('down')
            except Exception:
                pass
            return
        self._running = False
        _append_event('down')

    def _heartbeat_loop(self):
        while self._running:
            _write_heartbeat()
            for _ in range(HEARTBEAT_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    def _read_last_event(self):
        if not os.path.exists(EVENT_LOG):
            return None
        try:
            with open(EVENT_LOG, 'rb') as f:
                # read last line efficiently
                f.seek(0, os.SEEK_END)
                pos = f.tell() - 1
                while pos > 0 and f.read(1) != b"\n":
                    pos -= 1
                    f.seek(pos, os.SEEK_SET)
                if pos > 0:
                    f.seek(pos + 1, os.SEEK_SET)
                last = f.readline().decode('utf-8').strip()
                return json.loads(last) if last else None
        except Exception:
            return None

    def _read_heartbeat_ts(self):
        if not os.path.exists(HEARTBEAT):
            return None
        try:
            with open(HEARTBEAT, 'r', encoding='utf-8') as f:
                j = json.load(f)
                return int(j.get('ts'))
        except Exception:
            return None


def _read_events():
    if not os.path.exists(EVENT_LOG):
        return []
    out = []
    try:
        with open(EVENT_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    out.sort(key=lambda x: x.get('ts', 0))
    return out


def get_30day_uptime_pct():
    now = int(time.time())
    window_start = now - 30 * 24 * 3600
    events = _read_events()
    # if no events at all, return 100% (assume up from first start)
    if not events:
        return 100.0

    # if there are events but no recorded 'down' ever, assume uptime for whole window
    if not any(e.get('state') == 'down' for e in events):
        return 100.0

    # Build timeline starting at window_start
    # Determine state at window_start
    prev_ts = window_start
    # if there are no events at or before window_start, assume service was up before first event
    if not any(e['ts'] <= window_start for e in events):
        state = 'up'
    else:
        state = 'down'
        for e in events:
            if e['ts'] <= window_start:
                state = e['state']
            else:
                break

    up_seconds = 0
    # iterate events and accumulate
    for e in events:
        ts = e['ts']
        if ts <= window_start:
            continue
        if state == 'up':
            # up period from prev_ts to ts
            up_seconds += max(0, ts - prev_ts)
        # flip state
        state = e['state']
        prev_ts = ts

    # after last event, account until now
    if prev_ts < now and state == 'up':
        up_seconds += max(0, now - prev_ts)

    total = max(1, now - window_start)
    pct = (up_seconds / total) * 100.0
    return round(pct, 2)


_GLOBAL = UptimeTracker()

def start():
    _GLOBAL.start()

def stop():
    _GLOBAL.stop()

def get_30day_pct():
    return get_30day_uptime_pct()
