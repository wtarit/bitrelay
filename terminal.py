import uasyncio as asyncio
import sys
import select
import time


class Terminal:
    def __init__(self, send_message_cb, set_nick_cb, get_peers_cb,
                 get_info_cb, quit_cb, send_announce_cb):
        self._send_message = send_message_cb
        self._set_nick = set_nick_cb
        self._get_peers = get_peers_cb
        self._get_info = get_info_cb
        self._quit = quit_cb
        self._send_announce = send_announce_cb
        self._poll = select.poll()
        self._poll.register(sys.stdin, select.POLLIN)

    async def run(self):
        """Main input loop."""
        self._print_banner()
        while True:
            line = await self._read_line()
            if line is None:
                continue
            line = line.strip()
            if not line:
                continue

            if line.startswith('/'):
                await self._handle_command(line)
            else:
                await self._send_message(line)
                self.display_message(self._get_info()["nickname"], line)

    async def _read_line(self):
        """Non-blocking line reader using select.poll."""
        buf = []
        while True:
            if self._poll.poll(0):
                ch = sys.stdin.read(1)
                if ch in ('\n', '\r'):
                    if buf:
                        return ''.join(buf)
                    return None
                if ch:
                    buf.append(ch)
            await asyncio.sleep_ms(50)

    async def _handle_command(self, line):
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == '/nick':
            if arg:
                self._set_nick(arg)
                self.display_system("Nickname set to: %s" % arg.strip()[:15])
                await self._send_announce()
            else:
                self.display_system("Usage: /nick <name>")
        elif cmd == '/peers':
            self._show_peers()
        elif cmd == '/info':
            self._show_info()
        elif cmd == '/help':
            self._show_help()
        elif cmd == '/quit':
            self.display_system("Sending leave...")
            await self._quit()
            self.display_system("Goodbye!")
            raise SystemExit
        else:
            self.display_system("Unknown command. Type /help for help.")

    def display_message(self, sender, content, is_relay=False, timestamp_ms=None):
        """Display an incoming or outgoing chat message."""
        ts = _format_time(timestamp_ms)
        relay_tag = " (relay)" if is_relay else ""
        print("[%s] <%s>%s %s" % (ts, sender, relay_tag, content))

    def display_system(self, text):
        """Display a system event message."""
        print(text)

    def _print_banner(self):
        info = self._get_info()
        print("=" * 40)
        print("  bitrelay-esp32")
        print("  Peer ID: %s" % info["peer_id"])
        print("  Nickname: %s" % info["nickname"])
        print("  Type /help for commands")
        print("=" * 40)

    def _show_help(self):
        print("Commands:")
        print("  /nick <name>  - Set nickname (max 15 chars)")
        print("  /peers        - List connected peers")
        print("  /info         - Show node info")
        print("  /help         - Show this help")
        print("  /quit         - Leave mesh and exit")
        print("  <text>        - Send broadcast message")

    def _show_peers(self):
        peers = self._get_peers()
        if not peers:
            print("No peers connected.")
            return
        print("Peers (%d):" % len(peers))
        now = time.time()
        for pid, info in peers.items():
            ago = int(now - info["last_seen"])
            print("  %s (%s) - seen %ds ago" % (info["nickname"], pid[:8], ago))

    def _show_info(self):
        info = self._get_info()
        print("Peer ID:     %s" % info["peer_id"])
        print("Nickname:    %s" % info["nickname"])
        print("Connections: %d" % info["connections"])
        print("Peers:       %d" % info["peers"])


def _format_time(timestamp_ms=None):
    """Format a timestamp as HH:MM."""
    if timestamp_ms:
        # MicroPython time may not have full epoch support
        # Use local time for display
        try:
            t = time.localtime(timestamp_ms // 1000)
            return "%02d:%02d" % (t[3], t[4])
        except Exception:
            pass
    t = time.localtime()
    return "%02d:%02d" % (t[3], t[4])
