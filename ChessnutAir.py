"""
Discover and talk to chessnut Air devices.
See pdf file Chessnut_communications.pdf
for more information.
"""

import asyncio
import math
import time

import chess

from constants import WRITE_CHARACTERISTIC, INITIALIZATION_CODE, READ_DATA_CHARACTERISTIC, DEVICE_LIST, convertDict

from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


def loc_to_pos(location, rev=False):
    # noinspection SpellCheckingInspection
    return "hgfedcba"[location % 8]+str((8-(location//8)) if not rev else (location//8))


def board_state_as_square_and_piece(board_state):
    for i in range(32):
        pair = board_state[i]
        left = pair & 0xf
        right = pair >> 4
        str_left = convertDict[left]
        yield 63-i*2, chess.Piece.from_symbol(str_left) if str_left != ' ' else None
        str_right = convertDict[right]
        yield 63-(i*2+1), chess.Piece.from_symbol(str_right) if str_right != ' ' else None


class ChessnutAir:
    """
    Class created to discover and connect to chessnut Air devices.
    It discovers the first device with a name that matches the names in DEVICE_LIST.
    """
    def __init__(self):
        self.deviceNameList = DEVICE_LIST  # valid device name list
        self._device = self._advertisement_data = self._connection = None
        self.board_state = [0] * 32
        self._old_data = [0] * 32
        self._led_command = bytearray([0x0A, 0x08])
        self._board_changed = False
        self.cur_fen = " "
        self.to_blink = chess.SquareSet()
        self.to_light = chess.SquareSet()
        self.tick = False

    async def blink_tick(self, sleep_time=0.0):
        self.tick = not self.tick
        if self.tick:
            await self.change_leds(self.to_blink.union(self.to_light))
        else:
            await self.change_leds(self.to_light)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    def _filter_by_name(self, device: BLEDevice, _: AdvertisementData) -> bool:
        """
        Callback for each discovered device.
        return True if the device name is in the list of 
        valid device names otherwise it returns False
        """
        if any(ext in device.name for ext in self.deviceNameList):
            self._device = device
            return True
        return False

    async def discover(self):
        """Scan for chessnut Air devices"""
        print("scanning, please wait...")
        await BleakScanner.find_device_by_filter(
            self._filter_by_name)
        if self._device is None:
            print("No chessnut Air devices found")
            return
        print("done scanning")

    async def connect(self):
        """Run discover() until device is found."""
        while not self._device:
            await self.discover()

    async def piece_up(self, square: chess.Square, piece: chess.Piece):
        """Should be overriden with a function that handles piece up events."""
        raise NotImplementedError

    async def piece_down(self, square: chess.Square, piece: chess.Piece):
        """Should be overriden with a function that handles piece up events."""
        raise NotImplementedError

    async def game_loop(self):
        """Should be overriden with a function that creates an endless game loop."""
        raise NotImplementedError

    async def board_has_changed(self, timeout=0.0, sleep_time=0.4):
        """Sleeps until the board has changed or until timeout (if >0)."""
        self._board_changed = False
        end_time = time.time()+timeout if timeout > 0 else math.inf
        while not self._board_changed:
            if time.time() >= end_time:
                return False
            await self.blink_tick(sleep_time=sleep_time if sleep_time < timeout or timeout == 0.0 else timeout)
        return True

    async def change_leds(self, list_of_pos: list | chess.SquareSet):
        """
        Turns on all LEDs in list_of_pos and turns off all others.
            list_of_pos := ["e3", "a4",...]
        """
        is_square_set = isinstance(list_of_pos, chess.SquareSet)
        if is_square_set:
            arr = chess.flip_horizontal(int(list_of_pos)).to_bytes(8, byteorder='big')
        else:
            conv_letter = {"a": 128, "b": 64, "c": 32, "d": 16, "e": 8, "f": 4, "g": 2, "h": 1}
            conv_number = {"1": 7, "2": 6, "3": 5, "4": 4, "5": 3, "6": 2, "7": 1, "8": 0}
            arr = bytearray([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            if list_of_pos is None:
                return
            for pos in list_of_pos:
                arr[conv_number[pos[1]]] |= conv_letter[pos[0]]
        await self._connection.write_gatt_char(WRITE_CHARACTERISTIC, self._led_command + arr)

    async def play_animation(self, list_of_frames, sleep_time=0.5):
        """
            changes LED to a frame popped from beginning of list_of_frames
            waits for sleep_time and repeats until no more frames
        """
        for frame in list_of_frames:
            await self.change_leds(chess.SquareSet(map(lambda s: chess.parse_square(s), frame)))
            await asyncio.sleep(sleep_time)

    async def _handler(self, _, data):
        async def send_message(loc, old, new):
            if old != new:
                if new == 0:
                    await self.piece_up(loc, chess.Piece.from_symbol(convertDict[old]))
                else:
                    await self.piece_down(loc, chess.Piece.from_symbol(convertDict[new]))
        rdata = data[2:34]
        if rdata != self._old_data:
            self._board_changed = True
            self.board_state = rdata
            od = self._old_data
            self._old_data = rdata
            for i in range(32):
                if rdata[i] != od[i]:
                    cur_left = rdata[i] & 0xf
                    old_left = od[i] & 0xf
                    cur_right = rdata[i] >> 4
                    old_right = od[i] >> 4
                    await send_message(63-i*2, old_left, cur_left)  # 63-i since we get the data backwards
                    await send_message(63-(i*2+1), old_right, cur_right)

    async def run(self):
        """
        Connect to the device, start the notification handler (which calls self.piece_up() and self.piece_down())
        and wait for self.game_loop() to return.
        """
        print("device.address: ", self._device.address)

        async with BleakClient(self._device) as client:
            self._connection = client
            print(f"Connected: {client.is_connected}")
            # send initialisation string!
            await client.write_gatt_char(WRITE_CHARACTERISTIC, INITIALIZATION_CODE)  # send initialisation string
            print("Initialized")
            await client.start_notify(READ_DATA_CHARACTERISTIC, self._handler)  # start notification handler
            await self.game_loop()  # call user game loop
            await self.stop_handler()

    async def stop_handler(self):
        """Allow stopping of the handler from outside."""
        if self._connection:
            await self._connection.stop_notify(READ_DATA_CHARACTERISTIC)  # stop the notification handler

    def board_state_as_fen(self):
        fen = ''
        empty_count = 0

        def handle_empties():
            nonlocal empty_count, fen
            if empty_count > 0:
                fen += str(empty_count)
                empty_count = 0

        for square, piece in board_state_as_square_and_piece(self.board_state):
            if piece:
                handle_empties()
                fen += piece.symbol()
            else:
                empty_count += 1
            if square in chess.SquareSet(chess.BB_FILE_A):
                handle_empties()
                fen += '/'
        self.cur_fen = '/'.join(map(lambda row: ''.join(reversed(row)), fen[:-1].split('/')))
        return self.cur_fen

    def compare_board_state_to_fen(self, target_fen):
        # noinspection SpellCheckingInspection
        """
            takes target_fen and cur_fen and returns which pieces are wrong on fen2
            fen like "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            return like [['P','d4'],['1', d2']] -> '1' = empty field,  'letters' = piece
            """

        def convert_fen(fen):
            # noinspection SpellCheckingInspection
            """
                convert "r1bqkbnr/pppppppp/2n5/8/2P5/8/PP1PPPPP/RNBQKBNR w KQkq c6 0 2"
                to "r1bqkbnr/pppppppp/11n11111/11111111/11P11111/11111111/PP1PPPPP/RNBQKBNR"
                """
            fen = fen.split()[0]
            return ''.join(map(lambda p: "1" * int(p) if p.isdigit() and p != '1' else p, fen))

        target = ''.join(reversed(convert_fen(target_fen).split("/")))
        differences = []
        for square, piece in board_state_as_square_and_piece(self.board_state):
            new_piece = chess.Piece.from_symbol(target[square]) if target[square] != '1' else None
            if piece != new_piece:
                differences.append((piece, square, new_piece))
        return differences
