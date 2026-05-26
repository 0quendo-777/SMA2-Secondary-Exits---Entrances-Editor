"""
SMA2 (Super Mario Advance 2) - Screen Exit / Entrance Editor by Oquendo
=========================================================================================
Reads and modifies screen exits (object 00.00) in sublevel layer 1 data.

Object stream format (per documentation):
  Most objects are 3 bytes:
    byte 0: bit7=new_screen_flag, bit6-5=objID[5:4], bit4-0=Y_pos
    byte 1: bit7-4=objID[3:0], bit3-0=X_pos_low_digit
    byte 2: bit7-4=height, bit3-0=width  (or extID for global obj 00 and others)
  Full 6-bit object ID = (byte0[6:5] << 4) | byte1[7:4]

  Object ID 0x00 = global fixed-size objects; byte 2 = extended sub-ID:
    00.00  Screen exit         (4 bytes)
    00.01  Change screen #     (3 bytes)
    00.xx  Other globals       (3 bytes)

  Object 00.00 byte layout:
    byte 0: bit7=new_screen_flag, bit6-5=00, bit4-0=screen_number
    byte 1: bit7-4=0000, bit3-1=secondary_entrance_flag (any nonzero = secondary mode), bit0=unused
    byte 2: 0x00  (ext sub-ID confirming screen exit)
    byte 3: destination low byte (high bit inherited from current sublevel range)

  IMPORTANT - destination high bit:
    Only the low byte of the destination sublevel is stored.
    The high bit comes from the current sublevel:
      sublevel 0x000-0x0FF  →  dest is in 0x000-0x0FF
      sublevel 0x100-0x1FF  →  dest is in 0x100-0x1FF
    So a level like YI1 (sublevel 0x105) with dest byte=0xEF → sublevel 0x1EF.
    This is why a "same level" exit like the secret pipe works:
    dest byte=0x05 in sublevel 0x105 → 0x105 (same level, different entrance).

Secondary entrance tables (0x200 entries, 1 byte each at):
  080F4744: sublevel ID low byte
  080F4944: data byte 1  →  bits 7-4 = Y position (0-F), bit 1 = layer 2 scroll flag
  080F4B44: data byte 2  →  bits 7-4 = X position (0-F), bits 3-0 = reserved/zero
  080F4D44: data byte 3  →  bits 4-0 = screen number (0x00-0x1F)
  080F4F44: entrance animation (0-7)
    0 = walk right (from left pipe / left edge)
    1 = walk left  (from right pipe / right edge)
    2 = fall from above
    3 = enter pipe from top (coming down)
    4 = enter pipe from bottom (coming up)
    5 = enter door
    6 = fly in
    7 = warp (no animation / instant)
"""

import sys
import struct
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

class C:
    SUCCESS = "\033[38;2;180;230;210m"   # pastel mint / teal-green
    INFO    = "\033[38;2;255;200;220m"   # pastel rose / pink
    OPTION  = "\033[38;2;255;235;150m"   # pastel golden yellow
    ERROR   = "\033[38;2;255;160;130m"   # pastel coral / salmon
    HEADER  = "\033[38;2;150;220;255m"   # pastel sky blue
    RESET   = "\033[0m"

def ok(msg):   return f"{C.SUCCESS}{msg}{C.RESET}"
def info(msg): return f"{C.INFO}{msg}{C.RESET}"
def opt(msg):  return f"{C.OPTION}{msg}{C.RESET}"
def err(msg):  return f"{C.ERROR}{msg}{C.RESET}"
def hdr(msg):  return f"{C.HEADER}{msg}{C.RESET}"


def print_banner():
    logo = f"""
{C.INFO}  ███████╗███╗   ███╗ █████╗ ██████╗
{C.INFO}  ██╔════╝████╗ ████║██╔══██╗╚════██╗
{C.INFO}  ███████╗██╔████╔██║███████║ █████╔╝
{C.INFO}  ╚════██║██║╚██╔╝██║██╔══██║██╔═══╝
{C.INFO}  ███████║██║ ╚═╝ ██║██║  ██║███████╗
{C.INFO}  ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝{C.RESET}
{C.OPTION}        Screen Exit / Entrance Editor{C.RESET}
"""
    border = f"{C.INFO}  {'─' * 52}{C.RESET}"
    print(logo)
    print(border)
    print(f"  {ok('Version')} : v0.1          {info('Author')} : Oquendo")
    print(f"  {ok('ROM')}     : Super Mario Advance 2 (GBA)")
    print(border)
    print(f"""
  {hdr('Commands')}

  {opt('1.')} {ok('list')} {info('<sublevel_id>')}
     See all exits in a sublevel and where each one leads.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba list 0x105{C.RESET}
     {C.HEADER}→ Shows every screen exit in sublevel 0x105 (YI1) with its destination.{C.RESET}

  {opt('2.')} {ok('get')} {info('<sublevel_id>')}
     Full details: raw bytes, resolved sublevel, secondary entrance info.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba get 0x105{C.RESET}
     {C.HEADER}→ Also lists which secondary entrance slots land inside this sublevel.{C.RESET}

  {opt('3.')} {ok('set-dest')} {info('<sublevel_id> <screen> <dest_byte>')}
     Change the raw destination byte of an exit (advanced — you must know the byte).
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba set-dest 0x1CA 0x01 0xCB{C.RESET}
     {C.HEADER}→ The exit on screen 0x01 of sublevel 0x1CA now points to slot 0x1CB.{C.RESET}

  {opt('4.')} {ok('link')} {info('<from_sublevel> <screen> <to_sublevel>')}
     Wire an exit to another sublevel's secondary entrance automatically.
     No slot IDs, no bytes — the script finds the right entrance for you.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba link 0x1CA 0x01 0x105{C.RESET}
     {C.HEADER}→ The exit on screen 0x01 of sublevel 0x1CA now sends Mario to{C.RESET}
     {C.HEADER}  sublevel 0x105's secondary entrance (slot 0x1CB, fly-in on screen 0x08).{C.RESET}
     {C.HEADER}  If multiple entrances exist you'll be shown a list to choose from.{C.RESET}
  {opt('5.')} {ok('audit')} {info('<sublevel_id> [<sublevel_id> ...]')}
     Audit multiple sublevels at once: exits and secondary entrances for each.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba audit 0x105 0x106 0x1CB{C.RESET}
     {C.HEADER}→ Shows exits and sec entrances for YI1, YI2, and slot 0x1CB.{C.RESET}

  {opt('6.')} {ok('slot-find')} {info('<sublevel_id>')}
     Find which secondary entrance slots land in a given sublevel.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba slot-find 0x106{C.RESET}
     {C.HEADER}→ Shows slots that send Mario to YI2 and their animations.{C.RESET}

  {opt('7.')} {ok('anim-list')} {info('(no args)')}
     List all sublevels that have slots, grouped — shows which slots
     land in each sublevel and their animations.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba anim-list{C.RESET}
     {C.HEADER}→ See every sublevel and which slot IDs to edit for animations.{C.RESET}
""")
    print(border)
    print(f"  {info('Low-level slot commands:')}")
    print(f"  {C.OPTION}set-screen  sec-list  sec-info  slot-find  anim-list{C.RESET}")
    print(f"  {C.OPTION}sec-set  sec-screen  sec-pos  sec-anim  sec-edit{C.RESET}")
    print(f"  {C.HEADER}Run: {C.SUCCESS}python sma2_exit_editor.py sma2.gba help{C.HEADER}  to see all of them with examples.{C.RESET}")
    print()
    print(border)
    print()


GBA_ROM_BASE    = 0x08000000
L1_TABLE_OFFSET = 0x080F22CC - GBA_ROM_BASE   # 0x0F22CC
L1_TABLE_SIZE   = 0x209

SEC_SUBLEVEL_OFF = 0x080F4744 - GBA_ROM_BASE
SEC_BYTE1_OFF    = 0x080F4944 - GBA_ROM_BASE
SEC_BYTE2_OFF    = 0x080F4B44 - GBA_ROM_BASE
SEC_BYTE3_OFF    = 0x080F4D44 - GBA_ROM_BASE
SEC_ANIM_OFF     = 0x080F4F44 - GBA_ROM_BASE
SEC_TABLE_SIZE   = 0x200

ENTRANCE_ANIM_NAMES = {
    0: "walk right (from left pipe)",
    1: "walk left (from right pipe)",
    2: "fall from above",
    3: "enter pipe from top",
    4: "enter pipe from bottom",
    5: "enter door",
    6: "fly in",
    7: "warp (no animation)",
}

LEVEL_NAMES = {
    # Keys are full sublevel IDs (0x000–0x208).
    0x000: "Infinite Bonus game",
    0x001: "Vanilla Secret 2",
    0x002: "Vanilla Secret 3",
    0x003: "Top Secret Area",
    0x004: "Donut Ghost House",
    0x005: "Donut Plains 3",  # DP3 main
    0x006: "Donut Plains 4",  # DP4 main
    0x007: "#2 Morton's Castle",  # Castle2 1/3
    0x008: "Green Switch Palace",  # GSP main
    0x009: "Donut Plains 2",  # DP2 main
    0x00A: "Donut Secret 1",
    0x00B: "Vanilla Fortress",
    0x00C: "Butter Bridge 1",
    0x00D: "Butter Bridge 2",
    0x00E: "#4 Ludwig's Castle",
    0x00F: "Cheese Bridge Area",  # CBA main
    0x010: "Cookie Mountain",  # Cookie Mountain main
    0x011: "Soda Lake",
    0x012: "Test Level",
    0x013: "Donut Secret House",
    0x014: "Yellow Switch Palace",
    0x015: "Donut Plains 1",
    0x016: "Donut Plains 1 (Duplicate)",
    0x017: "Donut Plains 1 (Duplicate 2)",
    0x018: "Sunken Ghost Ship",
    0x019: "Test Level 2",
    0x01A: "#6 Wendy's Castle",  # Castle6 1/2
    0x01B: "Chocolate Fortress",
    0x01C: "Chocolate Island 5",
    0x01D: "Chocolate Island 4",
    0x01E: "Test Level 3",
    0x01F: "Forest Fortress",
    0x020: "#5 Roy's Castle",
    0x021: "Choco-Ghost House",
    0x022: "Chocolate Island 1",
    0x023: "Chocolate Island 3",
    0x024: "Chocolate Island 2", # CI2 1/4

    #==================================================================
    #            !! BUNCH OF TEST LEVELS 0x025-0x0BC !!               #
    #==================================================================

    0x025: "",
    0x026: "",
    0x027: "",
    0x028: "",
    0x029: "",
    0x02A: "",
    0x02B: "",
    0x02C: "",
    0x02D: "",
    0x02E: "",
    0x02F: "",
    0x030: "",
    0x031: "",
    0x032: "",
    0x033: "",
    0x034: "",
    0x035: "",
    0x036: "",
    0x037: "",
    0x038: "",
    0x039: "",
    0x03A: "",
    0x03B: "",
    0x03C: "",
    0x03D: "",
    0x03E: "",
    0x03F: "",
    0x040: "",
    0x041: "",
    0x042: "",
    0x043: "",
    0x044: "",
    0x045: "",
    0x046: "",
    0x047: "",
    0x048: "",
    0x049: "",
    0x04A: "",
    0x04B: "",
    0x04C: "",
    0x04D: "",
    0x04E: "",
    0x04F: "",
    0x050: "",
    0x051: "",
    0x052: "",
    0x053: "",
    0x054: "",
    0x055: "",
    0x056: "",
    0x057: "",
    0x058: "",
    0x059: "",
    0x05A: "",
    0x05B: "",
    0x05C: "",
    0x05D: "",
    0x05E: "",
    0x05F: "",
    0x060: "",
    0x061: "",
    0x062: "",
    0x063: "",
    0x064: "",
    0x065: "",
    0x066: "",
    0x067: "",
    0x068: "",
    0x069: "",
    0x06A: "",
    0x06B: "",
    0x06C: "",
    0x06D: "",
    0x06E: "",
    0x06F: "",
    0x070: "",
    0x071: "",
    0x072: "",
    0x073: "",
    0x074: "",
    0x075: "",
    0x076: "",
    0x077: "",
    0x078: "",
    0x079: "",
    0x07A: "",
    0x07B: "",
    0x07C: "",
    0x07D: "",
    0x07E: "",
    0x07F: "",
    0x080: "",
    0x081: "",
    0x082: "",
    0x083: "",
    0x084: "",
    0x085: "",
    0x086: "",
    0x087: "",
    0x088: "",
    0x089: "",
    0x08A: "",
    0x08B: "",
    0x08C: "",
    0x08D: "",
    0x08E: "",
    0x08F: "",
    0x090: "",
    0x091: "",
    0x092: "",
    0x093: "",
    0x094: "",
    0x095: "",
    0x096: "",
    0x097: "",
    0x098: "",
    0x099: "",
    0x09A: "",
    0x09B: "",
    0x09C: "",
    0x09D: "",
    0x09E: "",
    0x09F: "",
    0x0A0: "",
    0x0A1: "",
    0x0A2: "",
    0x0A3: "",
    0x0A4: "",
    0x0A5: "",
    0x0A6: "",
    0x0A7: "",
    0x0A8: "",
    0x0A9: "",
    0x0AA: "",
    0x0AB: "",
    0x0AC: "",
    0x0AD: "",
    0x0AE: "",
    0x0AF: "",
    0x0B0: "",
    0x0B1: "",
    0x0B2: "",
    0x0B3: "",
    0x0B4: "",
    0x0B5: "",
    0x0B6: "",
    0x0B7: "",
    0x0B8: "",
    0x0B9: "",
    0x0BA: "",
    0x0BB: "",
    0x0BC: "",

    # ==============================================================================================================

    0x0BD: "BONUS STAGE (CI5)",
    0x0BE: "",
    0x0BF: "Secret Stage (CBA)",
    0x0C0: "Secret Stage (CI5)",
    0x0C1: "",
    0x0C2: "Secret Stage (DS1)",
    0x0C3: "Secret Stage (DP4)",
    0x0C4: "Ghost House Exit",
    0x0C5: "Welcome to Dinosaourland",
    0x0C6: "Big Mountains Exit",
    0x0C7: "Title screen",
    0x0C8: "Flying Yoshi's Bonus Stage",
    0x0C9: "Green Switch Palace Room",
    0x0CA: "Yellow Switch Palace Room",
    0x0CB: "Big Clouds Exit",
    0x0CC: "",
    0x0CD: "CI2 room 4 4+: P-switch",  # CI2 room 4 4+: P-switch
    0x0CE: "CI2 room 3 0-229: Bubbled mushrooms",  # CI2 room 3 0-229: Bubbled mushrooms
    0x0CF: "CI2 room 2 20+: Cape",  # CI2 room 2 20+: Cape
    0x0D0: "",
    0x0D1: "",
    0x0D2: "DP4 Secret Stage",
    0x0D3: "Wendy's Boss Room",
    0x0D4: "Castle Before Wendy's Boss Room",
    0x0D5: "",
    0x0D6: "",
    0x0D7: "CI3 Bonus Room",
    0x0D8: "Vanilla Secret 1 Bonus Room",
    0x0D9: "",
    0x0DA: "",
    0x0DB: "",
    0x0DC: "",
    0x0DD: "",
    0x0DE: "",
    0x0DF: "",
    0x0E0: "",
    0x0E1: "",
    0x0E2: "",
    0x0E3: "",
    0x0E4: "",
    0x0E5: "",
    0x0E6: "",
    0x0E7: "",
    0x0E8: "",
    0x0E9: "",
    0x0EA: "",
    0x0EB: "",
    0x0EC: "",
    0x0ED: "",
    0x0EE: "",
    0x0EF: "",
    0x0F0: "",
    0x0F1: "",
    0x0F2: "",
    0x0F3: "",
    0x0F4: "Donuut Plains 3 duplicate???",  # DP3 5-tier bonus
    0x0F5: "",
    0x0F6: "",
    0x0F7: "",
    0x0F8: "",
    0x0F9: "",
    0x0FA: "",
    0x0FB: "",
    0x0FC: "",
    0x0FD: "",
    0x0FE: "",
    0x0FF: "",
    0x100: "Bonus game, submaps",
    0x101: "#1 Iggy's Castle",  # Castle1 1/2
    0x102: "Yoshi's Island 4",  # YI4 main
    0x103: "Yoshi's Island 3",  # YI3 main
    0x104: "Yoshi's House",
    0x105: "Yoshi's Island 1",  # YI1 main
    0x106: "Yoshi's Island 2",  # YI2 main
    0x107: "Vanilla Ghost House",
    0x108: "Intro Cutscene",  # Story intro
    0x109: "Vanilla Secret 1",
    0x10A: "Vanilla Dome 3",
    0x10B: "Donut Secret 2",
    0x10C: "Test Level 4",
    0x10D: "Front Door (Bowser's Castle)",
    0x10E: "Back Door (Bowser's Castle)",
    0x10F: "Valley of Bowser 4",
    0x110: "#7 Larry's Castle",
    0x111: "Valley Fortress",
    0x112: "Test Level 5",
    0x113: "Valley of Bowser 3",
    0x114: "Valley Ghost House",
    0x115: "Valley of Bowser 2",
    0x116: "Valley of Bowser 1",
    0x117: "Chocolate Secret",
    0x118: "Vanilla Dome 2",
    0x119: "Vanilla Dome 4",
    0x11A: "Vanilla Dome 1",  # VD1 1/3 + 3/3
    0x11B: "Red Switch Palace",
    0x11C: "#3 Lemmy's Switch Palace",
    0x11D: "Forest Ghost House",
    0x11E: "Forest of Illusion 1",
    0x11F: "Forest of Illusion 4",
    0x120: "Forest of Illusion 2",
    0x121: "Blue Switch Palace",
    0x122: "Forest Secret Area",
    0x123: "Forest of Illusion 3",
    0x124: "Test Level 6",
    0x125: "Funky",
    0x126: "Outrageous",
    0x127: "Mondo",
    0x128: "Groovy",
    0x129: "Test Level 7",
    0x12A: "Gnarly",
    0x12B: "Tubular",
    0x12C: "Way Cool",
    0x12D: "Awesome",
    0x12E: "Test Level 8",
    0x12F: "Test Level 9",
    0x130: "Star World 2",
    0x131: "Test Level 10",
    0x132: "Star World 3",
    0x133: "Test Level 11",
    0x134: "Star World 1",
    0x135: "Star World 4",
    0x136: "Star World 5",
    0x137: "Test Level 12",
    0x138: "Test Level 13",
    0x139: "Test Level 14",
    0x13A: "Test Level 15",
    0x13B: "Test Level 16",
    0x13C: "",
    0x13D: "",
    0x13E: "",
    0x13F: "",
    0x140: "",
    0x141: "",
    0x142: "",
    0x143: "",
    0x144: "",
    0x145: "",
    0x146: "",
    0x147: "",
    0x148: "",
    0x149: "",
    0x14A: "",
    0x14B: "",
    0x14C: "",
    0x14D: "",
    0x14E: "",
    0x14F: "",
    0x150: "",
    0x151: "",
    0x152: "",
    0x153: "",
    0x154: "",
    0x155: "",
    0x156: "",
    0x157: "",
    0x158: "",
    0x159: "",
    0x15A: "",
    0x15B: "",
    0x15C: "",
    0x15D: "",
    0x15E: "",
    0x15F: "",
    0x160: "",
    0x161: "",
    0x162: "",
    0x163: "",
    0x164: "",
    0x165: "",
    0x166: "",
    0x167: "",
    0x168: "",
    0x169: "",
    0x16A: "",
    0x16B: "",
    0x16C: "",
    0x16D: "",
    0x16E: "",
    0x16F: "",
    0x170: "",
    0x171: "",
    0x172: "",
    0x173: "",
    0x174: "",
    0x175: "",
    0x176: "",
    0x177: "",
    0x178: "",
    0x179: "",
    0x17A: "",
    0x17B: "",
    0x17C: "",
    0x17D: "",
    0x17E: "",
    0x17F: "",
    0x180: "",
    0x181: "",
    0x182: "",
    0x183: "",
    0x184: "",
    0x185: "",
    0x186: "",
    0x187: "",
    0x188: "",
    0x189: "",
    0x18A: "",
    0x18B: "",
    0x18C: "",
    0x18D: "",
    0x18E: "",
    0x18F: "",
    0x190: "",
    0x191: "",
    0x192: "",
    0x193: "",
    0x194: "",
    0x195: "",
    0x196: "",
    0x197: "",
    0x198: "",
    0x199: "",
    0x19A: "",
    0x19B: "",
    0x19C: "",
    0x19D: "",
    0x19E: "",
    0x19F: "",
    0x1A0: "",
    0x1A1: "",
    0x1A2: "",
    0x1A3: "",
    0x1A4: "",
    0x1A5: "",
    0x1A6: "",
    0x1A7: "",
    0x1A8: "",
    0x1A9: "",
    0x1AA: "",
    0x1AB: "",
    0x1AC: "",
    0x1AD: "",
    0x1AE: "",
    0x1AF: "",
    0x1B0: "",
    0x1B1: "",
    0x1B2: "",
    0x1B3: "",
    0x1B4: "",
    0x1B5: "",
    0x1B6: "",
    0x1B7: "",
    0x1B8: "",
    0x1B9: "",
    0x1BA: "",
    0x1BB: "",
    0x1BC: "",
    0x1BD: "",
    0x1BE: "",
    0x1BF: "",
    0x1C0: "",
    0x1C1: "",
    0x1C2: "",
    0x1C3: "",
    0x1C4: "",
    0x1C5: "",
    0x1C6: "",
    0x1C7: "",
    0x1C8: "",
    0x1C9: "",
    0x1CA: "",
    0x1CB: "",
    0x1CC: "",
    0x1CD: "",
    0x1CE: "",
    0x1CF: "",
    0x1D0: "",
    0x1D1: "",
    0x1D2: "",  # Front Door room 3
    0x1D3: "",
    0x1D4: "",
    0x1D5: "",
    0x1D6: "",
    0x1D7: "",
    0x1D8: "",
    0x1D9: "",
    0x1DA: "",
    0x1DB: "",
    0x1DC: "",
    0x1DD: "",
    0x1DE: "",
    0x1DF: "",
    0x1E0: "",
    0x1E1: "",
    0x1E2: "",
    0x1E3: "",
    0x1E4: "",
    0x1E5: "",
    0x1E6: "",
    0x1E7: "",
    0x1E8: "",
    0x1E9: "",
    0x1EA: "",
    0x1EB: "",
    0x1EC: "",
    0x1ED: "",
    0x1EE: "",
    0x1EF: "",
    0x1F0: "",
    0x1F1: "",
    0x1F2: "",
    0x1F3: "",
    0x1F4: "",
    0x1F5: "",
    0x1F6: "",
    0x1F7: "",
    0x1F8: "",
    0x1F9: "",
    0x1FA: "",
    0x1FB: "",
    0x1FC: "",
    0x1FD: "",
    0x1FE: "",
    0x1FF: "",  # YI4 goal
    0x200: "",  # CI2 room 4 4: P-switch
    0x201: "",  # CI2 room 4 0-3: Rex goal room
    0x202: "",  # CI2 room 4 0-3: Rex goal room (unused duplicate of 201)
    0x203: "",  # CI2 room 2 21+: Cape
    0x204: "",  # CI2 room 2 9-20: Rexes etc
    0x205: "",  # CI2 room 2 0-8: Paratroopa slopes
    0x206: "",  # CI2 room 3 0-234: Bubbled mushrooms
    0x207: "",  # CI2 room 3 235-249: Rhinos
    0x208: "",  # CI2 room 3 250+: secret exit
}


def level_name(level_id: int) -> str:
    # LEVEL_NAMES is keyed by full sublevel ID.
    name = LEVEL_NAMES.get(level_id, "")
    if name:
        return name
    return f"(sublevel 0x{level_id:03X})"



def check_rom(data: bytes) -> bool:
    if len(data) < 0xB0:
        return False
    title = data[0xA0:0xAC].rstrip(b'\x00')
    code  = data[0xAC:0xB0]
    return b'MARIO' in title.upper() and code == b'AA2E'


def out_path_for(rom_path: Path) -> Path:
    return rom_path  # always write back in-place


def get_l1_ptr(data: bytes, sublevel_id: int) -> int:
    off = L1_TABLE_OFFSET + sublevel_id * 4
    return struct.unpack_from('<I', data, off)[0]


# ── Object stream parser ──────────────────────────────────────────────────────

def parse_screen_exits(data: bytes, sublevel_id: int):
    """
    Walk the layer 1 object data stream and return all screen exit objects
    (object 00.00, 4 bytes each).

    The layer 1 block starts with a 7-byte sublevel header which is skipped
    before parsing begins.  Object data follows immediately after the header,
    terminated by 0xFF.

    Object ID encoding:
      6-bit ID = (byte0[6:5] << 4) | byte1[7:4]
      ID 0x00 = global objects; byte2 = extended sub-ID
        sub 0x00 = screen exit (4 bytes)
        sub 0x01 = change-screen command (2 bytes)
        sub else = other global object (3 bytes)

    Screen exit (00.00) layout:
      byte 0: bit7=new_screen_flag, bit4-0=screen_number  (bits 6-5 are 00)
      byte 1: bit1=secondary_flag, bit0=unused  (bits 7-4 are 0000)
      byte 2: 0x00 (sub-ID)
      byte 3: destination low byte

    Destination resolution:
      Only the low byte is stored. The high bit is taken from the current sublevel:
        sublevel >= 0x100  →  dest_full = 0x100 | dest_byte
        sublevel <  0x100  →  dest_full = dest_byte
      This means a pipe back to the same level is just dest_byte = sublevel & 0xFF.

    Returns: (exits: list[dict], secondary_mode: bool)
      secondary_mode is from the LAST 00.00 found (it affects ALL exits).
    """
    gba_ptr = get_l1_ptr(data, sublevel_id)
    if gba_ptr < GBA_ROM_BASE:
        return [], False

    rom_off = gba_ptr - GBA_ROM_BASE
    if rom_off >= len(data):
        return [], False

    # Layer 1 data begins with a 7-byte sublevel header (level mode, palette,
    # tileset, music, timer, etc.).  Object data starts immediately after.
    HEADER_SIZE = 7
    rom_off += HEADER_SIZE
    if rom_off >= len(data):
        return [], False

    # High-bit group for destination resolution.
    # The game inherits only bit 8 (0x100) from the current sublevel into the destination.
    # For CI2 sublevels 0x200-0x208, dest_high is still 0x100 (not 0x200) —
    # this matches actual game behaviour; the destination resolves to 0x1XX.
    dest_high = 0x100 if sublevel_id >= 0x100 else 0x000

    exits         = []
    secondary_mode = False
    pos            = rom_off
    MAX_SCAN       = 0x8000
    end_guard      = min(rom_off + MAX_SCAN, len(data) - 1)

    while pos <= end_guard:
        b0 = data[pos]
        if b0 == 0xFF:
            break   # end of object data

        # bits 6-5 of b0 = upper 2 bits of 6-bit object ID
        obj_id_hi = (b0 >> 5) & 0x03

        if pos + 1 > end_guard:
            break
        b1 = data[pos + 1]
        # bits 7-4 of b1 = lower 4 bits of 6-bit object ID
        obj_id_lo = (b1 >> 4) & 0x0F

        obj_id = (obj_id_hi << 4) | obj_id_lo   # 6-bit value

        if obj_id == 0x00:
            # Global object — sub-ID in byte 2
            if pos + 2 > end_guard:
                break
            b2     = data[pos + 2]
            sub_id = b2

            if sub_id == 0x00:
                # ── Screen exit (4 bytes) ──────────────────────────────────
                if pos + 3 > end_guard:
                    break
                b3 = data[pos + 3]

                screen_num = b0 & 0x1F           # bits 4-0 of byte 0
                sec_flag   = bool(b1 & 0x02)     # bit 1 of byte 1 is the secondary entrance flag
                dest_low   = b3
                dest_full  = dest_high | dest_low

                exits.append({
                    'rom_offset':     pos,
                    'screen':         screen_num,
                    'secondary_flag': sec_flag,
                    'dest_low':       dest_low,
                    'dest_full':      dest_full,
                    'raw':            bytes(data[pos:pos + 4]),
                })
                secondary_mode = sec_flag
                pos += 4

            elif sub_id == 0x01:
                # ── Change-screen-number command (3 bytes: b0, b1=0x00, b2=0x01) ──
                pos += 3

            else:
                # ── Other global extended objects (3 bytes) ────────────────
                pos += 3
        else:
            # Standard tileset objects — always 3 bytes in vanilla
            pos += 3

    return exits, secondary_mode


# ── Secondary entrance helpers ────────────────────────────────────────────────

def get_sec_info(data: bytes, sec_id: int) -> dict:
    return {
        'sublevel_low': data[SEC_SUBLEVEL_OFF + sec_id],
        'byte1':        data[SEC_BYTE1_OFF    + sec_id],
        'byte2':        data[SEC_BYTE2_OFF    + sec_id],
        'byte3':        data[SEC_BYTE3_OFF    + sec_id],
        'anim':         data[SEC_ANIM_OFF     + sec_id],
    }


def find_secondary_entrances(data: bytes, sublevel_id: int) -> list:
    """Return all secondary entrance slots that point into sublevel_id.

    The secondary entrance table at 080F4744 stores the LOW BYTE of the destination
    sublevel, indexed by slot ID.  The high bit of the full sublevel comes from the
    slot ID itself (same rule as screen exits).  byte3 (080F4D44) is the screen
    number the player spawns on when arriving via that entrance.
    """
    entrances = []
    for sid in range(SEC_TABLE_SIZE):
        sub_low   = data[SEC_SUBLEVEL_OFF + sid]
        dest_high = 0x100 if sid >= 0x100 else 0x000
        sub_full  = dest_high | sub_low
        if sub_full == sublevel_id:
            entrances.append({
                'slot_id': sid,
                'screen':  data[SEC_BYTE3_OFF + sid],
                'anim':    data[SEC_ANIM_OFF  + sid],
                'byte1':   data[SEC_BYTE1_OFF + sid],
                'byte2':   data[SEC_BYTE2_OFF + sid],
                'byte3':   data[SEC_BYTE3_OFF + sid],
            })
    return entrances


def format_dest(data: bytes, ex: dict, secondary_mode: bool) -> str:
    dest_full = ex['dest_full']   # already has high bit applied from current sublevel
    if secondary_mode:
        # Slot ID = dest_full (high bit inherited). Slot's sublevel_low also needs that high bit.
        slot_id   = dest_full
        si        = get_sec_info(data, slot_id)
        dest_high = 0x100 if slot_id >= 0x100 else 0x000
        sub_full  = dest_high | si['sublevel_low']
        anim_name = ENTRANCE_ANIM_NAMES.get(si['anim'], '?')
        return (f"sec 0x{slot_id:03X}  "
                f"→ sublevel 0x{sub_full:03X} ({level_name(sub_full)})  "
                f"anim={si['anim']} ({anim_name})")
    else:
        return f"sublevel 0x{dest_full:03X}  ({level_name(dest_full)})"


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list(data: bytes, sublevel_id: int):
    gba_ptr = get_l1_ptr(data, sublevel_id)

    print(f"\n  {hdr('Sublevel')} : 0x{sublevel_id:03X}  {level_name(sublevel_id)}")
    print(f"  {hdr('L1 ptr')}   : 0x{gba_ptr:08X}  (ROM 0x{gba_ptr - GBA_ROM_BASE:06X})")

    exits, secondary_mode = parse_screen_exits(data, sublevel_id)

    if not exits:
        print(f"\n  {err('No screen exits (object 00.00) found in this sublevel.')}\n")
        return

    mode_str = ok("secondary entrance IDs") if secondary_mode else info("direct sublevel IDs")
    print(f"\n  {info('Exit mode')} : all exits use {mode_str}")
    print()
    print(f"  {'Screen':>8}  {'Dest byte':>9}  {'Sec?':>4}  {'ROM off':>8}  Destination")
    print("  " + "─" * 84)
    for ex in exits:
        dest_str = format_dest(data, ex, secondary_mode)
        sec_mark = opt(" YES") if ex['secondary_flag'] else " no "
        print(f"  screen 0x{ex['screen']:02X}    0x{ex['dest_low']:02X}     {sec_mark}  "
              f"0x{ex['rom_offset']:06X}  {dest_str}")
    print()


def cmd_get(data: bytes, sublevel_id: int):
    gba_ptr = get_l1_ptr(data, sublevel_id)

    print(f"\n  {hdr('─' * 54)}")
    print(f"  {hdr('Sublevel')} : 0x{sublevel_id:03X}  {level_name(sublevel_id)}")
    print(f"  {hdr('L1 ptr')}   : 0x{gba_ptr:08X}  (ROM 0x{gba_ptr - GBA_ROM_BASE:06X})")

    exits, secondary_mode = parse_screen_exits(data, sublevel_id)

    if not exits:
        print(f"\n  {err('No screen exits found.')}\n")
        return

    mode_str = ok("secondary entrance IDs") if secondary_mode else info("direct sublevel IDs")
    print(f"  {hdr('Exit mode')} : {mode_str}")
    print(f"  {hdr('Note')}      : dest high bit from sublevel range "
          f"(0x{'1' if sublevel_id >= 0x100 else '0'}xx)\n")

    for i, ex in enumerate(exits, 1):
        raw   = ex['raw']
        roff  = ex['rom_offset']
        screen = ex['screen']

        print(f"  {opt(f'Exit #{i}')}  ─  screen 0x{screen:02X}  ─  ROM 0x{roff:06X}")
        print(f"    {info('Raw bytes')}       : {' '.join(f'{b:02X}' for b in raw)}")
        print(f"    {info('Screen number')}   : 0x{screen:02X}")
        print(f"    {info('Secondary flag')}  : {ex['secondary_flag']}  (byte 1 bits 1-3)")
        print(f"    {info('Dest byte (b3)')}  : 0x{ex['dest_low']:02X}")
        print(f"    {info('Dest resolved')}   : 0x{ex['dest_full']:03X}  "
              f"(= 0x{('1' if sublevel_id >= 0x100 else '0')}00 | 0x{ex['dest_low']:02X})")

        if secondary_mode:
            slot_id   = ex['dest_full']   # high bit inherited from current sublevel
            si        = get_sec_info(data, slot_id)
            dest_high = 0x100 if slot_id >= 0x100 else 0x000
            sub_full  = dest_high | si['sublevel_low']
            anim_name = ENTRANCE_ANIM_NAMES.get(si['anim'], '?')
            print(f"    {info('→ sec entrance')}  : 0x{slot_id:03X}")
            print(f"       {info('sublevel')}      : 0x{sub_full:03X}  "
                  f"({level_name(sub_full)})")
            print(f"       {info('animation')}     : {si['anim']}  ({anim_name})")
            print(f"       {info('data b1/b2/b3')} : 0x{si['byte1']:02X} / "
                  f"0x{si['byte2']:02X} / 0x{si['byte3']:02X}")
        else:
            print(f"    {info('→ sublevel')}      : 0x{ex['dest_full']:03X}  "
                  f"({level_name(ex['dest_full'])})")
        print()

    # ── Secondary entrances that land inside this sublevel ────────────────
    sec_entrances = find_secondary_entrances(data, sublevel_id)
    if sec_entrances:
        print(f"  {hdr('Secondary Entrances landing in this sublevel')}")
        print(f"  {'─' * 54}")
        for se in sec_entrances:
            anim_name = ENTRANCE_ANIM_NAMES.get(se['anim'], '?')
            slot_str  = f"Sec slot 0x{se['slot_id']:03X}"
            si_tmp = {'byte1': se['byte1'], 'byte2': se['byte2'], 'byte3': se['byte3']}
            x_tile = (se['byte2'] >> 4) & 0x0F
            y_tile = (se['byte1'] >> 4) & 0x0F
            screen = se['byte3'] & 0x1F
            print(f"  {opt(slot_str)}  screen=0x{screen:02X}  x={x_tile}  y={y_tile}  "
                  f"anim={se['anim']} ({anim_name})")
        print()


def cmd_set_dest(data: bytearray, sublevel_id: int, screen: int, new_dest: int,
                 out_path: Path, secondary_flag: bool = False) -> bool:
    exits, secondary_mode = parse_screen_exits(data, sublevel_id)

    matches = [ex for ex in exits if ex['screen'] == screen]
    if not matches:
        available = [f"0x{ex['screen']:02X}" for ex in exits]
        print(err(f"\n  Error: no exit on screen 0x{screen:02X} in sublevel 0x{sublevel_id:03X}."
                  f"\n  Available screens: {', '.join(available) if available else 'none'}\n"))
        return False

    ex   = matches[0]
    roff = ex['rom_offset']
    old  = ex['dest_low']
    old_byte1 = data[roff + 1]

    # Update destination byte
    data[roff + 3] = new_dest & 0xFF

    # Update secondary entrance flag if needed
    if secondary_flag:
        data[roff + 1] = old_byte1 | 0x02   # Set bit 1 = secondary entrance mode

    dest_high  = 0x100 if sublevel_id >= 0x100 else 0x000
    dest_full  = dest_high | (new_dest & 0xFF)
    print(f"\n  {ok('✓')} Sublevel 0x{sublevel_id:03X}  {level_name(sublevel_id)}")
    print(f"    {info('Screen')}    : 0x{screen:02X}")
    print(f"    {info('Dest byte')} : 0x{old:02X}  →  0x{new_dest & 0xFF:02X}")
    if secondary_mode:
        slot_id      = dest_full   # already has high bit applied
        si           = get_sec_info(data, slot_id)
        dest_high_si = 0x100 if slot_id >= 0x100 else 0x000
        sub_full     = dest_high_si | si['sublevel_low']
        anim_name    = ENTRANCE_ANIM_NAMES.get(si['anim'], '?')
        print(f"    {info('→ sec entrance')} 0x{slot_id:03X}  "
              f"→ sublevel 0x{sub_full:03X} ({level_name(sub_full)})  "
              f"anim={si['anim']} ({anim_name})")
        if si['sublevel_low'] == 0x00:
            # slot sublevel_low is 0x00 which almost certainly means it is unconfigured
            print(f"\n  {err('⚠  Warning:')} slot 0x{slot_id:03X} has sublevel_low=0x00 "
                  f"(likely not configured).")
            print(f"  {opt('→ Run:')} sec-set 0x{slot_id:03X} <sublevel_low_byte>  "
                  f"to point it to the correct sublevel.")
    else:
        print(f"    {info('→ sublevel')}    : 0x{dest_full:03X}  ({level_name(dest_full)})")
    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def cmd_set_screen(data: bytearray, sublevel_id: int, screen_old: int, screen_new: int,
                   out_path: Path) -> bool:
    if screen_new > 0x1F:
        print(err(f"\n  Error: screen_new 0x{screen_new:02X} out of range (max 0x1F).\n"))
        return False

    exits, _ = parse_screen_exits(data, sublevel_id)

    matches = [ex for ex in exits if ex['screen'] == screen_old]
    if not matches:
        available = [f"0x{ex['screen']:02X}" for ex in exits]
        print(err(f"\n  Error: no exit on screen 0x{screen_old:02X}."
                  f"\n  Available screens: {', '.join(available) if available else 'none'}\n"))
        return False

    ex   = matches[0]
    roff = ex['rom_offset']
    b0   = data[roff]
    # Preserve bit7 (new_screen_flag) and bits 6-5 (objID hi = 00), set bits 4-0
    data[roff] = (b0 & 0xE0) | (screen_new & 0x1F)

    name = level_name(sublevel_id)
    print(f"\n  {ok('✓')} Sublevel 0x{sublevel_id:03X}  {name}")
    print(f"    {info('Screen moved')} : 0x{screen_old:02X}  →  0x{screen_new:02X}")
    print(f"    {info('ROM offset')}   : 0x{roff:06X}  "
          f"(byte 0: 0x{b0:02X} → 0x{data[roff]:02X})")
    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def decode_sec_pos(si: dict) -> tuple:
    """Return (x_tile, y_tile, screen) from a secondary entrance info dict."""
    y_tile = (si['byte1'] >> 4) & 0x0F
    x_tile = (si['byte2'] >> 4) & 0x0F
    screen = si['byte3'] & 0x1F
    return x_tile, y_tile, screen


def cmd_sec_info(data: bytes, sec_id: int):
    if sec_id >= SEC_TABLE_SIZE:
        print(err(f"\n  Error: sec ID 0x{sec_id:02X} out of range (max 0x{SEC_TABLE_SIZE-1:02X}).\n"))
        return
    si        = get_sec_info(data, sec_id)
    dest_high = 0x100 if sec_id >= 0x100 else 0x000
    sub_full  = dest_high | si['sublevel_low']
    anim_name = ENTRANCE_ANIM_NAMES.get(si['anim'], '?')
    x_tile, y_tile, screen = decode_sec_pos(si)
    print(f"\n  {hdr('Secondary Entrance')} : 0x{sec_id:03X}")
    print(f"  {info('Sublevel')}           : 0x{sub_full:03X}  ({level_name(sub_full)})")
    print(f"  {info('Screen')}             : 0x{screen:02X}  (byte 3 bits 4-0)")
    print(f"  {info('X position')}         : {x_tile}  (tile column within screen, byte 2 bits 7-4)")
    print(f"  {info('Y position')}         : {y_tile}  (tile row, byte 1 bits 7-4)")
    print(f"  {info('Entrance animation')}  : {si['anim']}  ({anim_name})")
    print(f"  {info('Raw byte1/byte2/byte3')}: 0x{si['byte1']:02X} / 0x{si['byte2']:02X} / 0x{si['byte3']:02X}")
    print()


def cmd_sec_set(data: bytearray, sec_id: int, new_sublevel: int, out_path: Path) -> bool:
    """
    Set the destination sublevel for a secondary entrance slot.

    The slot ID (NOT the sublevel) is passed here. This changes which sublevel
    the player lands in when arriving via this slot.

    The slot determines WHERE Mario appears (which sublevel). The animation,
    screen, and tile position are separate fields in the same slot.

    Use `sec-list` to find slot IDs, or `audit <sublevel>` to see which slots
    land in a given level.

    Example:
      sec-set 0x1CB 0x06 → slot 0x1CB now lands in sublevel 0x106 (YI2)
    """
    if sec_id >= SEC_TABLE_SIZE:
        print(err(f"\n  Error: sec ID 0x{sec_id:02X} out of range.\n"))
        return False
    off     = SEC_SUBLEVEL_OFF + sec_id
    old_sub = data[off]
    data[off] = new_sublevel & 0xFF
    print(f"\n  {ok('✓')} Secondary entrance 0x{sec_id:02X}")
    print(f"    {info('Sublevel')} : 0x{old_sub:02X} ({level_name(old_sub)})  "
          f"→  0x{new_sublevel & 0xFF:02X} ({level_name(new_sublevel & 0xFF)})")
    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def cmd_sec_anim_set(data: bytearray, sec_id: int, new_anim: int, out_path: Path) -> bool:
    """
    Set the entrance animation for a secondary entrance slot.

    The slot ID (NOT the sublevel) is passed here. Slots are the actual storage
    location for animations — levels don't "have" animations; slots do.

    Exits using secondary-entrance mode point to a slot ID. That slot holds the
    animation, screen, and tile position. All exits routed through the same slot
    share the same entrance behavior.

    Use `audit <sublevel>` or `get <sublevel>` to find which slot lands in a level,
    then pass that slot ID here.

    Example:
      audit 0x106 → slot 0x1CA lands in YI2
      sec-anim 0x1CA 6 → sets YI2's entrance to fly-in
    """
    if sec_id >= SEC_TABLE_SIZE:
        print(err(f"\n  Error: sec ID 0x{sec_id:02X} out of range.\n"))
        return False
    if new_anim > 7:
        print(err(f"\n  Error: animation must be 0-7.\n"))
        return False
    off      = SEC_ANIM_OFF + sec_id
    old_anim = data[off]
    data[off] = new_anim
    print(f"\n  {ok('✓')} Secondary entrance 0x{sec_id:02X}")
    print(f"    {info('Animation')} : {old_anim} ({ENTRANCE_ANIM_NAMES.get(old_anim, '?')})  "
          f"→  {new_anim} ({ENTRANCE_ANIM_NAMES.get(new_anim, '?')})")
    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def cmd_sec_screen_set(data: bytearray, sec_id: int, new_screen: int, out_path: Path) -> bool:
    """Change the screen number where Mario appears for a secondary entrance (byte3 bits 4-0)."""
    if sec_id >= SEC_TABLE_SIZE:
        print(err(f"\n  Error: sec ID 0x{sec_id:03X} out of range.\n"))
        return False
    if new_screen > 0x1F:
        print(err(f"\n  Error: screen 0x{new_screen:02X} out of range (max 0x1F).\n"))
        return False
    off        = SEC_BYTE3_OFF + sec_id
    old_byte3  = data[off]
    old_screen = old_byte3 & 0x1F
    # Preserve upper 3 bits, replace bits 4-0
    data[off]  = (old_byte3 & 0xE0) | (new_screen & 0x1F)
    print(f"\n  {ok('✓')} Secondary entrance 0x{sec_id:03X}")
    print(f"    {info('Screen')} : 0x{old_screen:02X}  →  0x{new_screen:02X}")
    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def cmd_sec_pos_set(data: bytearray, sec_id: int, x_tile: int, y_tile: int,
                    out_path: Path) -> bool:
    """Change the X and Y tile position for a secondary entrance.

    byte1 bits 7-4 = Y tile (0-0xF)
    byte2 bits 7-4 = X tile (0-0xF)
    Lower 4 bits of each byte are preserved (flags / reserved).
    """
    if sec_id >= SEC_TABLE_SIZE:
        print(err(f"\n  Error: sec ID 0x{sec_id:03X} out of range.\n"))
        return False
    if not (0 <= x_tile <= 0xF):
        print(err(f"\n  Error: X tile must be 0-15 (0x0-0xF), got {x_tile}.\n"))
        return False
    if not (0 <= y_tile <= 0xF):
        print(err(f"\n  Error: Y tile must be 0-15 (0x0-0xF), got {y_tile}.\n"))
        return False

    off1 = SEC_BYTE1_OFF + sec_id
    off2 = SEC_BYTE2_OFF + sec_id

    old_b1 = data[off1]
    old_b2 = data[off2]
    old_y  = (old_b1 >> 4) & 0x0F
    old_x  = (old_b2 >> 4) & 0x0F

    data[off1] = (y_tile << 4) | (old_b1 & 0x0F)
    data[off2] = (x_tile << 4) | (old_b2 & 0x0F)

    print(f"\n  {ok('✓')} Secondary entrance 0x{sec_id:03X}")
    print(f"    {info('X tile')} : {old_x}  →  {x_tile}")
    print(f"    {info('Y tile')} : {old_y}  →  {y_tile}")
    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def cmd_sec_edit(data: bytearray, sec_id: int, out_path: Path) -> bool:
    """Interactive editor for all fields of a secondary entrance slot."""
    if sec_id >= SEC_TABLE_SIZE:
        print(err(f"\n  Error: sec ID 0x{sec_id:03X} out of range.\n"))
        return False

    si = get_sec_info(data, sec_id)
    dest_high = 0x100 if sec_id >= 0x100 else 0x000
    sub_full  = dest_high | si['sublevel_low']
    x_tile, y_tile, screen = decode_sec_pos(si)
    anim_name = ENTRANCE_ANIM_NAMES.get(si['anim'], '?')

    print(f"\n  {hdr('Interactive editor — Secondary Entrance 0x{sec_id:03X}')}")
    print(f"\n  Current state:")
    print(f"    {info('Sublevel')}   : 0x{sub_full:03X}  ({level_name(sub_full)})")
    print(f"    {info('Screen')}     : 0x{screen:02X}")
    print(f"    {info('X tile')}     : {x_tile}")
    print(f"    {info('Y tile')}     : {y_tile}")
    print(f"    {info('Animation')}  : {si['anim']}  ({anim_name})")
    print(f"\n  {opt('Available animation types:')}")
    for k, v in ENTRANCE_ANIM_NAMES.items():
        print(f"    {k} = {v}")

    changed = False

    def prompt(field: str, current, cast, validator=None):
        nonlocal changed
        raw = input(f"\n  {opt(field)} [{current}] (Enter = keep): ").strip()
        if not raw:
            return current
        try:
            val = cast(raw)
        except ValueError:
            print(err(f"  Invalid value; keeping {current}."))
            return current
        if validator and not validator(val):
            return current
        changed = True
        return val

    new_sub = prompt("New sublevel low byte (hex, e.g. 0x05)", f"0x{si['sublevel_low']:02X}",
                     lambda s: int(s, 16),
                     lambda v: 0 <= v <= 0xFF or (print(err("  Must be 0x00-0xFF.")) and False))
    new_screen = prompt("New screen (hex 0x00-0x1F)", f"0x{screen:02X}",
                        lambda s: int(s, 16),
                        lambda v: 0 <= v <= 0x1F or (print(err("  Must be 0x00-0x1F.")) and False))
    new_x = prompt("New X tile (0-15)", str(x_tile),
                   int,
                   lambda v: 0 <= v <= 0xF or (print(err("  Must be 0-15.")) and False))
    new_y = prompt("New Y tile (0-15)", str(y_tile),
                   int,
                   lambda v: 0 <= v <= 0xF or (print(err("  Must be 0-15.")) and False))
    new_anim = prompt("New animation (0-7)", str(si['anim']),
                      int,
                      lambda v: 0 <= v <= 7 or (print(err("  Must be 0-7.")) and False))

    if not changed:
        print(info("\n  No changes made.\n"))
        return True

    old_b1 = data[SEC_BYTE1_OFF + sec_id]
    old_b2 = data[SEC_BYTE2_OFF + sec_id]
    old_b3 = data[SEC_BYTE3_OFF + sec_id]

    data[SEC_SUBLEVEL_OFF + sec_id] = new_sub & 0xFF
    data[SEC_BYTE1_OFF    + sec_id] = (new_y  << 4) | (old_b1 & 0x0F)
    data[SEC_BYTE2_OFF    + sec_id] = (new_x  << 4) | (old_b2 & 0x0F)
    data[SEC_BYTE3_OFF    + sec_id] = (old_b3 & 0xE0) | (new_screen & 0x1F)
    data[SEC_ANIM_OFF     + sec_id] = new_anim

    print(f"\n  {ok('✓')} Secondary entrance 0x{sec_id:03X} updated.")
    out_path.write_bytes(bytes(data))
    print(ok(f"  Modified in-place: {out_path}\n"))
    return True


def cmd_sec_list(data: bytes):
    print(f"\n  {hdr('Secondary Entrance Table')}  (0x{SEC_TABLE_SIZE} entries)")
    print()
    print(f"  {'ID':>4}  {'Sublvl':>7}  {'Screen':>6}  {'X':>2}  {'Y':>2}  {'Anim':>5}  Name")
    print("  " + "─" * 74)
    for sid in range(SEC_TABLE_SIZE):
        si = get_sec_info(data, sid)
        if all(v == 0 for v in si.values()):
            continue
        dest_high  = 0x100 if sid >= 0x100 else 0x000
        sub_full   = dest_high | si['sublevel_low']
        name       = level_name(sub_full)
        x_tile, y_tile, screen = decode_sec_pos(si)
        print(f"  0x{sid:03X}  0x{sub_full:03X}    0x{screen:02X}   {x_tile:2}  {y_tile:2}  "
              f"  {si['anim']}    {name}")
    print()


def cmd_anim_list(data: bytes):
    """
    List all sublevels that have secondary entrance slots, grouped by sublevel.
    Shows which slots land in each sublevel and their animations.

    This is the inverse of sec-list: sec-list answers "which sublevel does slot X land in?"
    while anim-list answers "which slots land in sublevel Y and what animation do they use?"
    """
    # Collect slots grouped by sublevel
    sublevel_slots = {}
    for sid in range(SEC_TABLE_SIZE):
        si = get_sec_info(data, sid)
        if all(v == 0 for v in si.values()):
            continue
        dest_high  = 0x100 if sid >= 0x100 else 0x000
        sub_full   = dest_high | si['sublevel_low']
        sub_low    = sub_full & 0xFF
        if sub_full not in sublevel_slots:
            sublevel_slots[sub_full] = []
        sublevel_slots[sub_full].append({
            'slot_id': sid,
            'anim':    si['anim'],
            'screen':  si['byte3'] & 0x1F,
            'x':      (si['byte2'] >> 4) & 0x0F,
            'y':      (si['byte1'] >> 4) & 0x0F,
        })

    if not sublevel_slots:
        print(f"\n  {err('No secondary entrance slots found.')}\n")
        return

    print(f"\n  {hdr('Sublevels with Secondary Entrances')}")
    print(f"  {hdr(f'{len(sublevel_slots)} sublevels with slots in use')}")
    print()

    for sub_full in sorted(sublevel_slots.keys()):
        slots = sublevel_slots[sub_full]
        name  = level_name(sub_full)
        print(f"  {hdr('─' * 56)}")
        print(f"  {ok(f'0x{sub_full:03X}')}  {name}")
        print()
        for sl in slots:
            anim_name = ENTRANCE_ANIM_NAMES.get(sl['anim'], '?')
            sid = sl['slot_id']
            scr = sl['screen']
            print(f"    {opt(f'slot 0x{sid:03X}')}  "
                  f"screen=0x{scr:02X}  x={sl['x']}  y={sl['y']}  "
                  f"anim={sl['anim']} ({anim_name})")
        print()
    print()



def cmd_audit(data: bytes, sublevel_ids: list):
    """
    Audit command: for each given sublevel, show exits (where they go)
    and secondary entrances that land in it.
    """
    for sublevel_id in sublevel_ids:
        gba_ptr = get_l1_ptr(data, sublevel_id)

        print(f"\n  {hdr('-' * 56)}")
        print(f"  {hdr('Sublevel')} : 0x{sublevel_id:03X}  {level_name(sublevel_id)}")
        print(f"  {hdr('L1 ptr')}   : 0x{gba_ptr:08X}  (ROM 0x{gba_ptr - GBA_ROM_BASE:06X})")

        exits, secondary_mode = parse_screen_exits(data, sublevel_id)

        # ── Screen exits ────────────────────────────────────────────────
        if exits:
            mode_str = "secondary entrance IDs" if secondary_mode else "direct sublevel IDs"
            print(f"  {info('Exit mode')} : {mode_str}")
            print()
            print(f"  {hdr('Screen Exits →')}")
            print(f"  {'─' * 56}")
            for ex in exits:
                dest_str = format_dest(data, ex, secondary_mode)
                sec_mark = opt("Sec ") if ex['secondary_flag'] else info("Dir  ")
                print(f"    {sec_mark} screen 0x{ex['screen']:02X}  →  {dest_str}")
        else:
            print(f"\n  {info('Screen Exits')} : none")

        # ── Secondary entrances landing here ──────────────────────────────
        sec_entrances = find_secondary_entrances(data, sublevel_id)
        if sec_entrances:
            print()
            print(f"  {hdr('Secondary Entrances landing here →')}")
            print(f"  {'─' * 56}")
            for se in sec_entrances:
                anim_name = ENTRANCE_ANIM_NAMES.get(se['anim'], '?')
                x_tile = (se['byte2'] >> 4) & 0x0F
                y_tile = (se['byte1'] >> 4) & 0x0F
                screen = se['byte3'] & 0x1F
                print(f"    {opt(f'slot 0x{se['slot_id']:03X}')}  "
                      f"screen=0x{screen:02X}  x={x_tile}  y={y_tile}  "
                      f"anim={se['anim']} ({anim_name})")
        else:
            print(f"\n  {info('Secondary Entrances')} : none")
        print()


def cmd_link(data: bytearray, from_sublevel: int, screen: int, to_sublevel: int,
             out_path: Path) -> bool:
    """
    High-level command: wire the exit on <screen> of <from_sublevel> to the
    secondary entrance of <to_sublevel>, auto-resolving the correct slot.

    Steps:
      1. Find all secondary entrance slots that point to to_sublevel.
      2. If none found → error.
      3. If one found  → use it.
      4. If multiple   → show options, ask user to pick.
      5. Ask user which animation (0-7) to set on the slot.
      6. Write animation to the slot.
      7. Write dest byte in the exit object + confirm.
    """

    # ── 1. Validate source level has an exit on that screen ──────────────────
    exits, secondary_mode = parse_screen_exits(data, from_sublevel)
    matches = [ex for ex in exits if ex['screen'] == screen]
    if not matches:
        available = [f"0x{ex['screen']:02X}" for ex in exits]
        print(err(f"\n  Error: no exit on screen 0x{screen:02X} in sublevel "
                  f"0x{from_sublevel:03X}."))
        print(err(f"  Available screens: {', '.join(available) if available else 'none'}\n"))
        return False

    # ── 2. Find secondary entrance slots pointing to to_sublevel ─────────────
    slots = find_secondary_entrances(data, to_sublevel)
    if not slots:
        print(err(f"\n  Error: no secondary entrance slots found for sublevel "
                  f"0x{to_sublevel:03X} ({level_name(to_sublevel)})."))
        print(err(f"  Use sec-list to inspect the table.\n"))
        return False

    # ── 3/4. Pick slot ───────────────────────────────────────────────────────
    if len(slots) == 1:
        chosen = slots[0]
    else:
        print(f"\n  {hdr(f'Multiple secondary entrances found for sublevel 0x{to_sublevel:03X}:')}")
        print()
        for i, sl in enumerate(slots):
            x_tile = (sl['byte2'] >> 4) & 0x0F
            y_tile = (sl['byte1'] >> 4) & 0x0F
            screen_sl = sl['byte3'] & 0x1F
            anim_name = ENTRANCE_ANIM_NAMES.get(sl['anim'], '?')
            print(f"  {opt(f'[{i}]')}  slot 0x{sl['slot_id']:03X}  "
                  f"screen=0x{screen_sl:02X}  x={x_tile}  y={y_tile}  "
                  f"anim={sl['anim']} ({anim_name})")
        print()
        raw_pick = input(f"  {opt('Choose [0]: ')}").strip()
        try:
            pick = int(raw_pick) if raw_pick else 0
            if not (0 <= pick < len(slots)):
                raise ValueError
        except ValueError:
            print(err("  Invalid choice. Aborting.\n"))
            return False
        chosen = slots[pick]

    # ── 5. Ask user for animation ───────────────────────────────────────────
    slot_id   = chosen['slot_id']
    old_anim  = chosen['anim']
    print(f"\n  {hdr('Select entrance animation for slot 0x{:03X}:'.format(slot_id))}")
    print(f"  {info('Available animations:')}")
    for k, v in ENTRANCE_ANIM_NAMES.items():
        marker = " ← current" if k == old_anim else ""
        print(f"    {opt(str(k))} = {v}{marker}")
    print()

    raw_anim = input(f"  {opt('Animation [0-7]: ')}").strip()
    try:
        if raw_anim == "":
            new_anim = 6  # default to fly-in
        else:
            new_anim = int(raw_anim)
            if not (0 <= new_anim <= 7):
                raise ValueError
    except ValueError:
        print(err(f"  Invalid animation. Must be 0-7. Aborting.\n"))
        return False

    anim_name = ENTRANCE_ANIM_NAMES.get(new_anim, '?')

    # ── 6. Write animation to slot ──────────────────────────────────────────
    data[SEC_ANIM_OFF + slot_id] = new_anim

    # ── 7. Compute dest byte and write ──────────────────────────────────────
    dest_byte = slot_id & 0xFF

    ex   = matches[0]
    roff = ex['rom_offset']
    old_dest = ex['dest_low']
    old_byte1 = data[roff + 1]

    # Set the secondary entrance flag (bit 1 of byte 1)
    data[roff + 1] = old_byte1 | 0x02
    data[roff + 3] = dest_byte

    x_tile    = (chosen['byte2'] >> 4) & 0x0F
    y_tile    = (chosen['byte1'] >> 4) & 0x0F
    screen_sl = chosen['byte3'] & 0x1F

    from_name = level_name(from_sublevel)
    to_name   = level_name(to_sublevel)

    print(f"\n  {ok('✓')} Exit linked successfully!")
    print(f"    {info('From')}       : sublevel 0x{from_sublevel:03X} ({from_name})  screen 0x{screen:02X}")
    print(f"    {info('To')}         : sublevel 0x{to_sublevel:03X} ({to_name})")
    print(f"    {info('Slot')}       : 0x{slot_id:03X}")
    print(f"    {info('Appears on')} : screen 0x{screen_sl:02X}  x={x_tile}  y={y_tile}")
    print(f"    {info('Animation')}   : {old_anim} ({ENTRANCE_ANIM_NAMES.get(old_anim, '?')})  →  "
          f"{new_anim} ({anim_name})")
    print(f"    {info('Dest byte')}   : 0x{old_dest:02X}  →  0x{dest_byte:02X}")

    out_path.write_bytes(bytes(data))
    print(ok(f"\n  Modified in-place: {out_path}\n"))
    return True


def cmd_slot_find(data: bytes, sublevel_id: int):
    """
    Find all secondary entrance slots that land in a given sublevel.
    Alias for the landing-in section of cmd_audit(), but focused output.
    """
    slots = find_secondary_entrances(data, sublevel_id)
    name  = level_name(sublevel_id)

    print(f"\n  {hdr('─' * 56)}")
    print(f"  {ok(f'0x{sublevel_id:03X}')}  {name}")
    print(f"  {info(f'{len(slots)} slot(s) land here')}")

    if not slots:
        print(f"\n  {err('No secondary entrance slots point to this sublevel.')}")
        print(f"  {info('Use sec-set to create one, or link an exit to this level first.')}\n")
        return

    print()
    for sl in slots:
        anim_name = ENTRANCE_ANIM_NAMES.get(sl['anim'], '?')
        screen    = sl['byte3'] & 0x1F
        x_tile    = (sl['byte2'] >> 4) & 0x0F
        y_tile    = (sl['byte1'] >> 4) & 0x0F
        sid = sl['slot_id']
        print(f"  {opt(f'slot 0x{sid:03X}')}  "
              f"screen=0x{screen:02X}  x={x_tile}  y={y_tile}  "
              f"anim={sl['anim']} ({anim_name})")
    print()

# ── CLI ───────────────────────────────────────────────────────────────────────

def print_advanced_help():
    border = f"{C.INFO}  {'─' * 52}{C.RESET}"
    print(f"""
{border}
  {hdr('Low-level / Slot Commands')}
{border}

  {info('For direct access to individual secondary entrance slots.')}

  {opt('set-screen')} {ok('<sublevel_id> <old_screen> <new_screen>')}
     Move an exit object to a different screen number.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba set-screen 0x105 0x01 0x03{C.RESET}
     {C.HEADER}→ The exit that was on screen 0x01 is now on screen 0x03.{C.RESET}

  {opt('sec-info')} {ok('<slot_id>')}
     Inspect a secondary entrance slot: sublevel, screen, X/Y, animation.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba sec-info 0x1CB{C.RESET}
     {C.HEADER}→ Shows all fields of slot 0x1CB (the fly-in entrance of YI1).{C.RESET}

  {opt('sec-set')} {ok('<slot_id> <sublevel_low_byte>')}
     Change which sublevel a slot points to (low byte only).
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba sec-set 0x1CB 0x05{C.RESET}
     {C.HEADER}→ Slot 0x1CB now points to sublevel 0x105 (Yoshi's Island 1).{C.RESET}
     {C.HEADER}→ Use slot-find <sublevel> to find which slot to edit.{C.RESET}

  {opt('sec-screen')} {ok('<slot_id> <screen>')}
     Change the screen Mario spawns on when arriving via this slot.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba sec-screen 0x1CB 0x09{C.RESET}
     {C.HEADER}→ Mario now appears on screen 0x09 instead of 0x08.{C.RESET}

  {opt('sec-pos')} {ok('<slot_id> <x> <y>')}
     Change Mario's exact tile position within that screen (0-15 each).
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba sec-pos 0x1CB 5 8{C.RESET}
     {C.HEADER}→ Mario spawns at tile column 5, row 8 on arrival.{C.RESET}

  {opt('sec-anim')} {ok('<slot_id> <0-7>')}
     Change the entrance animation for a slot. Takes a slot ID — not a sublevel.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba sec-anim 0x1CB 4{C.RESET}
     {C.HEADER}→ Mario now comes up from a pipe instead of flying in.{C.RESET}
     {C.HEADER}→ Use slot-find <sublevel> to find which slot to edit.{C.RESET}

     {info('Animation types:')}
       {C.SUCCESS}0{C.RESET} walk right (from left pipe / left edge)
       {C.SUCCESS}1{C.RESET} walk left  (from right pipe / right edge)
       {C.SUCCESS}2{C.RESET} fall from above
       {C.SUCCESS}3{C.RESET} enter pipe from top    (coming down)
       {C.SUCCESS}4{C.RESET} enter pipe from bottom (coming up)
       {C.SUCCESS}5{C.RESET} enter door
       {C.SUCCESS}6{C.RESET} fly in
       {C.SUCCESS}7{C.RESET} warp (no animation / instant)

  {opt('sec-edit')} {ok('<slot_id>')}
     Interactive editor — change all fields of a slot at once.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba sec-edit 0x1CB{C.RESET}
     {C.HEADER}→ Prompts for sublevel, screen, X, Y and animation. Enter = keep.{C.RESET}

  {opt('sec-list')}
     List every non-empty secondary entrance slot in the ROM.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba sec-list{C.RESET}
     {C.HEADER}→ Useful to find which slot IDs are already in use.{C.RESET}
     {C.HEADER}→ See also: anim-list to group by sublevel instead.{C.RESET}

  {opt('slot-find')} {ok('<sublevel_id>')}
     Find all secondary entrance slots that land in a given sublevel.
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba slot-find 0x106{C.RESET}
     {C.HEADER}→ Shows slots pointing to YI2 and their animations.{C.RESET}

  {opt('anim-list')}
     List all sublevels that have slots, grouped — shows which slots land in
     each sublevel and their animations. Inverse of sec-list: sec-list answers
     "which sublevel does slot X land in?" while anim-list answers
     "which slots land in sublevel Y and what animation do they use?"
     {C.SUCCESS}python sma2_exit_editor.py sma2.gba anim-list{C.RESET}
     {C.HEADER}→ See every sublevel and which slot IDs to edit.{C.RESET}

{border}
  {info('Notes on dest byte (set-dest):')}
    Only the LOW BYTE of the destination is stored. The high bit comes
    from the current sublevel range (0x0xx → 0x0xx, 0x1xx → 0x1xx).
    Example: sublevel 0x1CA with dest byte 0xCB → slot 0x1CB.
{border}
""")


def parse_hex(s: str) -> int:
    return int(s.strip(), 16)


def main():
    if len(sys.argv) < 3:
        print_banner()
        print("")
        sys.exit(1)

    rom_path = Path(sys.argv[1])
    command  = sys.argv[2].lower()

    if command in ("help", "--help", "-h", "advanced"):
        print_advanced_help()
        sys.exit(0)

    if command == "sec-list":
        if not rom_path.exists():
            print(err(f"Error: '{rom_path}' not found.")); sys.exit(1)
        raw = rom_path.read_bytes()
        if not check_rom(raw):
            print(err("Warning: file does not look like an SMA2 ROM. Continuing..."))
        cmd_sec_list(raw)
        return

    if command == "anim-list":
        if not rom_path.exists():
            print(err(f"Error: '{rom_path}' not found.")); sys.exit(1)
        raw = rom_path.read_bytes()
        if not check_rom(raw):
            print(err("Warning: file does not look like an SMA2 ROM. Continuing..."))
        cmd_anim_list(raw)
        return

    if command == "slot-find":
        if not rom_path.exists():
            print(err(f"Error: '{rom_path}' not found.")); sys.exit(1)
        raw = rom_path.read_bytes()
        if not check_rom(raw):
            print(err("Warning: file does not look like an SMA2 ROM. Continuing..."))
        if len(sys.argv) < 4:
            print(err("Usage: slot-find <sublevel_id>")); sys.exit(1)
        try:
            sid = parse_hex(sys.argv[3])
        except ValueError:
            print(err(f"Invalid sublevel_id '{sys.argv[3]}'")); sys.exit(1)
        cmd_slot_find(raw, sid)
        return

    if not rom_path.exists():
        print(err(f"Error: '{rom_path}' not found.")); sys.exit(1)

    raw = rom_path.read_bytes()
    if not check_rom(raw):
        print(err("Warning: file does not look like an SMA2 ROM. Continuing..."))

    out = out_path_for(rom_path)

    if command == "list":
        if len(sys.argv) < 4:
            print(err("Usage: list <sublevel_id>")); sys.exit(1)
        try:    cmd_list(raw, parse_hex(sys.argv[3]))
        except ValueError: print(err(f"Invalid sublevel_id '{sys.argv[3]}'")); sys.exit(1)

    elif command == "get":
        if len(sys.argv) < 4:
            print(err("Usage: get <sublevel_id>")); sys.exit(1)
        try:    cmd_get(raw, parse_hex(sys.argv[3]))
        except ValueError: print(err(f"Invalid sublevel_id '{sys.argv[3]}'")); sys.exit(1)

    elif command == "set-dest":
        if len(sys.argv) < 6:
            print(err("Usage: set-dest <sublevel_id> <screen> <dest>")); sys.exit(1)
        try:
            lid = parse_hex(sys.argv[3]); screen = parse_hex(sys.argv[4]); dest = parse_hex(sys.argv[5])
        except ValueError as e: print(err(f"Invalid argument: {e}")); sys.exit(1)
        cmd_set_dest(bytearray(raw), lid, screen, dest, out)

    elif command == "set-screen":
        if len(sys.argv) < 6:
            print(err("Usage: set-screen <sublevel_id> <screen_old> <screen_new>")); sys.exit(1)
        try:
            lid = parse_hex(sys.argv[3]); s_old = parse_hex(sys.argv[4]); s_new = parse_hex(sys.argv[5])
        except ValueError as e: print(err(f"Invalid argument: {e}")); sys.exit(1)
        cmd_set_screen(bytearray(raw), lid, s_old, s_new, out)

    elif command == "sec-info":
        if len(sys.argv) < 4:
            print(err("Usage: sec-info <sec_id>")); sys.exit(1)
        try:    cmd_sec_info(raw, parse_hex(sys.argv[3]))
        except ValueError: print(err(f"Invalid sec_id '{sys.argv[3]}'")); sys.exit(1)

    elif command == "sec-set":
        if len(sys.argv) < 5:
            print(err("Usage: sec-set <sec_id> <sublevel_id>")); sys.exit(1)
        try:
            sid = parse_hex(sys.argv[3]); sub = parse_hex(sys.argv[4])
        except ValueError as e: print(err(f"Invalid argument: {e}")); sys.exit(1)
        cmd_sec_set(bytearray(raw), sid, sub, out)

    elif command == "sec-anim":
        if len(sys.argv) < 5:
            print(err("Usage: sec-anim <sec_id> <anim_0_to_7>")); sys.exit(1)
        try:
            sid = parse_hex(sys.argv[3]); anim = int(sys.argv[4], 0)
        except ValueError as e: print(err(f"Invalid argument: {e}")); sys.exit(1)
        cmd_sec_anim_set(bytearray(raw), sid, anim, out)

    elif command == "sec-screen":
        if len(sys.argv) < 5:
            print(err("Usage: sec-screen <sec_id> <screen_0x00_to_0x1F>")); sys.exit(1)
        try:
            sid = parse_hex(sys.argv[3]); screen = parse_hex(sys.argv[4])
        except ValueError as e: print(err(f"Invalid argument: {e}")); sys.exit(1)
        cmd_sec_screen_set(bytearray(raw), sid, screen, out)

    elif command == "sec-pos":
        if len(sys.argv) < 6:
            print(err("Usage: sec-pos <sec_id> <x_tile_0_to_15> <y_tile_0_to_15>")); sys.exit(1)
        try:
            sid   = parse_hex(sys.argv[3])
            x_arg = sys.argv[4]; y_arg = sys.argv[5]
            x_tile = int(x_arg, 16) if x_arg.startswith("0x") else int(x_arg)
            y_tile = int(y_arg, 16) if y_arg.startswith("0x") else int(y_arg)
        except ValueError as e: print(err(f"Invalid argument: {e}")); sys.exit(1)
        cmd_sec_pos_set(bytearray(raw), sid, x_tile, y_tile, out)

    elif command == "sec-edit":
        if len(sys.argv) < 4:
            print(err("Usage: sec-edit <sec_id>")); sys.exit(1)
        try:    sid = parse_hex(sys.argv[3])
        except ValueError: print(err(f"Invalid sec_id '{sys.argv[3]}'")); sys.exit(1)
        cmd_sec_edit(bytearray(raw), sid, out)

    elif command == "link":
        if len(sys.argv) < 6:
            print(err("Usage: link <from_sublevel> <screen> <to_sublevel>")); sys.exit(1)
        try:
            from_lvl = parse_hex(sys.argv[3])
            screen   = parse_hex(sys.argv[4])
            to_lvl   = parse_hex(sys.argv[5])
        except ValueError as e: print(err(f"Invalid argument: {e}")); sys.exit(1)
        cmd_link(bytearray(raw), from_lvl, screen, to_lvl, out)

    elif command == "audit":
        if len(sys.argv) < 4:
            print(err("Usage: audit <sublevel_id> [<sublevel_id> ...]")); sys.exit(1)
        try:
            ids = [parse_hex(arg) for arg in sys.argv[3:]]
        except ValueError: print(err(f"Invalid sublevel_id")); sys.exit(1)
        cmd_audit(raw, ids)

    else:
        if command in ("help", "--help", "-h", "advanced"):
            print_advanced_help()
        else:
            print(err(f"\n  Unknown command: '{command}'"))
            print(f"  Run without arguments to see the main commands.")
            print(f"  Run with {chr(39)}help{chr(39)} to see all advanced commands.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()