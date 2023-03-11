import asyncio
import sys
import socket

from aiohttp import web

from BoardGame import BoardGame
import chess.engine
from bleak import BleakError

from WebInterface import start_server
import configargparse

# noinspection SpellCheckingInspection
"""
Mindmap:

aufstellung der startposition = neues game
wenn stellung aufgestellt, dann ist der player turn = der letzte könig der gesetzt wurde
analysefunktion bzw. schiedsrichterfunktion

funktionsweise pi:
-an
- programm wird gestartet -> sucht nach board
-> vielleicht shutdown nach 5 min
- findet board -> ließt startpos aus
- fragt nach spielerfarbe
- startet game 
- wenn matt dann restart gameloop
- wenn beide könige in der mitte (diagonal oder nebeneinander) restart gameloop, 
    wenn beide weißen damen nebeneinander shutdown
"""

options = None


# noinspection SpellCheckingInspection
async def go():
    b = BoardGame(show_valid_moves=options.show_valid_moves,
                  suggestion_book_dir=options.suggestion_book_dir,
                  engine_dir=options.engine_cmd,
                  engine_suggest_dir=options.engine_suggest_cmd,
                  eco_file=options.eco_file,
                  experimental_dragging_detection=options.experimental_dragging_detection,
                  experimental_dragging_timeout=options.experimental_dragging_timeout,
                  play_animations=options.play_animations)
    await b.connect()
    try:
        run_task = asyncio.create_task(b.run())
        return await start_server(b)
        # while not run_task.done():
        #     await asyncio.sleep(1.0)
    except BleakError:
        print("Board Disconnected. Retrying connection.")
        run_task = asyncio.create_task(b.run())
        quit()
    except KeyboardInterrupt:
        print(b.board.fen())
        await b.stop_handler()
        b.game.quit_chess_engines()
        quit()


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    # noinspection PyBroadException
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


if __name__ == "__main__":
    asyncio.set_event_loop_policy(chess.engine.EventLoopPolicy())
    p = configargparse.ArgParser(default_config_files=["./default.config", '~/.config/chessnutair.config'],
                                 ignore_unknown_config_file_keys=False)
    p.add_argument("--no_server", default=False, required=False, action="store_true")
    p.add_argument("--hosts", default='auto-hosts', required=False,
                   help='ip1:ip2, or auto-hosts to use local address')
    p.add_argument('-p', '--port', default=8080, type=int)
    p.add_argument('-e', "--engine_cmd", default="stockfish")
    p.add_argument('--no_suggestions', default=False, action="store_true", help='disable suggestions')
    p.add_argument('--engine_suggest_cmd', default='stockfish')
    p.add_argument('--suggestion_book_dir', default='/usr/share/scid/books/Elo2400.bin')
    p.add_argument('--eco_file', default='./scid.eco')
    p.add_argument('--experimental_dragging_detection', default=False, action="store_true")
    p.add_argument('--experimental_dragging_timeout', default=0.3, type=float)
    p.add_argument('--show_valid_moves', default=True, action="store_true")
    p.add_argument('--play_animations', default=True, action="store_true")
    options = p.parse_args()
    print(options)
    print(options.no_server)
    try:
        if options.no_server:
            asyncio.run(go())
        else:
            if options.hosts == 'auto-hosts':
                host = get_ip()
                print(host)
                hosts = [host, 'localhost']
                web.run_app(go(), host=hosts, port=8080)
            elif len(options.hosts) > 0:
                hosts = options.hosts
                host = hosts[0].split(':')[1:]
                host.append('localhost')
                web.run_app(go(), host=host, port=options.port)
            else:
                web.run_app(go(), host='localhost', port=8080)
    except KeyboardInterrupt:
        pass
    asyncio.get_event_loop().close()
